"""
Cylindrical wall design -- hoop tension method (IS 3370 style).

Replaces the v0.1 empirical thickness rule with an actual structural
check: water pressure creates hoop (ring) tension in the wall; the
wall must be thick enough that concrete alone stays under its
permissible tensile stress (crack control for water-retaining
structures), and reinforcement is sized to carry the full tension at
a reduced permissible steel stress.

v0.2 uses the MAXIMUM hoop tension (at the base, full water depth) as
the governing case for a uniform wall thickness. This is a known
conservative simplification -- a real IS 3370 design uses base-fixity
coefficient tables (H^2/Dt) that reduce tension near the base due to
restraint from the base slab/ring beam. That refinement is flagged
below and left for a later checkpoint; using the conservative value
now is the correct thing to do for a first structural pass -- it
never under-designs.
"""

import math

WATER_DENSITY_KN_M3 = 9.81

# Permissible DIRECT tensile stress in concrete (N/mm2, MPa), working
# stress method, values used for water-retaining structure design
# (concrete alone, to prevent cracking). Standard textbook values.
PERMISSIBLE_TENSILE_STRESS_CONCRETE_MPA = {
    20: 1.2,
    25: 1.3,
    30: 1.5,
    35: 1.6,
    40: 1.7,
}

# Permissible tensile stress in steel for members in direct tension in
# water-retaining structures (Fe415) -- kept low vs normal RCC (usually
# 230 MPa) specifically to control crack width and keep the tank watertight.
PERMISSIBLE_STEEL_STRESS_WATER_TANK_MPA = 150.0

MIN_WALL_THICKNESS_MM = 150.0


def hoop_tension_at_depth(diameter_m: float, depth_m: float) -> float:
    """Hoop tension T (kN per metre of wall height) at a given water depth."""
    radius_m = diameter_m / 2
    return WATER_DENSITY_KN_M3 * depth_m * radius_m


def design_cylindrical_wall(diameter_m: float, water_head_m: float,
                             concrete_grade_mpa: float) -> dict:
    """
    Returns required wall thickness and hoop steel area, based on the
    maximum hoop tension (at the base, full water depth).
    """
    grade_key = int(concrete_grade_mpa)
    sigma_ct = PERMISSIBLE_TENSILE_STRESS_CONCRETE_MPA.get(grade_key, 1.3)

    T_max_kn_per_m = hoop_tension_at_depth(diameter_m, water_head_m)

    # Required thickness (mm): sigma(MPa) = T(kN/m) / t(mm)  =>  t = T / sigma
    required_thickness_mm = T_max_kn_per_m / sigma_ct
    required_thickness_mm = max(MIN_WALL_THICKNESS_MM, required_thickness_mm)
    # Round up to nearest 10mm (standard practical construction increment)
    final_thickness_mm = math.ceil(required_thickness_mm / 10.0) * 10.0

    # Required hoop steel area (mm2 per metre height of wall) to carry
    # the FULL tension at the permissible steel stress (i.e., assume
    # concrete has cracked and steel alone resists -- standard
    # conservative design assumption)
    required_steel_mm2_per_m = (T_max_kn_per_m * 1000) / PERMISSIBLE_STEEL_STRESS_WATER_TANK_MPA

    return {
        "max_hoop_tension_kn_per_m": round(T_max_kn_per_m, 2),
        "permissible_concrete_tensile_stress_mpa": sigma_ct,
        "required_thickness_mm": round(required_thickness_mm, 1),
        "final_thickness_mm": final_thickness_mm,
        "required_hoop_steel_mm2_per_m": round(required_steel_mm2_per_m, 1),
        "note": (
            "Governing case = maximum hoop tension at wall base (full "
            "water depth), applied uniformly up the whole wall. This is "
            "conservative -- ignores tension relief from base-slab/ring-"
            "beam fixity (IS 3370 H^2/Dt coefficient tables), which would "
            "allow a tapered, thinner wall higher up. Refinement planned "
            "for a later checkpoint; conservative value is safe to use now."
        ),
    }


if __name__ == "__main__":
    result = design_cylindrical_wall(
        diameter_m=8.91, water_head_m=8.319, concrete_grade_mpa=25.0
    )
    print("=== Cylindrical Wall -- Hoop Tension Design ===")
    for k, v in result.items():
        print(f"{k}: {v}")
