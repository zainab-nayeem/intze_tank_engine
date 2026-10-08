"""
Construction tracker -- keeps the optimizer working WITH the site team
across the whole project, not just at the start.

The engineer records what actually happens (progress, concrete stock,
site changes). The tracker keeps a saved project state (project_state.json)
and, on request, answers: "given what is already built and what we have
left, what is the SMALLEST change that keeps the project safe and on cost?"

Core ideas
  * Stage progress -> overall % complete (weights below are an editable
    assumption, not a standard).
  * Locks: what is already built cannot change. Column count is locked
    once foundation work starts; each stage that has started keeps the
    concrete grade it started with, and its as-built dimensions.
  * Material shortage is a QUANTITY: concrete stock per grade (m3). A
    grade is usable only if the stock covers everything still to be cast
    in that grade.
  * Minimal change: options are ranked by how many decisions they change,
    then by cost-to-complete. Dominated options (costlier AND less safe)
    are dropped first.
  * As-built check: if the site changes after columns are built (e.g.
    seismic re-classification), built columns are compared with what the
    new conditions require; a shortfall is flagged with an indicative
    jacketing (strengthening) estimate.

Everything uses the real engineering engine -- no surrogate -- because
only ~20 designs exist, so exact evaluation is instant.
"""

import json
import math
import os
import sys
from datetime import datetime

from models import DesignInputs
from intze_design_engine import design_intze_tank
from cost_model import GRADE_COST_FACTOR

STATE_FILE = "project_state.json"
GRADES = [20, 25, 30, 35, 40]
COLUMN_OPTIONS = [6, 8, 10, 12]

# Weight of each stage in "% complete" (assumption -- editable).
STAGE_WEIGHTS = {
    "foundation": 0.15, "staging": 0.25, "container_bottom": 0.20,
    "wall": 0.20, "top_dome": 0.10, "finishing": 0.10,
}
# Stages that cast concrete we can quantify from the engine.
CONCRETE_STAGES = ["foundation", "staging", "container_bottom", "wall", "top_dome"]

DEFAULT_SITE = {
    "capacity_liters": 500_000, "staging_height_m": 16.0, "soil_bearing_kpa": 150.0,
    "wind_speed_m_s": 44.0, "seismic_zone_factor": 0.16,
}


# ------------------------------------------------------------------ engine glue
def _design(site, n, grade):
    inputs = DesignInputs(
        capacity_liters=site["capacity_liters"], staging_height_m=site["staging_height_m"],
        num_columns=n, soil_bearing_capacity_kpa=site["soil_bearing_kpa"],
        concrete_grade_mpa=float(grade),
        basic_wind_speed_m_s=site["wind_speed_m_s"], seismic_zone_factor=site["seismic_zone_factor"],
    )
    return inputs, design_intze_tank(inputs)


def stage_volumes(inputs, out):
    """Concrete volume (m3) per stage, rebuilt from the engine's outputs."""
    D = out.internal_diameter_m
    H = out.cylindrical_wall_height_m - inputs.free_board_m
    vol = {
        "foundation": out.foundation_volume_m3,
        "staging": inputs.num_columns * math.pi * (out.staging_column_diameter_mm / 2000) ** 2
                   * inputs.staging_height_m + out.bracing_volume_m3,
        "container_bottom":
            (out.bottom_dome_thickness_mm / 1000) * 2 * math.pi * out.bottom_dome_radius_m
            * out.bottom_dome_rise_m
            + (out.ring_beam_width_mm / 1000) * (out.ring_beam_depth_mm / 1000) * math.pi * D
            + out.cone_volume_m3,
        "wall": (out.cylindrical_wall_thickness_mm / 1000) * math.pi * D * H,
        "top_dome": (out.top_dome_thickness_mm / 1000) * 2 * math.pi * out.top_dome_radius_m
                    * out.top_dome_rise_m,
    }
    return vol


def _factor(grade):
    return GRADE_COST_FACTOR.get(int(grade), 1.0)


# ------------------------------------------------------------------ state
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def new_state(site=None):
    site = dict(site or DEFAULT_SITE)
    # baseline plan = compromise pick of the optimizer for the original site
    from adaptive_reoptimizer import reoptimize
    pick = reoptimize(site, {})["ideal_pick"]
    st = {
        "site": site,
        "plan": {"num_columns": pick["num_columns"], "grade": pick["grade"]},
        "progress": {s: 0.0 for s in STAGE_WEIGHTS},
        "stage_grade": {}, "stage_volume_m3": {},
        "built": {},            # as-built column data, set when staging starts
        "stock_m3": {},         # grade -> m3 available (absent = unlimited)
        "max_cost": None,
        "last_options": [],
        "log": [],
    }
    log(st, "init", f"Project created. Baseline plan: {pick['num_columns']} columns, "
                    f"M{pick['grade']} (compromise pick of the optimizer).")
    return st


