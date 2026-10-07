"""
Adaptive re-optimization under changing real-world constraints.

A tank is optimized once at design time -- but construction does not go
exactly to plan: a supplier stops delivering a concrete grade, part of
the structure is already built, the site is re-classified to a higher
seismic zone, a budget cap appears. This module takes a TIMELINE of
such events, applies them cumulatively, and after each one:

  1. re-runs the multi-objective optimizer (ML surrogate + NSGA-II)
     under the new site data and the new restrictions,
  2. verifies every candidate against the real engineering engine,
  3. applies hard limits (cost cap / lateral-load cap) on the verified
     numbers,
  4. picks the best remaining compromise design,
  5. reports what must CHANGE versus the previous step, and the
     "price of the constraint": how much worse the pick is than what
     would have been possible with no restrictions at the same site.

Selection rule (stated explicitly because it is a decision-maker
preference, not physics): the "compromise pick" is the design closest to
the ideal corner (cheapest AND lowest lateral load), with both objectives
scaled 0-1 over the UNRESTRICTED Pareto front at the current site.
Change PICK_WEIGHT_COST to favour cost (>0.5) or safety (<0.5).
"""

import csv
import math

from models import DesignInputs
from intze_design_engine import design_intze_tank
from cost_model import total_relative_cost
from optimizer import run_optimization, NUM_COLUMNS_OPTIONS, CONCRETE_GRADE_OPTIONS

PICK_WEIGHT_COST = 0.5   # 0.5 = cost and safety equally important

BASE_SITE = {
    "capacity_liters": 500_000, "staging_height_m": 16.0, "soil_bearing_kpa": 150.0,
    "wind_speed_m_s": 44.0, "seismic_zone_factor": 0.16,
}

# Each event: what happened, and what it changes. Changes accumulate.
#   site changes:        any key of BASE_SITE
#   restrictions:        column_options, grade_options (what is still possible)
#   hard limits:         max_cost, max_extra_axial_kn
TIMELINE = [
    dict(month=0, label="Baseline design (original site data)", changes={}),
    dict(month=1, label="Foundation team has already cast 10 column footings",
         changes={"column_options": [10]}),
    dict(month=2, label="Cement supplier can no longer deliver M35 / M40",
         changes={"grade_options": [20, 25, 30]}),
    dict(month=3, label="Revised hydraulic design raises staging from 16 m to 20 m",
         changes={"staging_height_m": 20.0}),
    dict(month=4, label="Site re-classified to Seismic Zone V (zone factor 0.36)",
         changes={"seismic_zone_factor": 0.36}),
    dict(month=5, label="Client imposes a relative-cost cap of 243",
         changes={"max_cost": 243.0}),
]


def _real(candidate, site):
    inputs = DesignInputs(
        capacity_liters=site["capacity_liters"], staging_height_m=site["staging_height_m"],
        num_columns=candidate["num_columns"], soil_bearing_capacity_kpa=site["soil_bearing_kpa"],
        concrete_grade_mpa=float(candidate["concrete_grade_mpa"]),
        basic_wind_speed_m_s=site["wind_speed_m_s"], seismic_zone_factor=site["seismic_zone_factor"],
    )
    out = design_intze_tank(inputs)
    cost = total_relative_cost(out.concrete_volume_m3, candidate["concrete_grade_mpa"],
                               candidate["num_columns"])
    return {
        "num_columns": candidate["num_columns"],
        "grade": candidate["concrete_grade_mpa"],
        "cost": round(cost, 2),
        "axial_kn": out.staging_extra_axial_per_column_kn,
        "column_dia_mm": out.staging_column_diameter_mm,
        "foundation": out.foundation_type,
        "lateral_case": out.governing_lateral_case,
        "num_warnings": len(out.warnings),
        "slenderness_warning": any("Slenderness" in w for w in out.warnings),
    }


def _verified_front(site, column_options=None, grade_options=None):
    cands = run_optimization(site, column_options=column_options, grade_options=grade_options)
    return [_real(c, site) for c in cands]


def _pick(front, reference_front):
    """Closest to the ideal corner, scaled over the reference (unrestricted) front."""
    cmin = min(d["cost"] for d in reference_front)
    cmax = max(d["cost"] for d in reference_front)
    amin = min(d["axial_kn"] for d in reference_front)
    amax = max(d["axial_kn"] for d in reference_front)
    cs = (cmax - cmin) or 1.0
    as_ = (amax - amin) or 1.0

    def dist(d):
        nc = (d["cost"] - cmin) / cs
        na = (d["axial_kn"] - amin) / as_
        return math.sqrt(PICK_WEIGHT_COST * nc ** 2 + (1 - PICK_WEIGHT_COST) * na ** 2)
    return min(front, key=dist)


def reoptimize(site, restrictions):
    """One adaptive step. Returns dict with the full verified fronts and the pick."""
    unrestricted = _verified_front(site)
    restricted = _verified_front(
        site, restrictions.get("column_options"), restrictions.get("grade_options"))

    feasible = [d for d in restricted
                if d["cost"] <= restrictions.get("max_cost", float("inf"))
                and d["axial_kn"] <= restrictions.get("max_extra_axial_kn", float("inf"))]

    result = {"unrestricted": unrestricted, "restricted": restricted, "feasible": feasible}
    result["ideal_pick"] = _pick(unrestricted, unrestricted)
    result["pick"] = _pick(feasible, unrestricted) if feasible else None
    return result


