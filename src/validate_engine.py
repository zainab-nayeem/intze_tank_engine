"""
Validation of the Intze design engine.

Three kinds of checks, each reported PASS / FAIL:

  A. INDEPENDENT RECOMPUTATION -- the key formulas are recalculated here
     from first principles (textbook / code formulas written out again,
     without calling the engine's internals) and compared with what the
     engine reports. Catches coding mistakes.
  B. PHYSICAL SANITY -- the engine must respond to changes in the right
     direction (bigger tank -> bigger diameter; more columns -> less load
     per column; stronger seismic zone -> more column load, ...).
  C. LITERATURE TREND -- cost versus cylinder height/diameter ratio is
     compared with published findings that shallow tanks (H/D ~ 0.2-0.4)
     are cost-optimal for 400-1200 kL:
       - Saxena & Pathak (2024), Indian J. Eng. Mater. Sci. 31, 679-686
       - Tata Consulting Engineers, "Economical design of Intze type
         elevated service reservoirs" (H = D/3 most economical of 3 tested)

What this does NOT prove: that the engine equals a full design office
calculation. It checks internal correctness, sensible behaviour, and
agreement with published trends. Comparison against an actual project
design (e.g. the original VB5 tool) is still to be added.
"""

import csv
import math

from models import DesignInputs
from intze_design_engine import design_intze_tank
from cost_model import total_relative_cost

RESULTS = []


def check(group, name, engine_value, expected, rel_tol=0.005, abs_tol=0.0, note=""):
    ok = abs(engine_value - expected) <= max(abs_tol, rel_tol * abs(expected))
    RESULTS.append({"group": group, "check": name, "engine": round(engine_value, 3),
                    "independent": round(expected, 3), "result": "PASS" if ok else "FAIL", "note": note})
    return ok


def check_true(group, name, condition, detail=""):
    RESULTS.append({"group": group, "check": name, "engine": "", "independent": "",
                    "result": "PASS" if condition else "FAIL", "note": detail})


SIGMA_CT = {20: 1.2, 25: 1.3, 30: 1.5, 35: 1.6, 40: 1.7}   # IS 3370 permissible direct tension, MPa


def A_independent(cap_l, h_s, n, grade, hd=0.9, angle=45.0, wind=44.0, zone=0.16):
    tag = f"A [{cap_l/1000:.0f} kL, {h_s:.0f} m, {n} col, M{grade}, H/D {hd}, cone {angle:.0f} deg]"
    inp = DesignInputs(capacity_liters=cap_l, staging_height_m=h_s, num_columns=n,
                       concrete_grade_mpa=float(grade), hd_ratio=hd, cone_angle_deg=angle,
                       basic_wind_speed_m_s=wind, seismic_zone_factor=zone)
    o = design_intze_tank(inp)

    # geometry from capacity
    V = cap_l / 1000
    D = (4 * V / (math.pi * hd)) ** (1 / 3)
    H = hd * D
    check(tag, "diameter D (m)", o.internal_diameter_m, D, rel_tol=0.001)
    check(tag, "cylinder height incl. 0.3 m freeboard (m)", o.cylindrical_wall_height_m, H + 0.3, rel_tol=0.001)
    check(tag, "geometry holds the capacity: pi/4*D^2*H (m3)", math.pi / 4 * o.internal_diameter_m ** 2 * H, V, rel_tol=0.002)

    # wall: hoop tension T = gamma*H*D/2 ; t = T/sigma_ct ; As = T/150
    T = 9.81 * H * D / 2
    t = max(150.0, math.ceil(T / SIGMA_CT[grade] / 10) * 10)
    check(tag, "wall thickness (mm)", o.cylindrical_wall_thickness_mm, t, abs_tol=10.01)
    check(tag, "hoop steel (mm2/m)", o.cylindrical_wall_hoop_steel_mm2_per_m, T * 1000 / 150, rel_tol=0.005)

    # dead load
    rb = 0.4 * D / 2
    top_t = max(100.0, D * 8.0)
    top_rise = 0.15 * D
    dome = 25 * (top_t / 1000) * 2 * math.pi * (D / 2) * top_rise
    wall = 25 * (o.cylindrical_wall_thickness_mm / 1000) * math.pi * D * H
    water = V * 9.81
    check(tag, "total dead load (kN)", o.total_dead_load_kn, dome + wall + water, rel_tol=0.001)

    # lateral loads recomputed from first principles
    cone_vertical = (D / 2 - rb) * math.tan(math.radians(angle))
    exposed_h = H + 0.3 + top_rise + cone_vertical
    arm = h_s + exposed_h / 2
    p = 0.6 * wind ** 2
    Fw = 0.7 * p * D * exposed_h / 1000
    Mw = Fw * arm
    Ah = (zone / 2) * (1.5 / 2.5) * 2.5
    Fs = Ah * o.total_dead_load_kn
    Ms = Fs * arm
    M = max(Mw, Ms)
    extra = 2 * M / (n * (D / 2))
    check(tag, "extra axial load per column from wind/seismic (kN)", o.staging_extra_axial_per_column_kn, extra,
          rel_tol=0.005, note=f"governing: {'wind' if Mw >= Ms else 'seismic'}")
    check_true(tag, "governing case matches", o.governing_lateral_case == ("wind" if Mw >= Ms else "seismic"),
               f"engine says {o.governing_lateral_case}")

    # column equilibrium: capacity of the column the engine chose >= factored demand
    tiers = max(1, math.ceil(h_s / 4.0))
    le = h_s / tiers
    d = o.staging_column_diameter_mm / 1000
    demand = (o.total_dead_load_kn / n + o.staging_extra_axial_per_column_kn) * 1.5
    ratio = le / d
    Cr = 1.0 if ratio < 12 else max(0.3, 1.25 - ratio / 48)
    capacity = 6.0 * Cr * math.pi / 4 * d ** 2 * 1000
    check_true(tag, "column capacity >= factored demand", capacity >= demand * 0.995,
               f"capacity {capacity:.0f} kN vs demand {demand:.0f} kN")
    check_true(tag, "slenderness within IS 456 limit of 60", ratio <= 60, f"le/D = {ratio:.1f}")