def load_state():
    if not os.path.exists(STATE_FILE):
        print("No project yet. Run:  python construction_tracker.py init")
        sys.exit(1)
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=2)


def log(st, kind, text):
    st["log"].append({"time": _now(), "type": kind, "text": text})


def overall_progress(st):
    return sum(STAGE_WEIGHTS[s] * st["progress"][s] for s in STAGE_WEIGHTS)


def locked_columns(st):
    return st["progress"]["foundation"] > 0 or st["progress"]["staging"] > 0


# ------------------------------------------------------------------ updates
def set_progress(st, stage, pct):
    if stage not in STAGE_WEIGHTS:
        print(f"Unknown stage '{stage}'. Stages: {', '.join(STAGE_WEIGHTS)}")
        return
    pct = max(0.0, min(100.0, float(pct)))
    first_start = st["progress"][stage] == 0 and pct > 0
    st["progress"][stage] = pct
    if first_start:
        n, g = st["plan"]["num_columns"], st["plan"]["grade"]
        if stage in CONCRETE_STAGES:
            inputs, out = _design(st["site"], n, g)
            st["stage_grade"][stage] = g
            st["stage_volume_m3"][stage] = round(stage_volumes(inputs, out)[stage], 3)
            if stage == "staging":
                st["built"] = {"num_columns": n, "grade": g,
                               "column_dia_mm": out.staging_column_diameter_mm,
                               "staging_height_m": st["site"]["staging_height_m"]}
        log(st, "progress", f"Stage '{stage}' started at M{g}, {n} columns plan -- "
                            f"grade and dimensions for this stage are now LOCKED.")
    log(st, "progress", f"{stage} set to {pct:.0f}%. Overall project: {overall_progress(st):.0f}% complete.")


def set_stock(st, grade, m3):
    g = str(int(grade))
    if m3 is None:
        st["stock_m3"].pop(g, None)
        log(st, "stock", f"M{g} stock set to unlimited.")
    else:
        st["stock_m3"][g] = float(m3)
        log(st, "stock", f"M{g} concrete available: {float(m3):.1f} m3.")


def set_site(st, key, value):
    if key not in DEFAULT_SITE:
        print(f"Unknown site field '{key}'. Fields: {', '.join(DEFAULT_SITE)}")
        return
    value = float(value)
    if key == "staging_height_m" and st["progress"]["staging"] > 0:
        msg = (f"REFUSED: staging height cannot change from {st['site'][key]} m to {value} m -- "
               "columns are already being cast. This would need a column-extension design "
               "decision by the project engineer.")
        print(msg)
        log(st, "refused", msg)
        return
    old = st["site"][key]
    st["site"][key] = value
    log(st, "site", f"Site data changed: {key} {old} -> {value}.")


# ------------------------------------------------------------------ analysis
def _need_by_grade(st, n, grade_for_free):
    """Concrete still to be cast, grouped by grade, for a candidate plan."""
    need, cost = {}, 0.0
    inputs, out = _design(st["site"], n, grade_for_free)
    free_vol = stage_volumes(inputs, out)
    for s in CONCRETE_STAGES:
        p = st["progress"][s] / 100.0
        if s in st["stage_grade"]:                       # started: locked grade & volume
            g, v = st["stage_grade"][s], st["stage_volume_m3"][s] * (1 - p)
        else:                                            # not started: free to choose
            g, v = grade_for_free, free_vol[s]
        need[g] = need.get(g, 0.0) + v
        cost += v * _factor(g)
    return need, cost, out


def _stock_ok(st, need):
    short = {}
    for g, v in need.items():
        stock = st["stock_m3"].get(str(g))
        if stock is not None and v > stock + 1e-9:
            short[g] = (v, stock)
    return short


