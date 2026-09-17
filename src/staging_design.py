"""
Staging column design -- slenderness/buckling check (IS 456 style).

A tall staging is split into "tiers" by horizontal bracing beams; each
column is only unsupported between consecutive bracing levels, not
over its full height. Slenderness ratio = unsupported length / column
diameter. Beyond a limit, IS 456 requires the column's load capacity
to be reduced using a reduction coefficient -- meaning a "slender"
column needs a bigger diameter than a pure axial-stress calculation
would suggest, purely to resist buckling.

v0.2 scope: axial load + slenderness only. Wind/seismic lateral load
on the staging is a separate, real check (IS 875 / IS 1893) -- NOT
included yet, flagged explicitly below. For a 16m staging this
matters and is planned for the next checkpoint.
"""

import math

MAX_SLENDERNESS_RATIO = 60.0      # IS 456 absolute limit, le/D
SHORT_COLUMN_LIMIT = 12.0         # below this, no slenderness reduction needed
DEFAULT_PERMISSIBLE_STRESS_MPA = 6.0   # placeholder working stress, M25 concrete
DEFAULT_TIER_HEIGHT_M = 4.0       # typical practical bracing spacing


def reduction_coefficient(le_over_d: float) -> float:
    """
    IS 456-style reduction coefficient Cr for slender compression members.
    Cr = 1.0 for short columns (le/D < 12).
    Cr = 1.25 - le/(48*D) for 12 <= le/D <= 60 (standard simplified formula).
    Beyond 60, the column is not permitted -- must add bracing or increase size.
    """
    if le_over_d < SHORT_COLUMN_LIMIT:
        return 1.0
    return 1.25 - (le_over_d / 48.0)


def design_staging_columns(total_load_kn: float, staging_height_m: float,
                            num_columns: int,
                            permissible_stress_mpa: float = DEFAULT_PERMISSIBLE_STRESS_MPA,
                            tier_height_target_m: float = DEFAULT_TIER_HEIGHT_M,
                            load_factor: float = 1.5) -> dict:
    warnings = []

    num_tiers = max(1, math.ceil(staging_height_m / tier_height_target_m))
    unsupported_length_m = staging_height_m / num_tiers

    load_per_column_kn = total_load_kn / num_columns
    factored_load_kn = load_per_column_kn * load_factor

    # Start from a pure axial-stress estimate, then iterate to account
    # for slenderness reduction (bigger diameter -> lower le/D -> less
    # reduction needed -> converges quickly, few iterations suffice).
    diameter_m = math.sqrt(
        4 * (factored_load_kn / (permissible_stress_mpa * 1000)) / math.pi
    )
    diameter_m = max(diameter_m, 0.3)  # 300mm practical minimum

    Cr = 1.0
    le_over_d = 0.0
    for _ in range(15):
        le_over_d = unsupported_length_m / diameter_m
        Cr = reduction_coefficient(le_over_d)
        Cr = max(Cr, 0.3)  # floor to keep the loop numerically sane
        effective_stress = permissible_stress_mpa * Cr
        required_area_m2 = factored_load_kn / (effective_stress * 1000)
        new_diameter_m = math.sqrt(4 * required_area_m2 / math.pi)
        new_diameter_m = max(new_diameter_m, 0.3)
        if abs(new_diameter_m - diameter_m) < 0.001:
            diameter_m = new_diameter_m
            break
        diameter_m = new_diameter_m

    le_over_d = unsupported_length_m / diameter_m

    if le_over_d > MAX_SLENDERNESS_RATIO:
        warnings.append(
            f"Slenderness ratio {le_over_d:.1f} exceeds the IS 456 limit of "
            f"{MAX_SLENDERNESS_RATIO}. Increase bracing tiers (reduce "
            "unsupported length) or increase column diameter beyond what "
            "this iteration converged to -- design as shown is NOT valid."
        )

    warnings.append(
        "Wind and seismic lateral load on the staging (IS 875 / IS 1893) "
        "is NOT yet included -- only vertical (axial) load with slenderness "
        "reduction is checked so far. For a 16m-class staging this is a "
        "real remaining gap, planned for the next checkpoint."
    )

    return {
        "num_bracing_tiers": num_tiers,
        "unsupported_length_per_tier_m": round(unsupported_length_m, 3),
        "load_per_column_kn": round(load_per_column_kn, 2),
        "factored_load_per_column_kn": round(factored_load_kn, 2),
        "column_diameter_m": round(diameter_m, 3),
        "column_diameter_mm": round(diameter_m * 1000, 1),
        "slenderness_ratio_le_over_d": round(le_over_d, 2),
        "reduction_coefficient_Cr": round(Cr, 3),
        "warnings": warnings,
    }


if __name__ == "__main__":
    result = design_staging_columns(
        total_load_kn=6513.67, staging_height_m=16.0, num_columns=8
    )
    print("=== Staging Column Design -- Slenderness Check ===")
    for k, v in result.items():
        if k == "warnings":
            continue
        print(f"{k}: {v}")
    print("\n--- Warnings ---")
    for w in result["warnings"]:
        print(f"! {w}")
