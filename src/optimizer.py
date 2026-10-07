"""
Multi-objective optimizer -- NSGA-II over num_columns and concrete_grade,
using the trained ML surrogate models for fast fitness evaluation.

Site context (capacity, staging height, soil bearing, wind speed,
seismic zone) is FIXED -- it comes from the site, not from the
designer. The genuine design choices are: how many staging columns and
what concrete grade.

Objectives (both minimized):
  1. total_relative_cost -- concrete volume x grade cost factor, plus a
     per-column construction overhead (see cost_model.py)
  2. extra_axial_per_column_kn -- extra compression each column must
     carry from wind/seismic overturning (lower = more structural
     margin against lateral load)

More columns lower objective 2 but raise objective 1, and higher grades
raise cost -- a real Pareto front, not a single "best" answer.

Process (surrogate-in-the-loop): NSGA-II searches with the FAST
surrogates; the Pareto-optimal candidates are then re-run through the
REAL engine to verify the surrogate's predictions.
"""

import numpy as np
import pandas as pd
import joblib
from pymoo.core.problem import Problem
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.optimize import minimize

from models import DesignInputs
from intze_design_engine import design_intze_tank
from cost_model import total_relative_cost

NUM_COLUMNS_OPTIONS = [6, 8, 10, 12]
CONCRETE_GRADE_OPTIONS = [20, 25, 30, 35, 40]


class TankDesignProblem(Problem):
    def __init__(self, site, volume_model, axial_model,
                 column_options=None, grade_options=None):
        self.column_options = list(column_options or NUM_COLUMNS_OPTIONS)
        self.grade_options = list(grade_options or CONCRETE_GRADE_OPTIONS)
        super().__init__(
            n_var=2, n_obj=2, n_constr=0,
            xl=np.array([0, 0]),
            xu=np.array([len(self.column_options) - 1, len(self.grade_options) - 1]),
        )
        self._cache = {}   # (num_columns, grade) -> (cost, axial); only ~20 distinct designs exist
        self.site = site
        self.volume_model = volume_model
        self.axial_model = axial_model

    def _evaluate(self, X, out, *args, **kwargs):
        n = X.shape[0]
        f1 = np.zeros(n)
        f2 = np.zeros(n)
        for i in range(n):
            ci = int(round(np.clip(X[i, 0], 0, len(self.column_options) - 1)))
            gi = int(round(np.clip(X[i, 1], 0, len(self.grade_options) - 1)))
            num_columns = self.column_options[ci]
            grade = self.grade_options[gi]
            if (num_columns, grade) in self._cache:
                f1[i], f2[i] = self._cache[(num_columns, grade)]
                continue
            features = pd.DataFrame([{
                "capacity_liters": self.site["capacity_liters"],
                "staging_height_m": self.site["staging_height_m"],
                "num_columns": num_columns,
                "soil_bearing_capacity_kpa": self.site["soil_bearing_kpa"],
                "concrete_grade_mpa": grade,
                "basic_wind_speed_m_s": self.site["wind_speed_m_s"],
                "seismic_zone_factor": self.site["seismic_zone_factor"],
            }])
            volume = self.volume_model.predict(features)[0]
            f1[i] = total_relative_cost(volume, grade, num_columns)
            f2[i] = self.axial_model.predict(features)[0]
            self._cache[(num_columns, grade)] = (f1[i], f2[i])
        out["F"] = np.column_stack([f1, f2])


