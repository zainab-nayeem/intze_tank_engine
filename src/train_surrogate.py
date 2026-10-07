"""
ML Surrogate Model Training -- v0.1

Trains fast-predicting ML models that approximate the validated
engineering engine's outputs. Purpose: the optimizer (NSGA-II, next
checkpoint) needs to evaluate thousands of candidate designs quickly;
re-running the full physics-based engine for every candidate would be
slow, so the surrogate stands in for it during the search, with the
real engine used to VERIFY the final chosen design.

This only works if the surrogate is actually accurate -- so this
script trains on 80% of the dataset and tests on the other 20% it
never saw, reporting real error metrics rather than just "it trained."

Targets chosen: the three outputs most relevant to optimization --
wall thickness, staging column diameter, and concrete volume (proxy
for material cost).
"""

import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

INPUT_FEATURES = [
    "capacity_liters",
    "staging_height_m",
    "num_columns",
    "soil_bearing_capacity_kpa",
    "concrete_grade_mpa",
    "basic_wind_speed_m_s",
    "seismic_zone_factor",
]

TARGETS = [
    "cylindrical_wall_thickness_mm",
    "staging_column_diameter_mm",
    "concrete_volume_m3",
    "staging_extra_axial_per_column_kn",
]


def train_and_evaluate(dataset_path: str, model_output_prefix: str = "surrogate") -> dict:
    df = pd.read_csv(dataset_path)

    results = {}
    for target in TARGETS:
        X = df[INPUT_FEATURES]
        y = df[target]

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # RandomForest: chosen because it's CPU-only friendly, handles
        # non-linear relationships (which these engineering formulas
        # definitely have -- e.g. hoop tension scales with diameter AND
        # height together), and needs no feature scaling.
        model = RandomForestRegressor(
            n_estimators=200, max_depth=None, min_samples_leaf=2, random_state=42, n_jobs=-1
        )
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        mean_target = y_test.mean()
        mae_pct = (mae / mean_target) * 100

        model_path = f"{model_output_prefix}_{target}.joblib"
        joblib.dump(model, model_path)

        results[target] = {
            "r2_score": round(r2, 4),
            "mean_absolute_error": round(mae, 3),
            "mae_as_pct_of_mean": round(mae_pct, 2),
            "test_set_mean_value": round(mean_target, 3),
            "model_saved_to": model_path,
        }

    return results


if __name__ == "__main__":
    results = train_and_evaluate("intze_dataset.csv")
    print("=== Surrogate Model Training Results ===\n")
    for target, metrics in results.items():
        print(f"Target: {target}")
        for k, v in metrics.items():
            print(f"  {k}: {v}")
        print()
