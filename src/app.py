"""
Intze Tank Platform -- web app (stage 1: login, roles, project overview,
site desk, advice).

Run from the src folder:   python app.py      then open http://127.0.0.1:5000

ROLES (checked on the SERVER for every action, not just hidden in menus):
  manager  Project Manager / Design Engineer -- everything, including site
           data, cost cap and approving a changed plan.
  site     Site Engineer -- logs progress and concrete stock, sees advice,
           CANNOT change site data / cost cap or approve a changed plan.
  client   Client / Viewer -- read-only.

DEMO ACCOUNTS ONLY: the three passwords below are for demonstration and
must be replaced (and the SECRET_KEY set) before any real deployment.
The project data is the same project_state.json the command-line tracker uses.
"""

import io
import json
import os
import secrets
from contextlib import redirect_stdout
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import construction_tracker as ct
import optimizer as opt
import regional_planner as rp
import visualize_tank as vt
from cost_model import total_relative_cost
from intze_design_engine import design_intze_tank
from models import DesignInputs

app = Flask(__name__)
app.secret_key = os.environ.get("INTZE_SECRET_KEY", "demo-only-change-me")

ROLE_LABEL = {"manager": "Project Manager", "site": "Site Engineer", "client": "Client"}
ROLE_CAN = {
    "manager": {"view", "log", "site_data", "approve", "start"},
    "site": {"view", "log"},
    "client": {"view"},
}

USERS = {
    "manager": {"name": "Project Manager", "role": "manager",
                "hash": generate_password_hash("Manager@123")},
    "site": {"name": "Site Engineer", "role": "site",
             "hash": generate_password_hash("Site@123")},
    "client": {"name": "Client", "role": "client",
               "hash": generate_password_hash("Client@123")},
}

STAGE_LABEL = {
    "foundation": "Foundation", "staging": "Staging columns",
    "container_bottom": "Container bottom", "wall": "Cylindrical wall",
    "top_dome": "Top dome", "finishing": "Finishing",
}


# ------------------------------------------------------------ helpers
def project_exists():
    return os.path.exists(ct.STATE_FILE)


def get_state():
    with open(ct.STATE_FILE) as f:
        return json.load(f)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["STAGE_LABEL"] = STAGE_LABEL


@app.before_request
def load_user():
    g.user = None
    uname = session.get("user")
    if uname in USERS:
        g.user = {"username": uname, **USERS[uname]}
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            abort(400)


@app.context_processor
def inject():
    can = ROLE_CAN.get(g.user["role"], set()) if g.user else set()
    return {"user": g.user, "can": can, "role_label": ROLE_LABEL}


def need(permission):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                return redirect(url_for("login"))
            if permission not in ROLE_CAN[g.user["role"]]:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def quiet(fn, *a, **kw):
    """Run a tracker function that prints; keep its output out of the server console."""
    with redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def by(text):
    return f"{text} (by {ROLE_LABEL[g.user['role']]})"


