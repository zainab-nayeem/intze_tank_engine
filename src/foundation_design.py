"""
Foundation design -- sizes either isolated footings (one per staging
column) or a raft foundation (one continuous slab), based on soil
bearing capacity.

Decision logic: isolated footings are used when the soil is strong
enough that each footing stays reasonably sized AND adjacent footings
don't overlap given the column spacing. If either fails, a raft is
recommended instead -- this mirrors what a geotechnical/structural
engineer actually checks by hand.

v0.2 scope: working-load sizing only (bearing pressure check). Does
NOT yet include depth-of-foundation-below-ground (frost/scour, not
usually governing in this climate context but flagged), or detailed
punching shear / reinforcement design of the footing itself -- those
are finer-grained checks for a later pass, footing plan-area is the
governing decision at this stage.
"""

import math

MIN_FOOTING_DEPTH_MM = 300.0
FOOTING_SELF_WEIGHT_FACTOR = 1.10  # +10% for footing's own weight, standard assumption
OVERLAP_SAFETY_FACTOR = 1.5        # footing side must be < spacing/this factor


def design_foundation(total_load_kn: float, num_columns: int,
                       permissible_bearing_kpa: float,
                       column_pitch_circle_diameter_m: float) -> dict:
    warnings = []
    assumptions = [
        f"Staging columns assumed arranged on a pitch circle of diameter "
        f"{round(column_pitch_circle_diameter_m, 2)}m (approximated as the "
        "tank's internal diameter) -- actual column layout may differ "
        "slightly, to be confirmed once staging plan geometry is finalized."
    ]

    load_per_column_kn = total_load_kn / num_columns
    footing_load_kn = load_per_column_kn * FOOTING_SELF_WEIGHT_FACTOR

    footing_area_m2 = footing_load_kn / permissible_bearing_kpa
    footing_side_m = math.sqrt(footing_area_m2)

    # Spacing between adjacent column centres along the pitch circle
    circumference_m = math.pi * column_pitch_circle_diameter_m
    spacing_m = circumference_m / num_columns

    footings_overlap = footing_side_m > (spacing_m / OVERLAP_SAFETY_FACTOR)

    if permissible_bearing_kpa < 100 or footings_overlap:
        # -------- RAFT FOUNDATION --------
        raft_load_kn = total_load_kn * FOOTING_SELF_WEIGHT_FACTOR
        raft_area_m2 = raft_load_kn / permissible_bearing_kpa
        raft_equivalent_diameter_m = 2 * math.sqrt(raft_area_m2 / math.pi)

        if footings_overlap and permissible_bearing_kpa >= 100:
            warnings.append(
                f"Isolated footings would need side {footing_side_m:.2f}m "
                f"but column spacing is only {spacing_m:.2f}m -- footings "
                "would overlap, so a RAFT foundation is used instead."
            )
        else:
            warnings.append(
                f"Soil bearing capacity ({permissible_bearing_kpa} kPa) is "
                "low -- isolated footings would be impractically large, "
                "so a RAFT foundation is used instead."
            )

        if raft_equivalent_diameter_m > column_pitch_circle_diameter_m * 1.3:
            warnings.append(
                f"Required raft diameter ({raft_equivalent_diameter_m:.2f}m) "
                "is significantly larger than the staging footprint -- soil "
                "conditions may be marginal for this tank size/height; "
                "consider a pile foundation as an alternative (not "
                "implemented -- flag for geotechnical consultation)."
            )

        return {
            "foundation_type": "raft",
            "raft_area_m2": round(raft_area_m2, 2),
            "raft_equivalent_diameter_m": round(raft_equivalent_diameter_m, 2),
            "footing_side_m": None,
            "footing_depth_mm": None,
            "assumptions": assumptions,
            "warnings": warnings,
        }

    # -------- ISOLATED FOOTINGS --------
    # Rough depth via thumb rule (side/4), min 300mm -- placeholder until
    # punching shear / bending design of the footing is done.
    footing_depth_mm = max(MIN_FOOTING_DEPTH_MM, (footing_side_m / 4) * 1000)
    assumptions.append(
        "Footing depth from thumb rule (side/4, 300mm minimum) -- "
        "placeholder until punching shear and bending design of the "
        "footing slab itself is carried out."
    )

    return {
        "foundation_type": "isolated_footings",
        "footing_side_m": round(footing_side_m, 3),
        "footing_area_m2": round(footing_area_m2, 2),
        "footing_depth_mm": round(footing_depth_mm, 1),
        "raft_area_m2": None,
        "assumptions": assumptions,
        "warnings": warnings,
    }


if __name__ == "__main__":
    print("--- Case 1: good soil (150 kPa) ---")
    result = design_foundation(
        total_load_kn=6513.67, num_columns=8,
        permissible_bearing_kpa=150.0,
        column_pitch_circle_diameter_m=8.91,
    )
    for k, v in result.items():
        print(f"{k}: {v}")

    print("\n--- Case 2: weak soil (80 kPa) ---")
    result2 = design_foundation(
        total_load_kn=6513.67, num_columns=8,
        permissible_bearing_kpa=80.0,
        column_pitch_circle_diameter_m=8.91,
    )
    for k, v in result2.items():
        print(f"{k}: {v}")
