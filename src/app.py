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
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import construction_tracker as ct

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
