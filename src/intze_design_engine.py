"""
Intze Tank Design Engine -- v0.5

Implements the classical hand-calculation procedure for an Intze-type
RCC elevated water tank, following standard design practice used in
Indian civil engineering (IS 3370 for water-retaining structures,
IS 456 for general RCC, IS 875/IS 1893 for wind/seismic lateral load
on the staging, working-stress-style thumb rules for member sizing
that are standard in textbook Intze tank design).

All assumptions are logged into DesignOutputs.assumptions so nothing is
silently guessed.

v0.5 (found by an independent load-path check, Nov 2026):
  * CAPACITY: the tank now holds the requested capacity in total
    (cylinder + conical bottom + bottom dome). Earlier versions sized the
    cylinder alone for 100% of the capacity, so the real tank held about
    18% more water than requested.
  * LOADS ON THE STAGING: the load carried by the columns now includes the
    conical shell, bottom dome, ring beam and the water they hold, plus the
    staging's own weight (columns and bracing). Earlier versions left these
    out, which under-sized the columns and the foundation and
    under-estimated the seismic force. One-third of the staging weight is
    added to the seismic mass (IS 1893 Part 2 practice).
  * The wind/seismic simplifications from v0.2 are unchanged.
"""

import math
from models import DesignInputs, DesignOutputs
from wall_design import design_cylindrical_wall
from staging_design import design_staging_columns
from foundation_design import design_foundation

WATER_DENSITY_KN_M3 = 9.81          # kN/m3
CONCRETE_DENSITY_KN_M3 = 25.0       # kN/m3 for RCC
STEEL_DENSITY_KG_M3 = 7850.0


def _water_volume_m3(D, hd, cone_angle_deg, bottom_rise_ratio, cone_bottom_ratio=0.4):
    """Water volume = cylinder (height hd*D) + conical frustum + bottom dome cap."""
    H = hd * D
    r = D / 2
    a = cone_bottom_ratio * D / 2
    h_cone = (r - a) * math.tan(math.radians(cone_angle_deg))
    v_cyl = math.pi / 4 * D ** 2 * H
    v_cone = math.pi * h_cone / 3 * (r * r + r * a + a * a)
    hb = bottom_rise_ratio * (2 * a)
    v_cap = math.pi * hb / 6 * (3 * a * a + hb * hb)
    return v_cyl + v_cone + v_cap, v_cyl, v_cone, v_cap