def analyse(st):
    plan_n, plan_g = st["plan"]["num_columns"], st["plan"]["grade"]
    col_opts = [st["built"]["num_columns"]] if locked_columns(st) and st["built"] else \
               ([plan_n] if locked_columns(st) else COLUMN_OPTIONS)

    options = []
    for n in col_opts:
        for g in GRADES:
            need, cost, out = _need_by_grade(st, n, g)
            short = _stock_ok(st, need)
            if short:
                continue
            total_cost = cost
            if st["max_cost"] is not None and total_cost > st["max_cost"]:
                continue
            changes = (0 if g == plan_g else 1) + (0 if n == plan_n else 1)
            options.append({"num_columns": n, "grade": g, "cost_to_complete": round(total_cost, 2),
                            "lateral_kn": out.staging_extra_axial_per_column_kn,
                            "required_column_dia_mm": out.staging_column_diameter_mm,
                            "changes": changes, "need": {str(k): round(v, 2) for k, v in need.items()}})

    # drop dominated options (costlier AND less safe)
    def dominated(a):
        return any(b["cost_to_complete"] <= a["cost_to_complete"] and b["lateral_kn"] <= a["lateral_kn"]
                   and (b["cost_to_complete"] < a["cost_to_complete"] or b["lateral_kn"] < a["lateral_kn"])
                   for b in options if b is not a)
    options = [o for o in options if not dominated(o)]
    options.sort(key=lambda o: (o["changes"], o["cost_to_complete"]))

    # what the CURRENT plan would need
    cur_need, cur_cost, cur_out = _need_by_grade(st, plan_n, plan_g)
    cur_short = _stock_ok(st, cur_need)

    # as-built check on columns
    shortfall = None
    if st["built"]:
        b = st["built"]
        _, req_out = _design(st["site"], b["num_columns"], b["grade"])
        req = req_out.staging_column_diameter_mm
        if req > b["column_dia_mm"] + 0.5:
            extra = b["num_columns"] * math.pi / 4 * ((req / 1000) ** 2 - (b["column_dia_mm"] / 1000) ** 2) \
                    * b["staging_height_m"]
            shortfall = {"built_mm": b["column_dia_mm"], "required_mm": req,
                         "jacket_m3": round(extra, 2),
                         "jacket_cost": round(extra * _factor(b["grade"]), 2)}
    return {"options": options, "current_cost": round(cur_cost, 2), "current_short": cur_short,
            "shortfall": shortfall, "current_need": cur_need}


# ------------------------------------------------------------------ reporting
def show_status(st):
    print("=" * 70)
    print(f"PROJECT STATUS   {overall_progress(st):.0f}% complete")
    print("=" * 70)
    for s, w in STAGE_WEIGHTS.items():
        bar = "#" * int(st["progress"][s] / 5) + "." * (20 - int(st["progress"][s] / 5))
        g = f"  [M{st['stage_grade'][s]} locked]" if s in st["stage_grade"] else ""
        print(f"  {s:<17} {bar} {st['progress'][s]:>4.0f}%  (weight {w*100:.0f}%){g}")
    site = st["site"]
    print(f"\nSite: staging {site['staging_height_m']:.0f} m | seismic factor {site['seismic_zone_factor']} | "
          f"wind {site['wind_speed_m_s']} m/s | soil {site['soil_bearing_kpa']:.0f} kPa")
    print(f"Plan: {st['plan']['num_columns']} columns, M{st['plan']['grade']}"
          + ("   (column count LOCKED)" if locked_columns(st) else ""))
    if st["stock_m3"]:
        print("Concrete stock: " + ", ".join(f"M{g}: {v:.0f} m3" for g, v in sorted(st["stock_m3"].items())))
    if st["max_cost"]:
        print(f"Cost cap: {st['max_cost']}")