# ------------------------------------------------------------ auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("overview"))
    if request.method == "POST":
        u = USERS.get(request.form.get("username", "").strip().lower())
        if u and check_password_hash(u["hash"], request.form.get("password", "")):
            session.clear()
            session["user"] = request.form["username"].strip().lower()
            return redirect(url_for("overview"))
        flash("That username and password do not match. Check both and try again.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def home():
    return redirect(url_for("overview"))


# ------------------------------------------------------------ pages
@app.route("/overview")
@need("view")
def overview():
    if not project_exists():
        return render_template("empty.html", page="overview")
    st = get_state()
    return render_template(
        "overview.html", page="overview", st=st,
        pct=ct.overall_progress(st), weights=ct.STAGE_WEIGHTS,
        locked=ct.locked_columns(st), recent=list(reversed(st["log"]))[:8])


@app.route("/site-desk")
@need("log")
def site_desk():
    if not project_exists():
        return render_template("empty.html", page="site")
    st = get_state()
    return render_template("site_desk.html", page="site", st=st,
                           grades=ct.GRADES, weights=ct.STAGE_WEIGHTS)


DESIGN_LIMITS = {
    "capacity_kl": (50, 2000, "Capacity (kL)"),
    "staging_height_m": (6, 30, "Staging height (m)"),
    "soil_bearing_kpa": (50, 500, "Soil bearing (kPa)"),
    "wind_speed_m_s": (30, 60, "Basic wind speed (m/s)"),
    "seismic_zone_factor": (0.05, 0.40, "Seismic zone factor"),
}


@app.route("/design", methods=["GET", "POST"])
@need("view")
def design():
    form = {"capacity_kl": 500, "staging_height_m": 16, "soil_bearing_kpa": 150,
            "wind_speed_m_s": 44, "seismic_zone_factor": 0.16}
    results = None
    dropped = 0
    if request.method == "POST":
        vals = {}
        for key, (lo, hi, label) in DESIGN_LIMITS.items():
            raw = request.form.get(key, "").strip()
            form[key] = raw
            try:
                v = float(raw)
            except ValueError:
                flash(f"{label}: enter a number.", "error")
                return render_template("design.html", page="design", form=form,
                                       results=None, dropped=0, limits=DESIGN_LIMITS)
            if not lo <= v <= hi:
                flash(f"{label} must be between {lo} and {hi}.", "error")
                return render_template("design.html", page="design", form=form,
                                       results=None, dropped=0, limits=DESIGN_LIMITS)
            vals[key] = v
        site = {"capacity_liters": vals["capacity_kl"] * 1000,
                "staging_height_m": vals["staging_height_m"],
                "soil_bearing_kpa": vals["soil_bearing_kpa"],
                "wind_speed_m_s": vals["wind_speed_m_s"],
                "seismic_zone_factor": vals["seismic_zone_factor"]}
        try:
            cands = quiet(opt.run_optimization, site)
            results, dropped = quiet(opt.refine_with_real_engine, cands, site)
        except Exception:
            flash("The design could not be computed for these inputs. Check them and try again.", "error")
    return render_template("design.html", page="design", form=form, results=results,
                           dropped=dropped, limits=DESIGN_LIMITS)


# ------------------------------------------------------------ vendor script (not stored in the project)
@app.route("/vendor/plotly.js")
@need("view")
def vendor_plotly():
    """Serves the Plotly.js file from the installed plotly package, so the pages
    work offline and the project repository does not contain a copy of the library."""
    import plotly
    path = os.path.join(os.path.dirname(plotly.__file__), "package_data", "plotly.min.js")
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="application/javascript", max_age=86400)


# ------------------------------------------------------------ design detail (3D + printable summary)
OUTPUT_ROWS = [
    ("Geometry", [
        ("Internal diameter", "internal_diameter_m", "m"), ("Cylinder height (with free board)", "cylindrical_wall_height_m", "m"),
        ("Water held (cylinder + cone + bottom dome)", "actual_water_volume_m3", "m³"),
        ("Cone bottom diameter", "cone_bottom_diameter_m", "m"), ("Cone slant height", "cone_slant_height_m", "m"),
        ("Top dome rise", "top_dome_rise_m", "m"), ("Bottom dome rise", "bottom_dome_rise_m", "m")]),
    ("Shell members", [
        ("Wall thickness", "cylindrical_wall_thickness_mm", "mm"), ("Hoop steel in wall", "cylindrical_wall_hoop_steel_mm2_per_m", "mm² per m"),
        ("Top dome thickness", "top_dome_thickness_mm", "mm"), ("Bottom dome thickness", "bottom_dome_thickness_mm", "mm"),
        ("Ring beam tension (simplified)", "ring_beam_hoop_tension_kn", "kN"), ("Ring beam size", None, "mm")]),
    ("Staging and foundation", [
        ("Column diameter (at base)", "staging_column_diameter_mm", "mm"), ("Bracing tiers", "staging_num_bracing_tiers", ""),
        ("Governing lateral case", "governing_lateral_case", ""), ("Extra axial load per column", "staging_extra_axial_per_column_kn", "kN"),
        ("Load at column tops", "total_dead_load_kn", "kN"), ("Staging self weight", "staging_self_weight_kn", "kN"),
        ("Load on foundation", "foundation_load_kn", "kN"), ("Foundation type", "foundation_type", ""), ("Foundation size", "foundation_size_m", "m")]),
    ("Quantities (rough)", [
        ("Concrete in total", "concrete_volume_m3", "m³"), ("of which cone", "cone_volume_m3", "m³"),
        ("of which bracing beams", "bracing_volume_m3", "m³"), ("of which foundation", "foundation_volume_m3", "m³"),
        ("Steel (assumed intensities)", "estimated_steel_kg", "kg")]),
]


def _num(name, lo, hi, label, source):
    raw = (source.get(name) or "").strip()
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"{label}: enter a number.")
    if not lo <= v <= hi:
        raise ValueError(f"{label} must be between {lo} and {hi}.")
    return v