def run_timeline(events=TIMELINE, base_site=BASE_SITE):
    site = dict(base_site)
    restrictions = {}
    previous_pick = None
    log = []

    print("=" * 74)
    print("ADAPTIVE RE-OPTIMIZATION TIMELINE")
    print("=" * 74)

    for ev in events:
        for key, value in ev["changes"].items():
            if key in site or key in BASE_SITE:
                site[key] = value
            else:
                restrictions[key] = value

        res = reoptimize(site, restrictions)
        pick, ideal = res["pick"], res["ideal_pick"]

        print(f"\n--- Month {ev['month']}: {ev['label']} ---")
        active = []
        if "column_options" in restrictions:
            active.append(f"columns limited to {restrictions['column_options']}")
        if "grade_options" in restrictions:
            active.append("grades limited to " + ", ".join(f"M{g}" for g in restrictions["grade_options"]))
        if "max_cost" in restrictions:
            active.append(f"cost cap {restrictions['max_cost']}")
        print(f"Site: staging {site['staging_height_m']:.0f} m, seismic factor "
              f"{site['seismic_zone_factor']}, soil {site['soil_bearing_kpa']:.0f} kPa"
              + ("  |  Restrictions: " + "; ".join(active) if active else ""))

        row = {"month": ev["month"], "event": ev["label"],
               "staging_height_m": site["staging_height_m"],
               "seismic_zone_factor": site["seismic_zone_factor"],
               "feasible_designs": len(res["feasible"])}

        if pick is None:
            cheapest = min(res["restricted"], key=lambda d: d["cost"])
            print("!! NO FEASIBLE DESIGN under the current restrictions.")
            print(f"   Cheapest option available costs {cheapest['cost']} "
                  f"({cheapest['num_columns']} columns, M{cheapest['grade']}); "
                  f"the cap is {restrictions.get('max_cost')}. "
                  "A restriction must be relaxed. Options tested:")
            found_any = False
            for name, label in (("column_options", "unlock the column count"),
                                ("grade_options", "allow all concrete grades"),
                                ("max_cost", "remove the cost cap")):
                if name not in restrictions:
                    continue
                relaxed = {k: v for k, v in restrictions.items() if k != name}
                alt = reoptimize(site, relaxed)
                if name == "max_cost":
                    best = min(alt["feasible"], key=lambda d: d["cost"]) if alt["feasible"] else None
                    best_txt = "cheapest feasible"
                else:
                    best = _pick(alt["feasible"], alt["unrestricted"]) if alt["feasible"] else None
                    best_txt = "best pick"
                if best:
                    found_any = True
                    print(f"   - {label}: feasible -> {best_txt} is {best['num_columns']} columns, "
                          f"M{best['grade']} (cost {best['cost']}, lateral load "
                          f"{best['axial_kn']:.0f} kN/column)")
                else:
                    print(f"   - {label}: still infeasible")
            if not found_any:
                print("   No single relaxation is enough.")
            row.update({"pick": "INFEASIBLE"})
            log.append(row)
            continue

        print(f"Unrestricted best here : {ideal['num_columns']} columns, M{ideal['grade']}  "
              f"(cost {ideal['cost']}, lateral load {ideal['axial_kn']:.0f} kN/column)")
        print(f"Best under restrictions: {pick['num_columns']} columns, M{pick['grade']}  "
              f"(cost {pick['cost']}, lateral load {pick['axial_kn']:.0f} kN/column, "
              f"column dia {pick['column_dia_mm']:.0f} mm, {pick['foundation']})")

        price_cost = (pick["cost"] - ideal["cost"]) / ideal["cost"] * 100
        price_axial = (pick["axial_kn"] - ideal["axial_kn"]) / ideal["axial_kn"] * 100
        if abs(price_cost) > 0.05 or abs(price_axial) > 0.05:
            print(f"Compared with the unrestricted best: cost {price_cost:+.1f}%, "
                  f"lateral load {price_axial:+.1f}%  "
                  "(difference caused by the restrictions)")
        else:
            print("Compared with the unrestricted best: identical (restrictions do not hurt here)")

        if previous_pick is None:
            print("Action: this is the baseline plan.")
        else:
            changes = []
            if pick["num_columns"] != previous_pick["num_columns"]:
                changes.append(f"columns {previous_pick['num_columns']} -> {pick['num_columns']}")
            if pick["grade"] != previous_pick["grade"]:
                changes.append(f"grade M{previous_pick['grade']} -> M{pick['grade']}")
            if pick["foundation"] != previous_pick["foundation"]:
                changes.append(f"foundation {previous_pick['foundation']} -> {pick['foundation']}")
            if changes:
                print("Action required: " + "; ".join(changes))
            else:
                print("Action required: none, current plan remains the best choice.")
            print(f"Change vs previous plan: cost {pick['cost'] - previous_pick['cost']:+.1f}, "
                  f"lateral load {pick['axial_kn'] - previous_pick['axial_kn']:+.0f} kN/column")
        if pick["slenderness_warning"]:
            print("WARNING: engine reports a slenderness limit violation for this design -- "
                  "needs more bracing tiers or a larger column; not a valid final design as is.")

        row.update({"pick": f"{pick['num_columns']} columns M{pick['grade']}",
                    "pick_cost": pick["cost"], "pick_lateral_kn": pick["axial_kn"],
                    "unrestricted_best": f"{ideal['num_columns']} columns M{ideal['grade']}",
                    "unrestricted_cost": ideal["cost"], "unrestricted_lateral_kn": ideal["axial_kn"],
                    "price_cost_pct": round(price_cost, 2), "price_lateral_pct": round(price_axial, 2)})
        log.append(row)
        previous_pick = pick

    keys = []
    for r in log:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open("adaptive_log.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(log)
    print("\nLog saved to adaptive_log.csv")
    return log


if __name__ == "__main__":
    run_timeline()