def run_optimization(site, pop_size=20, n_gen=30,
                      column_options=None, grade_options=None):
    """column_options / grade_options restrict the search (e.g. columns
    already built, a grade no longer available). Default = all options."""
    column_options = list(column_options or NUM_COLUMNS_OPTIONS)
    grade_options = list(grade_options or CONCRETE_GRADE_OPTIONS)
    volume_model = joblib.load("surrogate_concrete_volume_m3.joblib")
    axial_model = joblib.load("surrogate_staging_extra_axial_per_column_kn.joblib")
    problem = TankDesignProblem(site, volume_model, axial_model,
                                column_options, grade_options)

    # If a choice is locked to a single value (e.g. columns already cast),
    # NSGA-II has nothing to vary in that dimension and stalls. The
    # remaining space is then tiny, so every option is evaluated
    # directly with the surrogate and the Pareto front is taken exactly.
    if len(column_options) == 1 or len(grade_options) == 1:
        combos = [(ci, gi) for ci in range(len(column_options))
                  for gi in range(len(grade_options))]
        out = {}
        problem._evaluate(np.array(combos, dtype=float), out)
        F = out["F"]
        keep = []
        for i in range(len(combos)):
            dominated = any(
                F[j, 0] <= F[i, 0] and F[j, 1] <= F[i, 1]
                and (F[j, 0] < F[i, 0] or F[j, 1] < F[i, 1])
                for j in range(len(combos)) if j != i)
            if not dominated:
                keep.append(i)
        candidates = [{
            "num_columns": column_options[combos[i][0]],
            "concrete_grade_mpa": grade_options[combos[i][1]],
            "surrogate_cost": round(float(F[i, 0]), 2),
            "surrogate_extra_axial_kn": round(float(F[i, 1]), 1),
        } for i in keep]
        candidates.sort(key=lambda c: c["surrogate_cost"])
        return candidates

    result = minimize(problem, NSGA2(pop_size=pop_size), ("n_gen", n_gen),
                      seed=42, verbose=False)

    seen = set()
    candidates = []
    for x, f in zip(result.X, result.F):
        ci = int(round(np.clip(x[0], 0, len(column_options) - 1)))
        gi = int(round(np.clip(x[1], 0, len(grade_options) - 1)))
        if (ci, gi) in seen:
            continue
        seen.add((ci, gi))
        candidates.append({
            "num_columns": column_options[ci],
            "concrete_grade_mpa": grade_options[gi],
            "surrogate_cost": round(float(f[0]), 2),
            "surrogate_extra_axial_kn": round(float(f[1]), 1),
        })
    candidates.sort(key=lambda c: c["surrogate_cost"])
    return candidates


def verify_against_real_engine(candidate, site):
    inputs = DesignInputs(
        capacity_liters=site["capacity_liters"],
        staging_height_m=site["staging_height_m"],
        num_columns=candidate["num_columns"],
        soil_bearing_capacity_kpa=site["soil_bearing_kpa"],
        concrete_grade_mpa=float(candidate["concrete_grade_mpa"]),
        basic_wind_speed_m_s=site["wind_speed_m_s"],
        seismic_zone_factor=site["seismic_zone_factor"],
    )
    real = design_intze_tank(inputs)
    return {
        "real_cost": round(total_relative_cost(
            real.concrete_volume_m3, candidate["concrete_grade_mpa"],
            candidate["num_columns"]), 2),
        "real_extra_axial_kn": real.staging_extra_axial_per_column_kn,
        "real_column_dia_mm": real.staging_column_diameter_mm,
    }


if __name__ == "__main__":
    SITE = {
        "capacity_liters": 500_000, "staging_height_m": 16.0,
        "soil_bearing_kpa": 150.0, "wind_speed_m_s": 44.0,
        "seismic_zone_factor": 0.16,
    }
    print(f"=== Optimizing: {SITE} ===\n")
    candidates = run_optimization(SITE)
    print(f"Found {len(candidates)} Pareto-optimal design candidates:\n")
    for c in candidates:
        real = verify_against_real_engine(c, SITE)
        print(f"  {c['num_columns']} columns, M{c['concrete_grade_mpa']}")
        print(f"    surrogate: cost={c['surrogate_cost']}, extra_axial={c['surrogate_extra_axial_kn']} kN")
        print(f"    real     : cost={real['real_cost']}, extra_axial={real['real_extra_axial_kn']} kN, "
              f"column_dia={real['real_column_dia_mm']} mm")
        print()
