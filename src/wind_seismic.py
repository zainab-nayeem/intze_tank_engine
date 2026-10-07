"""
Wind and seismic lateral load on the staging -- IS 875 (wind) / IS 1893
(seismic) simplified static methods, following the standard approach
used for elevated water tank staging (e.g. IITK-GSDMA guidelines for
elevated tanks): the tank + water is treated as a single lumped mass
at its centre of gravity, height above ground = staging height + half
the tank body height. Both wind and seismic produce a horizontal force
at that height, which creates an OVERTURNING MOMENT at the base of the
staging. That moment is resisted by the columns acting as a couple --
the windward-side columns get extra compression, the leeward-side
columns get extra tension (or reduced compression), on top of their
share of the pure vertical dead load.

IS 1893 does not require wind and seismic to be combined -- design
for whichever governs (this is standard practice, not a simplification
we're choosing for convenience).

v1 scope and flagged simplifications:
  - Wind force coefficient Cf = 0.7, a standard textbook value for a
    circular tank shape -- IS 875 gives a more detailed Cf depending
    on height/diameter ratio and Reynolds number, not implemented here.
  - Terrain/height/topography factors (k1, k2, k3) for wind are taken
    as 1.0 (i.e., basic wind speed used directly as design wind speed)
    -- a real design would adjust for terrain category and height,
    this is a conservative-ish placeholder, not a precise value.
  - Seismic uses fixed importance factor I=1.5 (water tanks are
    classified as important structures per IS 1893) and response
    reduction factor R=2.5 (typical for RCC staging), with Sa/g=2.5
    (the flat part of the design spectrum, a common conservative
    assumption for the short-period range elevated tanks usually fall
    into) -- a full seismic design would compute the actual time
    period and read Sa/g off the real spectrum.
  - The overturning-moment-to-column-force conversion uses the
    standard "columns as a ring resisting a couple" formula for n
    equally spaced columns: P_extra_max = 2*M / (n*R), R = pitch
    circle radius. This is the same simplified method commonly used
    in elevated-tank staging textbook examples.
  - Exposed diameter/height for the wind force approximate the tank
    body as a cylinder of its internal diameter and body height --
    ignores the wall thickness addition and the dome bulge, a minor
    conservative simplification.
"""

import math

WIND_FORCE_COEFFICIENT = 0.7   # Cf for a circular/cylindrical shape

SEISMIC_IMPORTANCE_FACTOR = 1.5    # I, water tanks are "important" structures
SEISMIC_RESPONSE_REDUCTION_FACTOR = 2.5   # R, typical for RCC staging
SEISMIC_SA_OVER_G = 2.5            # flat-spectrum plateau value, short period


def wind_force_and_moment(exposed_diameter_m: float, exposed_height_m: float,
                           staging_height_m: float,
                           basic_wind_speed_m_s: float) -> dict:
    design_wind_speed = basic_wind_speed_m_s  # k1=k2=k3=1.0, flagged above
    design_wind_pressure_pa = 0.6 * design_wind_speed ** 2   # IS 875 formula, N/m2

    exposed_area_m2 = exposed_diameter_m * exposed_height_m
    wind_force_kn = (WIND_FORCE_COEFFICIENT * design_wind_pressure_pa * exposed_area_m2) / 1000

    height_of_action_m = staging_height_m + exposed_height_m / 2
    overturning_moment_knm = wind_force_kn * height_of_action_m

    return {
        "design_wind_pressure_pa": round(design_wind_pressure_pa, 1),
        "wind_force_kn": round(wind_force_kn, 2),
        "height_of_action_m": round(height_of_action_m, 2),
        "overturning_moment_knm": round(overturning_moment_knm, 2),
    }


def seismic_force_and_moment(total_dead_load_kn: float,
                              exposed_height_m: float,
                              staging_height_m: float,
                              seismic_zone_factor: float) -> dict:
    Ah = (seismic_zone_factor / 2) * (SEISMIC_IMPORTANCE_FACTOR /
                                       SEISMIC_RESPONSE_REDUCTION_FACTOR) * SEISMIC_SA_OVER_G
    seismic_force_kn = Ah * total_dead_load_kn

    height_of_action_m = staging_height_m + exposed_height_m / 2
    overturning_moment_knm = seismic_force_kn * height_of_action_m

    return {
        "design_horizontal_seismic_coefficient_Ah": round(Ah, 4),
        "seismic_force_kn": round(seismic_force_kn, 2),
        "height_of_action_m": round(height_of_action_m, 2),
        "overturning_moment_knm": round(overturning_moment_knm, 2),
    }


def compute_lateral_load_effects(exposed_diameter_m: float, exposed_height_m: float,
                                  staging_height_m: float, total_dead_load_kn: float,
                                  num_columns: int, column_pitch_circle_diameter_m: float,
                                  basic_wind_speed_m_s: float = 44.0,
                                  seismic_zone_factor: float = 0.16) -> dict:
    warnings = [
        "Wind/seismic uses simplified IS 875/IS 1893 static methods with "
        "standard textbook factors (Cf=0.7, terrain factors=1.0, I=1.5, "
        "R=2.5, Sa/g=2.5) -- not a substitute for a full dynamic analysis, "
        "but a real improvement over ignoring lateral load entirely."
    ]

    wind = wind_force_and_moment(
        exposed_diameter_m, exposed_height_m, staging_height_m, basic_wind_speed_m_s,
    )
    seismic = seismic_force_and_moment(
        total_dead_load_kn, exposed_height_m, staging_height_m, seismic_zone_factor,
    )

    # IS 1893: design for whichever governs, don't combine
    if wind["overturning_moment_knm"] >= seismic["overturning_moment_knm"]:
        governing_case = "wind"
        governing_moment_knm = wind["overturning_moment_knm"]
    else:
        governing_case = "seismic"
        governing_moment_knm = seismic["overturning_moment_knm"]

    R = column_pitch_circle_diameter_m / 2
    if num_columns < 3:
        warnings.append(
            f"num_columns={num_columns} is too few for the ring-of-columns "
            "overturning formula (needs >=3 evenly spaced columns) -- "
            "lateral load effect not reliably computed."
        )
        max_extra_axial_per_column_kn = 0.0
    else:
        max_extra_axial_per_column_kn = (2 * governing_moment_knm) / (num_columns * R)

    return {
        "wind": wind,
        "seismic": seismic,
        "governing_case": governing_case,
        "governing_moment_knm": round(governing_moment_knm, 2),
        "max_extra_axial_per_column_kn": round(max_extra_axial_per_column_kn, 2),
        "warnings": warnings,
    }