def advise(st):
    a = analyse(st)
    show_status(st)
    print("\n" + "-" * 70 + "\nADVICE\n" + "-" * 70)
    problems = False

    if a["shortfall"]:
        problems = True
        s = a["shortfall"]
        print(f"! BUILT COLUMNS UNDER-SIZED for current site data: built {s['built_mm']:.0f} mm, "
              f"now required {s['required_mm']:.0f} mm.")
        print(f"  Indicative fix: jacket (thicken) the columns -- about {s['jacket_m3']} m3 extra "
              f"concrete, relative cost +{s['jacket_cost']}. A structural engineer must design this.")
    if a["current_short"]:
        problems = True
        for g, (need, have) in a["current_short"].items():
            print(f"! MATERIAL SHORTFALL: current plan needs {need:.1f} m3 of M{g} but only {have:.1f} m3 is available.")
    if not problems:
        print("No problems with the current plan.")

    opts = a["options"]
    st["last_options"] = opts
    plan_n, plan_g = st["plan"]["num_columns"], st["plan"]["grade"]
    if not opts:
        print("\nNO FEASIBLE OPTION with current stock / cap / locks.")
        print("Relax one of: concrete stock, cost cap, or an already-built element (needs engineer decision).")
        log(st, "advice", "No feasible option.")
        return
    print(f"\nOptions, smallest change first (cost-to-complete of current plan: {a['current_cost']}):")
    for i, o in enumerate(opts[:4], 1):
        tag = "KEEP CURRENT PLAN" if o["changes"] == 0 else f"{o['changes']} change(s)"
        delta = o["cost_to_complete"] - a["current_cost"]
        print(f"  {i}. {o['num_columns']} columns, M{o['grade']}  [{tag}]  "
              f"cost-to-complete {o['cost_to_complete']} ({delta:+.1f}), "
              f"lateral load {o['lateral_kn']:.0f} kN/column")
        print(f"     concrete still needed: " + ", ".join(f"M{g}: {v} m3" for g, v in o["need"].items()))
    best = opts[0]
    if best["changes"] == 0:
        print("\nRECOMMENDATION: the remaining (not yet built) work can continue as planned"
              + (", BUT the built columns must be strengthened first -- see the warning above."
                 if a["shortfall"] else "."))
    else:
        print(f"\nRECOMMENDATION: switch remaining work to M{best['grade']}"
              + (f" and {best['num_columns']} columns" if best["num_columns"] != plan_n else "")
              + " -- the smallest change that keeps the project feasible.")
    print("To adopt an option:  python construction_tracker.py accept <number>")
    log(st, "advice", f"Recommended: {best['num_columns']} columns M{best['grade']} "
                      f"({best['changes']} change(s)); {len(opts)} option(s) found."
                      + (" Column shortfall flagged." if a["shortfall"] else ""))


def accept(st, number):
    opts = st.get("last_options") or []
    i = int(number) - 1
    if i < 0 or i >= len(opts):
        print("No such option. Run 'advise' first.")
        return
    o = opts[i]
    st["plan"] = {"num_columns": o["num_columns"], "grade": o["grade"]}
    log(st, "decision", f"Engineer accepted option {number}: plan is now "
                        f"{o['num_columns']} columns, M{o['grade']} for all work not yet started.")
    print(f"Plan updated: {o['num_columns']} columns, M{o['grade']} for remaining stages.")


def show_log(st):
    print("DECISION LOG")
    for e in st["log"]:
        print(f"  {e['time']}  [{e['type']}]  {e['text']}")


# ------------------------------------------------------------------ demo + CLI
def demo():
    print("\n##### DEMO: a project over time #####\n")
    st = new_state()
    show_status(st)

    print("\n>>> Site engineer: foundation done, columns 60% cast")
    set_progress(st, "foundation", 100)
    set_progress(st, "staging", 60)

    print("\n>>> Store: only 30 m3 of M20 left until next delivery")
    set_stock(st, 20, 30)
    advise(st)
    accept(st, 1)

    print("\n>>> Authority: site re-classified to Seismic Zone V")
    set_site(st, "seismic_zone_factor", 0.36)
    advise(st)

    print("\n>>> Designer tries to raise staging height after columns started")
    set_site(st, "staging_height_m", 20)

    print()
    show_log(st)
    return st


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print("Commands: init | status | progress <stage> <pct> | stock <grade> <m3|none> | "
              "site <field> <value> | cap <cost|none> | advise | accept <n> | log | demo")
        return
    cmd = args[0]
    if cmd == "demo":
        demo()
        return
    if cmd == "init":
        st = new_state()
        save_state(st)
        show_status(st)
        return
    st = load_state()
    if cmd == "status":
        show_status(st)
    elif cmd == "progress":
        set_progress(st, args[1], args[2]); show_status(st)
    elif cmd == "stock":
        set_stock(st, args[1], None if args[2].lower() == "none" else args[2]); show_status(st)
    elif cmd == "site":
        set_site(st, args[1], args[2]); show_status(st)
    elif cmd == "cap":
        st["max_cost"] = None if args[1].lower() == "none" else float(args[1])
        log(st, "cap", f"Cost cap set to {st['max_cost']}."); show_status(st)
    elif cmd == "advise":
        advise(st)
    elif cmd == "accept":
        accept(st, args[1])
    elif cmd == "log":
        show_log(st)
    else:
        print(f"Unknown command '{cmd}'.")
    save_state(st)


if __name__ == "__main__":
    main()
