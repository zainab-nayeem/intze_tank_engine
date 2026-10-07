"""
Dataset generator for the ML surrogate model.

No public dataset exists for Intze tank design, so this script BUILDS
one by running the validated engine (models.py + intze_design_engine.py
+ wall_design.py + staging_design.py + foundation_design.py) across a
wide, randomly-sampled range of realistic input parameters. Every row
in the output CSV is a real, physically-consistent design produced by
the actual engineering engine -- not fabricated or scraped data.

Output: intze_dataset.csv, one row per sampled design, with all inputs
and all computed outputs as columns, plus a couple of derived flags
(foundation type, whether any warnings fired) that will be useful
signals for the ML model later.
"""

import csv
import random
from models import DesignInputs
from intze_design_engine import design_intze_tank

# ---- Parameter ranges (realistic engineering bounds) ----
CAPACITY_RANGE_L = (50_000, 2_000_000)       # 50k to 20 lakh litres
STAGING_HEIGHT_RANGE_M = (8.0, 24.0)         # 8m to 24m
NUM_COLUMNS_OPTIONS = [6, 8, 10, 12]
SOIL_BEARING_RANGE_KPA = (80.0, 250.0)
CONCRETE_GRADE_OPTIONS = [20, 25, 30, 35, 40]
WIND_SPEED_RANGE_M_S = (33.0, 55.0)           # IS 875 basic wind speed zones
SEISMIC_ZONE_FACTORS = [0.10, 0.16, 0.24, 0.36]  # IS 1893 Zones II-V

RANDOM_SEED = 42   # fixed seed -- makes the dataset reproducible, an
                    # important detail for academic integrity (anyone
                    # re-running this script gets the exact same dataset)


def sample_inputs() -> DesignInputs:
    return DesignInputs(
        capacity_liters=random.uniform(*CAPACITY_RANGE_L),
        staging_height_m=random.uniform(*STAGING_HEIGHT_RANGE_M),
        num_columns=random.choice(NUM_COLUMNS_OPTIONS),
        soil_bearing_capacity_kpa=random.uniform(*SOIL_BEARING_RANGE_KPA),
        concrete_grade_mpa=float(random.choice(CONCRETE_GRADE_OPTIONS)),
        basic_wind_speed_m_s=random.uniform(*WIND_SPEED_RANGE_M_S),
        seismic_zone_factor=random.choice(SEISMIC_ZONE_FACTORS),
    )


def generate_dataset(num_samples: int, output_path: str) -> dict:
    random.seed(RANDOM_SEED)

    rows = []
    num_errors = 0

    for i in range(num_samples):
        inputs = sample_inputs()
        try:
            outputs = design_intze_tank(inputs)
        except Exception as e:
            num_errors += 1
            continue  # skip failed samples, log count at the end

        row = {
            # inputs
            "capacity_liters": round(inputs.capacity_liters, 1),
            "staging_height_m": round(inputs.staging_height_m, 2),
            "num_columns": inputs.num_columns,
            "soil_bearing_capacity_kpa": round(inputs.soil_bearing_capacity_kpa, 1),
            "concrete_grade_mpa": inputs.concrete_grade_mpa,
            "basic_wind_speed_m_s": round(inputs.basic_wind_speed_m_s, 1),
            "seismic_zone_factor": inputs.seismic_zone_factor,
            # outputs
            "internal_diameter_m": outputs.internal_diameter_m,
            "cylindrical_wall_height_m": outputs.cylindrical_wall_height_m,
            "cylindrical_wall_thickness_mm": outputs.cylindrical_wall_thickness_mm,
            "cylindrical_wall_hoop_steel_mm2_per_m": outputs.cylindrical_wall_hoop_steel_mm2_per_m,
            "top_dome_thickness_mm": outputs.top_dome_thickness_mm,
            "bottom_dome_thickness_mm": outputs.bottom_dome_thickness_mm,
            "cone_bottom_diameter_m": outputs.cone_bottom_diameter_m,
            "ring_beam_hoop_tension_kn": outputs.ring_beam_hoop_tension_kn,
            "ring_beam_depth_mm": outputs.ring_beam_depth_mm,
            "staging_column_diameter_mm": outputs.staging_column_diameter_mm,
            "staging_num_bracing_tiers": outputs.staging_num_bracing_tiers,
            "foundation_type": outputs.foundation_type,
            "foundation_size_m": outputs.foundation_size_m,
            "total_dead_load_kn": outputs.total_dead_load_kn,
            "staging_extra_axial_per_column_kn": outputs.staging_extra_axial_per_column_kn,
            "governing_lateral_case": outputs.governing_lateral_case,
            "concrete_volume_m3": outputs.concrete_volume_m3,
            "estimated_steel_kg": outputs.estimated_steel_kg,
            # derived flags -- useful signals for the ML model later
            "has_warnings": 1 if outputs.warnings else 0,
            "num_warnings": len(outputs.warnings),
        }
        rows.append(row)

    if rows:
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    return {
        "requested_samples": num_samples,
        "successful_rows": len(rows),
        "failed_samples": num_errors,
        "output_path": output_path,
    }


if __name__ == "__main__":
    result = generate_dataset(num_samples=8000, output_path="intze_dataset.csv")
    print("=== Dataset Generation Complete ===")
    for k, v in result.items():
        print(f"{k}: {v}")