def B_sanity():
    g = "B sanity"
    def d(**kw):
        base = dict(capacity_liters=500_000, staging_height_m=16.0, num_columns=10, concrete_grade_mpa=25.0)
        base.update(kw)
        return design_intze_tank(DesignInputs(**base))

    check_true(g, "bigger capacity -> bigger diameter", d(capacity_liters=800_000).internal_diameter_m > d().internal_diameter_m)
    check_true(g, "bigger capacity -> more concrete", d(capacity_liters=800_000).concrete_volume_m3 > d().concrete_volume_m3)
    check_true(g, "stronger concrete grade -> wall not thicker",
               d(concrete_grade_mpa=35.0).cylindrical_wall_thickness_mm <= d(concrete_grade_mpa=20.0).cylindrical_wall_thickness_mm)
    check_true(g, "more columns -> less lateral load per column",
               d(num_columns=12).staging_extra_axial_per_column_kn < d(num_columns=8).staging_extra_axial_per_column_kn)
    check_true(g, "higher seismic zone -> more load per column",
               d(seismic_zone_factor=0.36).staging_extra_axial_per_column_kn > d(seismic_zone_factor=0.10).staging_extra_axial_per_column_kn)
    check_true(g, "taller staging -> more load per column (seismic governs)",
               d(staging_height_m=24.0).staging_extra_axial_per_column_kn > d(staging_height_m=10.0).staging_extra_axial_per_column_kn)
    check_true(g, "weaker soil -> raft chosen (<100 kPa)", d(soil_bearing_capacity_kpa=80.0).foundation_type == "raft")
    check_true(g, "full water tank: seismic governs at Zone II-V (matches usual practice)",
               d(basic_wind_speed_m_s=55.0, seismic_zone_factor=0.10).governing_lateral_case == "seismic")
    check_true(g, "code path: wind is chosen when seismic force is negligible",
               d(basic_wind_speed_m_s=44.0, seismic_zone_factor=0.005).governing_lateral_case == "wind")
    check_true(g, "lateral load never negative", d().staging_extra_axial_per_column_kn >= 0)


def C_literature():
    g = "C literature trend"
    print("\nCost vs H/D (our model), M25, 12 columns, 16 m staging:")
    print(f"  {'capacity':>9} | best H/D | cost at 0.9 | cost at best | saving | paper's optimum")
    paper = {200: "0.8", 400: "0.3", 600: "0.3", 800: "0.3", 1000: "0.4", 1200: "0.2"}
    for cap in [200, 400, 600, 800, 1000, 1200]:
        rows = []
        for hd in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            o = design_intze_tank(DesignInputs(capacity_liters=cap * 1000, staging_height_m=16, num_columns=12,
                                               concrete_grade_mpa=25.0, hd_ratio=hd))
            rows.append((hd, total_relative_cost(o.concrete_volume_m3, 25, 12)))
        best = min(rows, key=lambda r: r[1])
        c09 = dict(rows)[0.9]
        print(f"  {cap:>6} kL | {best[0]:>8} | {c09:>11.0f} | {best[1]:>12.0f} | {100*(c09-best[1])/c09:>5.0f}% | {paper[cap]}")
        check_true(g, f"{cap} kL: shallow tank (H/D<=0.4) cheaper than H/D 0.9 -- as published",
                   dict(rows)[0.4] < c09, f"cost {dict(rows)[0.4]:.0f} vs {c09:.0f}")


def main():
    cases = [(500_000, 16.0, 8, 25, 0.9, 45.0, 44.0, 0.16),
             (1_000_000, 20.0, 12, 30, 0.4, 45.0, 39.0, 0.24),
             (200_000, 12.0, 6, 20, 0.8, 45.0, 50.0, 0.10),
             (500_000, 16.0, 10, 25, 0.9, 55.0, 44.0, 0.16)]   # 55 deg cone: tests cone geometry
    for c in cases:
        A_independent(*c)
    B_sanity()
    C_literature()

    total = len(RESULTS)
    fails = [r for r in RESULTS if r["result"] == "FAIL"]
    print(f"\n{'=' * 70}\nVALIDATION SUMMARY: {total - len(fails)} / {total} checks passed\n{'=' * 70}")
    for r in fails:
        print(f"FAIL  {r['group']}\n      {r['check']}: engine {r['engine']} vs independent {r['independent']}  {r['note']}")
    with open("validation_report.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "check", "engine", "independent", "result", "note"])
        w.writeheader(); w.writerows(RESULTS)
    print("\nFull table saved to validation_report.csv")


if __name__ == "__main__":
    main()