def design_intze_tank(inputs: DesignInputs) -> DesignOutputs:
    out = DesignOutputs()
    out.assumptions = []
    out.warnings = []

    # ---- 1. Basic sizing: capacity -> tank dimensions ----
    capacity_m3 = inputs.capacity_liters / 1000.0
    hd_ratio_assumed = inputs.hd_ratio
    out.assumptions.append(
        f"Cylindrical wall height/diameter ratio = {hd_ratio_assumed} "
        "(default 0.9; published studies report lower ratios, about 0.2-0.4, "
        "as cost-optimal for 400-1200 kL tanks -- see validation report)"
    )
    out.assumptions.append(
        "Capacity = water in the cylinder + the conical bottom + the bottom "
        "dome. The diameter is found by solving for that total, so the tank "
        "holds the requested capacity (v0.5; earlier versions put all of it "
        "in the cylinder)."
    )
    cone_bottom_ratio = 0.4
    lo, hi = 0.5, 80.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _water_volume_m3(mid, hd_ratio_assumed, inputs.cone_angle_deg,
                            inputs.bottom_dome_rise_ratio, cone_bottom_ratio)[0] < capacity_m3:
            lo = mid
        else:
            hi = mid
    D = 0.5 * (lo + hi)
    H = hd_ratio_assumed * D
    vol_total, vol_cyl, vol_cone_water, vol_cap_water = _water_volume_m3(
        D, hd_ratio_assumed, inputs.cone_angle_deg, inputs.bottom_dome_rise_ratio, cone_bottom_ratio)
    out.actual_water_volume_m3 = round(vol_total, 2)

    out.internal_diameter_m = round(D, 3)
    out.cylindrical_wall_height_m = round(H + inputs.free_board_m, 3)

    # ---- 2. Cylindrical wall thickness (real hoop-tension design) ----
    water_head_m = H
    wall_design = design_cylindrical_wall(
        diameter_m=D, water_head_m=water_head_m,
        concrete_grade_mpa=inputs.concrete_grade_mpa,
    )
    wall_thickness_mm = wall_design["final_thickness_mm"]
    out.cylindrical_wall_thickness_mm = round(wall_thickness_mm, 1)
    out.cylindrical_wall_hoop_steel_mm2_per_m = wall_design["required_hoop_steel_mm2_per_m"]
    out.assumptions.append(
        f"Cylindrical wall thickness from IS 3370-style hoop tension check: "
        f"max hoop tension {wall_design['max_hoop_tension_kn_per_m']} kN/m at "
        f"base, permissible concrete tensile stress "
        f"{wall_design['permissible_concrete_tensile_stress_mpa']} MPa. "
        f"{wall_design['note']}"
    )
    out.assumptions.append(
        f"Required hoop steel: {wall_design['required_hoop_steel_mm2_per_m']} "
        "mm2 per metre height of wall, sized to carry full hoop tension at "
        f"{150.0} MPa permissible steel stress (crack-width-controlled, "
        "lower than normal RCC's usual 230 MPa)."
    )

    # ---- 3. Top dome ----
    top_dome_radius = D / 2
    top_dome_rise = inputs.top_dome_rise_ratio * D
    top_dome_thickness_mm = max(100.0, D * 8.0)  # ~8mm per metre of dia, min 100mm
    out.top_dome_radius_m = round(top_dome_radius, 3)
    out.top_dome_rise_m = round(top_dome_rise, 3)
    out.top_dome_thickness_mm = round(top_dome_thickness_mm, 1)

    # ---- 4. Bottom (conical) geometry ----
    cone_bottom_diameter = cone_bottom_ratio * D
    out.assumptions.append(
        f"Cone bottom diameter assumed = {cone_bottom_ratio} x internal "
        "diameter (standard Intze proportion range 0.4-0.5)."
    )
    slant_height = (D / 2 - cone_bottom_diameter / 2) / math.cos(
        math.radians(inputs.cone_angle_deg)
    )
    out.cone_bottom_diameter_m = round(cone_bottom_diameter, 3)
    out.cone_slant_height_m = round(slant_height, 3)

    # ---- 5. Bottom dome ----
    bottom_dome_radius = cone_bottom_diameter / 2
    bottom_dome_rise = inputs.bottom_dome_rise_ratio * cone_bottom_diameter
    bottom_dome_thickness_mm = max(150.0, cone_bottom_diameter * 15.0)
    out.bottom_dome_radius_m = round(bottom_dome_radius, 3)
    out.bottom_dome_rise_m = round(bottom_dome_rise, 3)
    out.bottom_dome_thickness_mm = round(bottom_dome_thickness_mm, 1)

    # ---- 6. Ring beam (the defining Intze member) ----
    water_pressure_at_junction_kpa = WATER_DENSITY_KN_M3 * water_head_m
    horizontal_thrust_per_m_kn = (
        water_pressure_at_junction_kpa
        * math.tan(math.radians(90 - inputs.cone_angle_deg))
    )
    hoop_tension_kn = horizontal_thrust_per_m_kn * (D / 2)
    out.ring_beam_hoop_tension_kn = round(hoop_tension_kn, 2)
    out.assumptions.append(
        "Ring beam hoop tension computed from hydrostatic pressure at "
        "the cone/cylinder junction resolved through the cone angle -- "
        "a simplified statics estimate, NOT a full Intze ring-beam "
        "analysis (cone thrust, dome thrust and wall restraint are not "
        "separately resolved). The beam depth rule below is a placeholder. "
        "To be replaced by proper ring-beam statics."
    )
    out.ring_beam_width_mm = 300.0
    out.ring_beam_depth_mm = round(max(450.0, hoop_tension_kn * 1.5), 1)

    # ---- 7. Member volumes and weights (everything that sits above the columns) ----
    cone_r_top = D / 2
    cone_r_bot = cone_bottom_diameter / 2
    cone_thickness_mm = max(300.0, 30.0 * D)
    cone_volume_m3 = (
        (cone_thickness_mm / 1000)
        * math.pi * (cone_r_top + cone_r_bot) * slant_height
    )
    top_dome_volume = (top_dome_thickness_mm / 1000) * 2 * math.pi * top_dome_radius * top_dome_rise
    bottom_dome_volume = (bottom_dome_thickness_mm / 1000) * 2 * math.pi * bottom_dome_radius * bottom_dome_rise
    wall_volume = (wall_thickness_mm / 1000) * math.pi * D * H
    ring_beam_volume = (out.ring_beam_width_mm / 1000) * (out.ring_beam_depth_mm / 1000) * math.pi * D

    water_load = capacity_m3 * WATER_DENSITY_KN_M3      # all the water: cylinder + cone + bottom dome
    shell_load = CONCRETE_DENSITY_KN_M3 * (
        top_dome_volume + wall_volume + cone_volume_m3 + bottom_dome_volume + ring_beam_volume)
    total_dead_load = shell_load + water_load           # carried by the columns at the top
    out.total_dead_load_kn = round(total_dead_load, 2)
    out.assumptions.append(
        f"Load at the top of the columns = tank shell concrete (top dome, "
        f"wall, cone, bottom dome, ring beam) {round(shell_load, 0)} kN + all "
        f"the water {round(water_load, 0)} kN = {round(total_dead_load, 0)} kN. "
        "No live load, snow or platform/ladder weight is included, and only one "
        "ring beam (at the cone top) is counted."
    )

    cone_vertical_height_m = slant_height * math.sin(math.radians(inputs.cone_angle_deg))  # angle is measured from horizontal
    exposed_height_m = H + inputs.free_board_m + top_dome_rise + cone_vertical_height_m
    out.assumptions.append(
        f"Exposed tank-body height for wind/seismic = cylindrical wall "
        f"({round(H + inputs.free_board_m, 2)}m) + top dome rise "
        f"({round(top_dome_rise, 2)}m) + conical portion vertical height "
        f"({round(cone_vertical_height_m, 2)}m) = "
        f"{round(exposed_height_m, 2)}m. Tank body approximated as a plain "
        "cylinder of internal diameter D for wind exposed-area purposes "
        "(ignores wall thickness and dome bulge -- minor, conservative "
        "simplification, see wind_seismic.py)."
    )

    # ---- 8. Staging (wind/seismic + own weight) ----
    tier_target_m = 4.0
    num_tiers_guess = max(1, math.ceil(inputs.staging_height_m / tier_target_m))
    n_brace_rings = max(num_tiers_guess - 1, 0)
    bracing_volume_m3 = n_brace_rings * 0.30 * 0.50 * math.pi * D
    bracing_weight_kn = CONCRETE_DENSITY_KN_M3 * bracing_volume_m3

    staging_result = design_staging_columns(
        total_load_kn=total_dead_load,
        staging_height_m=inputs.staging_height_m,
        num_columns=inputs.num_columns,
        exposed_diameter_m=D,
        exposed_height_m=exposed_height_m,
        basic_wind_speed_m_s=inputs.basic_wind_speed_m_s,
        seismic_zone_factor=inputs.seismic_zone_factor,
        bracing_weight_kn=bracing_weight_kn,
    )
    out.staging_column_diameter_mm = staging_result["column_diameter_mm"]
    out.staging_num_bracing_tiers = staging_result["num_bracing_tiers"]
    out.staging_extra_axial_per_column_kn = staging_result["extra_axial_per_column_from_lateral_kn"]
    out.staging_self_weight_kn = staging_result["staging_self_weight_kn"]
    out.seismic_weight_kn = staging_result["seismic_weight_kn"]
    if "lateral_load_detail" in staging_result:
        out.governing_lateral_case = staging_result["lateral_load_detail"]["governing_case"]
    out.assumptions.append(
        f"Staging split into {staging_result['num_bracing_tiers']} bracing "
        f"tiers ({staging_result['unsupported_length_per_tier_m']}m unsupported "
        "length each, ~4m target spacing assumed). Column sized at its BASE for "
        "the tank load + bracing + its own weight + wind/seismic effect, via "
        f"IS 456-style slenderness check: le/D = "
        f"{staging_result['slenderness_ratio_le_over_d']}, reduction "
        f"coefficient Cr = {staging_result['reduction_coefficient_Cr']}. "
        f"Staging self weight {round(out.staging_self_weight_kn)} kN. "
        f"Seismic mass = tank load + 1/3 staging = {round(out.seismic_weight_kn)} kN. "
        f"Extra axial load from wind/seismic: "
        f"{staging_result['extra_axial_per_column_from_lateral_kn']} kN per "
        "column (added before factoring)."
    )
    if "lateral_load_detail" in staging_result:
        lld = staging_result["lateral_load_detail"]
        out.assumptions.append(
            f"Governing lateral case: {lld['governing_case']} "
            f"(overturning moment = {lld['governing_moment_knm']} kN.m). "
            f"Wind force = {lld['wind']['wind_force_kn']} kN, seismic force = "
            f"{lld['seismic']['seismic_force_kn']} kN."
        )
    for w in staging_result["warnings"]:
        out.warnings.append(w)

    # ---- 9. Foundation: carries the tank AND the staging ----
    permissible_bearing = (
        inputs.permissible_bearing_kpa or inputs.soil_bearing_capacity_kpa
    )
    foundation_load_kn = total_dead_load + out.staging_self_weight_kn
    out.foundation_load_kn = round(foundation_load_kn, 2)
    foundation_result = design_foundation(
        total_load_kn=foundation_load_kn,
        num_columns=inputs.num_columns,
        permissible_bearing_kpa=permissible_bearing,
        column_pitch_circle_diameter_m=D,
    )
    out.foundation_type = foundation_result["foundation_type"]
    if foundation_result["foundation_type"] == "raft":
        out.foundation_size_m = foundation_result["raft_equivalent_diameter_m"]
    else:
        out.foundation_size_m = foundation_result["footing_side_m"]
    for a_ in foundation_result["assumptions"]:
        out.assumptions.append(a_)
    for w in foundation_result["warnings"]:
        out.warnings.append(w)
    if getattr(inputs, "soil_source", "manual") == "auto_map":
        out.warnings.append(
            "Soil bearing capacity was auto-filled from a regional map "
            "lookup, not a site geotechnical report -- this is INDICATIVE "
            "only. Confirm with an actual SPT/plate load test before this "
            "design is treated as final."
        )

    # ---- 10. Rough material quantities ----
    staging_column_volume_m3 = (
        inputs.num_columns
        * math.pi
        * ((staging_result["column_diameter_mm"] / 1000) / 2) ** 2
        * inputs.staging_height_m
    )
    if foundation_result["foundation_type"] == "raft":
        raft_thickness_m = max(0.6, foundation_result["raft_equivalent_diameter_m"] / 15.0)
        foundation_volume_m3 = foundation_result["raft_area_m2"] * raft_thickness_m
    else:
        foundation_volume_m3 = (
            inputs.num_columns
            * foundation_result["footing_area_m2"]
            * (foundation_result["footing_depth_mm"] / 1000)
        )

    tank_body_volume = wall_volume + top_dome_volume + bottom_dome_volume + ring_beam_volume
    concrete_volume = (
        tank_body_volume + cone_volume_m3 + staging_column_volume_m3
        + bracing_volume_m3 + foundation_volume_m3
    )
    out.concrete_volume_m3 = round(concrete_volume, 2)
    out.cone_volume_m3 = round(cone_volume_m3, 2)
    out.foundation_volume_m3 = round(foundation_volume_m3, 2)
    out.bracing_volume_m3 = round(bracing_volume_m3, 2)

    steel_kg = (
        80.0 * (tank_body_volume + cone_volume_m3)
        + 150.0 * staging_column_volume_m3
        + 100.0 * bracing_volume_m3
        + 60.0 * foundation_volume_m3
    )
    out.estimated_steel_kg = round(steel_kg, 1)
    out.assumptions.append(
        f"Concrete volume {out.concrete_volume_m3} m3 = tank body "
        f"{round(tank_body_volume, 1)} + cone {round(cone_volume_m3, 1)} "
        f"(thickness {round(cone_thickness_mm)} mm) + staging columns "
        f"{round(staging_column_volume_m3, 1)} + bracing beams "
        f"{round(bracing_volume_m3, 1)} + foundation "
        f"{round(foundation_volume_m3, 1)}. Cone thickness, raft thickness "
        "and bracing section are placeholder rules, not yet designed members."
    )
    out.assumptions.append(
        "Steel estimated member-wise: 80 kg/m3 tank body and cone, 150 kg/m3 "
        "columns, 100 kg/m3 bracing, 60 kg/m3 foundation (typical textbook "
        "ranges) -- placeholder until real reinforcement design."
    )

    return out


if __name__ == "__main__":
    sample = DesignInputs(
        capacity_liters=500_000,   # 5 lakh litres
        staging_height_m=16.0,
        num_columns=8,
        soil_bearing_capacity_kpa=150.0,
    )
    result = design_intze_tank(sample)
    print("=== Intze Tank Design -- v0.2 output (with wind/seismic) ===")
    for field_name, value in result.__dict__.items():
        if field_name in ("assumptions", "warnings"):
            continue
        print(f"{field_name}: {value}")
    print("\n--- Assumptions logged ---")
    for a in result.assumptions:
        print(f"- {a}")
    if result.warnings:
        print("\n--- Warnings ---")
        for w in result.warnings:
            print(f"! {w}")