@app.route("/design/detail")
@need("view")
def design_detail():
    src = request.args
    try:
        vals = {k: _num(k, lo, hi, label, src) for k, (lo, hi, label) in DESIGN_LIMITS.items()}
        n = int(_num("num_columns", 6, 16, "Columns", src))
        grade = int(_num("grade", 20, 40, "Concrete grade", src))
        if grade not in (20, 25, 30, 35, 40):
            raise ValueError("Concrete grade must be 20, 25, 30, 35 or 40.")
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("design"))
    inputs = DesignInputs(
        capacity_liters=vals["capacity_kl"] * 1000, staging_height_m=vals["staging_height_m"], num_columns=n,
        soil_bearing_capacity_kpa=vals["soil_bearing_kpa"], concrete_grade_mpa=float(grade),
        basic_wind_speed_m_s=vals["wind_speed_m_s"], seismic_zone_factor=vals["seismic_zone_factor"])
    out = design_intze_tank(inputs)
    cost = total_relative_cost(out.concrete_volume_m3, grade, n, out.estimated_steel_kg)
    fig = vt.make_single_figure(inputs, out, cost)
    sections = []
    for title, rows in OUTPUT_ROWS:
        items = []
        for label, field, unit in rows:
            if field is None:
                val = f"{out.ring_beam_width_mm:.0f} × {out.ring_beam_depth_mm:.0f}"
            else:
                v = getattr(out, field)
                val = f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
            items.append((label, val, unit))
        sections.append((title, items))
    slender = [w for w in out.warnings if "Slenderness" in w]
    return render_template("detail.html", page="design", inputs=inputs, out=out, cost=cost,
                           sections=sections, fig_json=fig.to_json(), vals=vals, n=n, grade=grade,
                           slender=slender)


# ------------------------------------------------------------ regional planner
DEMO_ZONES_CSV = """name,lat,lon,population,area_km2,density_per_km2,lpcd,growth_rate_pct
DEMO Zone A,26.7200,88.4300,18000,,,135,1.5
DEMO Zone B,26.7290,88.4380,12000,,,135,1.5
DEMO Zone C,26.7120,88.4420,,1.80,6500,135,2.0
DEMO Zone D,26.7350,88.4250,6000,,,100,1.0
DEMO Zone E,26.7080,88.4250,,0.66,5500,135,1.5
DEMO Zone F,26.7400,88.4500,9500,,,135,1.5
"""


@app.route("/regional", methods=["GET", "POST"])
@need("view")
def regional():
    text = DEMO_ZONES_CSV
    result = None
    if request.method == "POST":
        text = (request.form.get("zones") or "").strip() + "\n"
        if len(text) > 20000:
            flash("That is too much text for a zone list (limit 20,000 characters).", "error")
            return render_template("regional.html", page="regional", text=text, result=None)
        try:
            zones = rp.load_zones_from_text(text)
            if not zones:
                raise ValueError("No zones found. The first line must be the column names.")
            arrangements = quiet(rp.plan, zones)
            if not arrangements:
                flash("No arrangement satisfies the service-radius and tank-size limits. "
                      "Increase the radius, allow bigger tanks or add zones.", "error")
            else:
                best = min(arrangements, key=rp.total)
                fig = rp.build_plain_map_figure(zones, best)
                tanks = []
                for i, grp in enumerate(sorted(best["groups"], key=lambda g_: g_["zones"]), 1):
                    d = grp["design"]
                    tanks.append({"no": i, "cap": grp["capacity_kl"], "need": grp["need_kl"],
                                  "serves": ", ".join(zones[j]["name"] for j in grp["zones"]),
                                  "staging": grp["staging_m"], "far": max(grp["dists"]), "d": d})
                by_k = []
                for k in sorted({a_["k"] for a_ in arrangements}):
                    a2 = min((x for x in arrangements if x["k"] == k), key=rp.total)
                    by_k.append({"k": k, "total": rp.total(a2), "tank": a2["tank_cost"],
                                 "oh": rp.SITE_OVERHEAD * k, "dist": a2["dist_cost"], "best": a2 is best})
                sens = []
                for oh in (0, 10, 20, 40, 80, 160, 320):
                    b2 = min(arrangements, key=lambda a_: rp.total(a_, oh))
                    sens.append({"oh": oh, "k": b2["k"], "total": rp.total(b2, oh)})
                result = {"zones": zones, "tanks": tanks, "best": best, "total": rp.total(best),
                          "by_k": by_k, "sens": sens, "fig_json": fig.to_json(),
                          "years": rp.DESIGN_YEARS, "frac": rp.STORAGE_FRACTION,
                          "radius": rp.MAX_SERVICE_RADIUS_KM, "overhead": rp.SITE_OVERHEAD}
        except SystemExit as e:
            flash(str(e), "error")
        except Exception as e:
            flash(f"Could not read the zone list: {e}", "error")
    return render_template("regional.html", page="regional", text=text, result=result)


