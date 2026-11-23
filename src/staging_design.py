"""
Staging column design -- slenderness/buckling check (IS 456 style),
now combined with wind/seismic lateral load (see wind_seismic.py).
"""

import math
from wind_seismic import compute_lateral_load_effects

MAX_SLENDERNESS_RATIO = 60.0
SHORT_COLUMN_LIMIT = 12.0
DEFAULT_PERMISSIBLE_STRESS_MPA = 6.0
DEFAULT_TIER_HEIGHT_M = 4.0


def reduction_coefficient(le_over_d: float) -> float:
    if le_over_d < SHORT_COLUMN_LIMIT:
        return 1.0
    return 1.25 - (le_over_d / 48.0)


CONCRETE_DENSITY_KN_M3 = 25.0
SEISMIC_STAGING_MASS_FRACTION = 1.0 / 3.0   # one-third of staging weight joins the tank mass (IS 1893 Part 2 practice)


def design_staging_columns(total_load_kn: float, staging_height_m: float,
                            num_columns: int,
                            exposed_diameter_m: float = None,
                            exposed_height_m: float = None,
                            basic_wind_speed_m_s: float = 44.0,
                            seismic_zone_factor: float = 0.16,
                            permissible_stress_mpa: float = DEFAULT_PERMISSIBLE_STRESS_MPA,
                            tier_height_target_m: float = DEFAULT_TIER_HEIGHT_M,
                            load_factor: float = 1.5,
                            bracing_weight_kn: float = 0.0) -> dict:
    warnings = []

    num_tiers = max(1, math.ceil(staging_height_m / tier_height_target_m))
    unsupported_length_m = staging_height_m / num_tiers

    # ---- v0.5: the load path now includes the staging's own weight ----
    # total_load_kn = weight of everything ABOVE the columns (tank shell,
    # cone, domes, ring beam and all the water). The columns also carry
    # their own self weight and the bracing beams, and one-third of the
    # staging weight is added to the tank mass for the seismic force.
    # Column diameter and weight depend on each other, so we iterate.
    have_lateral = exposed_diameter_m is not None and exposed_height_m is not None
    if not have_lateral:
        warnings.append(
            "Wind and seismic lateral load NOT evaluated -- exposed "
            "tank dimensions were not supplied to the staging design "
            "call. Only vertical (axial) load with slenderness "
            "reduction is checked."
        )
    diameter_m = 0.5
    Cr = 1.0
    lateral_result = None
    extra_axial_per_column_kn = 0.0
    staging_weight_kn = 0.0
    seismic_weight_kn = total_load_kn
    factored_load_kn = 0.0
    load_per_column_kn = 0.0
    for _ in range(80):
        area_m2 = math.pi * diameter_m ** 2 / 4
        column_weight_kn = CONCRETE_DENSITY_KN_M3 * area_m2 * staging_height_m
        staging_weight_kn = num_columns * column_weight_kn + bracing_weight_kn
        seismic_weight_kn = total_load_kn + SEISMIC_STAGING_MASS_FRACTION * staging_weight_kn
        if have_lateral:
            lateral_result = compute_lateral_load_effects(
                exposed_diameter_m=exposed_diameter_m,
                exposed_height_m=exposed_height_m,
                staging_height_m=staging_height_m,
                total_dead_load_kn=seismic_weight_kn,
                num_columns=num_columns,
                column_pitch_circle_diameter_m=exposed_diameter_m,
                basic_wind_speed_m_s=basic_wind_speed_m_s,
                seismic_zone_factor=seismic_zone_factor,
            )
            extra_axial_per_column_kn = lateral_result["max_extra_axial_per_column_kn"]
        # axial load at the BASE of one column
        load_per_column_kn = (total_load_kn + bracing_weight_kn) / num_columns + column_weight_kn
        factored_load_kn = (load_per_column_kn + extra_axial_per_column_kn) * load_factor
        le_over_d = unsupported_length_m / diameter_m
        Cr = max(reduction_coefficient(le_over_d), 0.3)
        required_area_m2 = factored_load_kn / (permissible_stress_mpa * Cr * 1000)
        new_diameter_m = max(math.sqrt(4 * required_area_m2 / math.pi), 0.3)
        if abs(new_diameter_m - diameter_m) < 0.0005:
            diameter_m = new_diameter_m
            break
        diameter_m = 0.5 * (diameter_m + new_diameter_m)   # damped step, converges smoothly
    if lateral_result:
        warnings.extend(lateral_result["warnings"])

    le_over_d = unsupported_length_m / diameter_m

    if le_over_d > MAX_SLENDERNESS_RATIO:
        warnings.append(
            f"Slenderness ratio {le_over_d:.1f} exceeds the IS 456 limit of "
            f"{MAX_SLENDERNESS_RATIO}. Increase bracing tiers or column "
            "diameter -- design as shown is NOT valid."
        )

    result = {
        "num_bracing_tiers": num_tiers,
        "unsupported_length_per_tier_m": round(unsupported_length_m, 3),
        "load_per_column_kn": round(load_per_column_kn, 2),
        "staging_self_weight_kn": round(staging_weight_kn, 2),
        "seismic_weight_kn": round(seismic_weight_kn, 2),
        "extra_axial_per_column_from_lateral_kn": round(extra_axial_per_column_kn, 2),
        "factored_load_per_column_kn": round(factored_load_kn, 2),
        "column_diameter_m": round(diameter_m, 3),
        "column_diameter_mm": round(diameter_m * 1000, 1),
        "slenderness_ratio_le_over_d": round(le_over_d, 2),
        "reduction_coefficient_Cr": round(Cr, 3),
        "warnings": warnings,
    }
    if lateral_result:
        result["lateral_load_detail"] = lateral_result
    return result
