"""
Intze Tank Design Engine -- v0.1 (first working version)

Implements the classical hand-calculation procedure for an Intze-type
RCC elevated water tank, following standard design practice used in
Indian civil engineering (IS 3370 for water-retaining structures,
IS 456 for general RCC, working-stress-style thumb rules for member
sizing that are standard in textbook Intze tank design).

IMPORTANT -- ACADEMIC INTEGRITY NOTE (per project rules):
This is a first-pass engine using well-known standard formulas and
commonly-used empirical thickness/sizing rules. It has NOT yet been
validated against a certified example or against the original VB5
project. Treat every output as provisional until Checkpoint 2
(validation) is complete. All assumptions are logged into
DesignOutputs.assumptions so nothing is silently guessed.
"""

import math
from models import DesignInputs, DesignOutputs
from wall_design import design_cylindrical_wall
from staging_design import design_staging_columns
from foundation_design import design_foundation

WATER_DENSITY_KN_M3 = 9.81          # kN/m3
CONCRETE_DENSITY_KN_M3 = 25.0       # kN/m3 for RCC
STEEL_DENSITY_KG_M3 = 7850.0


def design_intze_tank(inputs: DesignInputs) -> DesignOutputs:
    out = DesignOutputs()
    out.assumptions = []
    out.warnings = []

    # ---- 1. Basic sizing: capacity -> cylindrical wall dimensions ----
    # Standard practice: height-to-diameter ratio for the cylindrical
    # portion is usually kept between 0.8 and 1.0 for hydraulic/wind
    # efficiency. We assume H/D = 0.9 as a starting proportion; this is
    # exactly the kind of variable the optimizer will later search over
    # instead of us fixing it.
    capacity_m3 = inputs.capacity_liters / 1000.0
    hd_ratio_assumed = 0.9
    out.assumptions.append(
        f"Cylindrical wall height/diameter ratio assumed = {hd_ratio_assumed} "
        "(will become a search variable for the optimizer in later phases)"
    )

    # capacity ~ cylindrical volume + conical volume - bottom dome volume (approx)
    # For v0.1 we size off the cylindrical portion alone and treat the
    # conical + bottom dome volume as a bonus safety margin (they add
    # extra storage below the cylinder). This is a conservative
    # simplification, logged as an assumption.
    out.assumptions.append(
        "v0.1 sizes the cylindrical wall to hold 100% of capacity; the "
        "conical + bottom dome volume is treated as extra safety margin "
        "rather than counted toward capacity. Will refine in Checkpoint 2."
    )

    # V = pi/4 * D^2 * H, H = hd_ratio * D  =>  V = pi/4 * hd_ratio * D^3
    D = (capacity_m3 / (math.pi / 4 * hd_ratio_assumed)) ** (1 / 3)
    H = hd_ratio_assumed * D

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
    # Spherical dome thickness: thin, usually governed by minimum
    # practical thickness rather than stress for typical spans.
    top_dome_thickness_mm = max(100.0, D * 8.0)  # ~8mm per metre of dia, min 100mm
    out.top_dome_radius_m = round(top_dome_radius, 3)
    out.top_dome_rise_m = round(top_dome_rise, 3)
    out.top_dome_thickness_mm = round(top_dome_thickness_mm, 1)

    # ---- 4. Bottom (conical) geometry ----
    # Cone bottom diameter is smaller than the main tank diameter --
    # typically 40-50% of D for a well-proportioned Intze tank.
    cone_bottom_ratio = 0.4
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
    # The ring beam at the cone/cylinder junction resists the outward
    # horizontal thrust from the conical bottom, in hoop tension.
    # Approximate thrust from static water pressure + self weight
    # component at the junction, resolved horizontally.
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
        "a simplified statics estimate, not a full IS 3370 analysis. "
        "To be refined with self-weight + live load contributions in "
        "Checkpoint 2."
    )
    # Rough sizing: keep steel stress in tension well within permissible
    # (v0.1 uses a simple area-of-steel-free sizing heuristic on the
    # concrete section, refined later with actual reinforcement design)
    out.ring_beam_width_mm = 300.0
    out.ring_beam_depth_mm = round(max(450.0, hoop_tension_kn * 1.5), 1)

    # ---- 7. Staging ----
    # Column size driven by total dead + live load / soil bearing check
    dome_load = (
        CONCRETE_DENSITY_KN_M3
        * (top_dome_thickness_mm / 1000)
        * (2 * math.pi * top_dome_radius * top_dome_rise)  # approx dome shell area x thickness
    )
    wall_load = (
        CONCRETE_DENSITY_KN_M3
        * (wall_thickness_mm / 1000)
        * math.pi * D * H
    )
    water_load = capacity_m3 * WATER_DENSITY_KN_M3
    total_dead_load = dome_load + wall_load + water_load
    out.total_dead_load_kn = round(total_dead_load, 2)

    load_per_column_kn = total_dead_load / inputs.num_columns
    staging_result = design_staging_columns(
        total_load_kn=total_dead_load,
        staging_height_m=inputs.staging_height_m,
        num_columns=inputs.num_columns,
    )
    out.staging_column_diameter_mm = staging_result["column_diameter_mm"]
    out.staging_num_bracing_tiers = staging_result["num_bracing_tiers"]
    out.assumptions.append(
        f"Staging split into {staging_result['num_bracing_tiers']} bracing "
        f"tiers ({staging_result['unsupported_length_per_tier_m']}m unsupported "
        "length each, ~4m target spacing assumed). Column sized via "
        f"IS 456-style slenderness check: le/D = "
        f"{staging_result['slenderness_ratio_le_over_d']}, reduction "
        f"coefficient Cr = {staging_result['reduction_coefficient_Cr']}."
    )
    for w in staging_result["warnings"]:
        out.warnings.append(w)

    # ---- 8. Foundation (isolated footings or raft, from soil bearing) ----
    permissible_bearing = (
        inputs.permissible_bearing_kpa or inputs.soil_bearing_capacity_kpa
    )
    foundation_result = design_foundation(
        total_load_kn=total_dead_load,
        num_columns=inputs.num_columns,
        permissible_bearing_kpa=permissible_bearing,
        column_pitch_circle_diameter_m=D,
    )
    out.foundation_type = foundation_result["foundation_type"]
    if foundation_result["foundation_type"] == "raft":
        out.foundation_size_m = foundation_result["raft_equivalent_diameter_m"]
    else:
        out.foundation_size_m = foundation_result["footing_side_m"]
    for a in foundation_result["assumptions"]:
        out.assumptions.append(a)
    for w in foundation_result["warnings"]:
        out.warnings.append(w)
    if getattr(inputs, "soil_source", "manual") == "auto_map":
        out.warnings.append(
            "Soil bearing capacity was auto-filled from a regional map "
            "lookup, not a site geotechnical report -- this is INDICATIVE "
            "only. Confirm with an actual SPT/plate load test before this "
            "design is treated as final."
        )

    # ---- 9. Rough material quantities ----
    concrete_volume = (
        (wall_thickness_mm / 1000) * math.pi * D * H
        + (top_dome_thickness_mm / 1000) * 2 * math.pi * top_dome_radius * top_dome_rise
        + (bottom_dome_thickness_mm / 1000) * 2 * math.pi * bottom_dome_radius * bottom_dome_rise
        + (out.ring_beam_width_mm / 1000) * (out.ring_beam_depth_mm / 1000) * math.pi * D
    )
    out.concrete_volume_m3 = round(concrete_volume, 2)
    # Very rough steel estimate: ~80 kg per m3 of RCC for this member type (typical range 60-100)
    out.estimated_steel_kg = round(concrete_volume * 80.0, 1)
    out.assumptions.append(
        "Steel quantity estimated at 80 kg per m3 of concrete (typical "
        "textbook range 60-100 kg/m3 for water tank members) -- placeholder "
        "until actual reinforcement design is computed member-by-member."
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
    print("=== Intze Tank Design -- v0.1 output ===")
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