@app.route("/advice")
@need("view")
def advice():
    if not project_exists():
        return render_template("empty.html", page="advice")
    st = get_state()
    a = ct.analyse(st)
    st["last_options"] = a["options"]
    ct.save_state(st)
    return render_template("advice.html", page="advice", st=st, a=a,
                           plan=st["plan"], locked=ct.locked_columns(st))


# ------------------------------------------------------------ actions
@app.route("/project/start", methods=["POST"])
@need("start")
def start_project():
    if not project_exists():
        st = quiet(ct.new_state)
        ct.save_state(st)
        flash("Project created with the optimiser's balanced pick as the starting plan.", "ok")
    return redirect(url_for("overview"))


@app.route("/progress", methods=["POST"])
@need("log")
def post_progress():
    st = get_state()
    stage = request.form.get("stage", "")
    try:
        pct = float(request.form.get("percent", ""))
    except ValueError:
        flash("Enter the completed percentage as a number from 0 to 100.", "error")
        return redirect(url_for("site_desk"))
    if stage not in ct.STAGE_WEIGHTS:
        abort(400)
    quiet(ct.set_progress, st, stage, pct)
    st["log"][-1]["text"] = by(st["log"][-1]["text"])
    ct.save_state(st)
    flash(f"{STAGE_LABEL[stage]} is now {max(0, min(100, pct)):.0f}% complete.", "ok")
    return redirect(url_for("site_desk"))


@app.route("/stock", methods=["POST"])
@need("log")
def post_stock():
    st = get_state()
    grade = request.form.get("grade", "")
    raw = request.form.get("m3", "").strip().lower()
    if grade not in {str(x) for x in ct.GRADES}:
        abort(400)
    if raw in ("", "none", "unlimited"):
        quiet(ct.set_stock, st, grade, None)
        msg = f"M{grade} stock set to unlimited."
    else:
        try:
            val = float(raw)
            if val < 0:
                raise ValueError
        except ValueError:
            flash("Enter the available concrete in cubic metres, or leave it empty for unlimited.", "error")
            return redirect(url_for("site_desk"))
        quiet(ct.set_stock, st, grade, val)
        msg = f"M{grade} stock set to {val:.1f} m3."
    st["log"][-1]["text"] = by(st["log"][-1]["text"])
    ct.save_state(st)
    flash(msg, "ok")
    return redirect(url_for("site_desk"))


@app.route("/site-data", methods=["POST"])
@need("site_data")
def post_site_data():
    st = get_state()
    changed = []
    refused = []
    for key in ct.DEFAULT_SITE:
        raw = request.form.get(key, "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            flash(f"'{raw}' is not a valid number for {key.replace('_', ' ')}.", "error")
            return redirect(url_for("site_desk"))
        if value == float(st["site"][key]):
            continue
        quiet(ct.set_site, st, key, raw)
        last = st["log"][-1] if st["log"] else None
        if last and last["type"] == "refused":
            refused.append(last["text"])
            continue
        st["log"][-1]["text"] = by(st["log"][-1]["text"])
        changed.append(key)
    cap = request.form.get("max_cost", "").strip().lower()
    try:
        new_cap = None if cap in ("", "none") else float(cap)
    except ValueError:
        flash("Enter the cost cap as a number, or leave it empty for none.", "error")
        return redirect(url_for("site_desk"))
    if new_cap != st["max_cost"]:
        st["max_cost"] = new_cap
        ct.log(st, "cap", by(f"Cost cap set to {new_cap}."))
        changed.append("cost cap")
    ct.save_state(st)
    for text in refused:
        flash(text, "error")
    if changed:
        flash("Saved. Changed: " + ", ".join(c.replace("_", " ") for c in changed)
              + ". Open Advice to see what it means for the plan.", "ok")
    elif not refused:
        flash("Nothing changed.", "ok")
    return redirect(url_for("site_desk"))


@app.route("/accept", methods=["POST"])
@need("approve")
def post_accept():
    st = get_state()
    quiet(ct.accept, st, request.form.get("option", "0"))
    if st["log"] and st["log"][-1]["type"] == "decision":
        st["log"][-1]["text"] = by(st["log"][-1]["text"])
    ct.save_state(st)
    flash("Plan updated for all work not yet started.", "ok")
    return redirect(url_for("advice"))


# ------------------------------------------------------------ errors
@app.errorhandler(403)
def forbidden(e):
    return render_template("denied.html", page=""), 403


@app.errorhandler(400)
def bad(e):
    return render_template("denied.html", page="", bad=True), 400


if __name__ == "__main__":
    print("Intze Tank Platform running at  http://127.0.0.1:5000   (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5000, debug=False)
