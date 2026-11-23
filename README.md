# Intze Tank Platform

AI-driven parametric design and multi-tank optimisation of Intze elevated water tanks, built to work **with** the civil
engineer from the first sizing to the as-built check. B.Tech major project, Zainab Nayeem, SMIT (AI&DS).
Credits, libraries and originality statement: see [THIRD_PARTY.md](THIRD_PARTY.md).

## What it does
| Part | File | What it gives |
|---|---|---|
| Design engine | `src/intze_design_engine.py` | Geometry, wall, dome and cone members, staging columns, foundation, concrete and steel quantities for one tank |
| Validation | `src/validate_engine.py` | 68 checks: independent load-path check, trends, comparison with published optimum H/D |
| ML surrogate | `src/generate_dataset.py`, `src/train_surrogate.py` | Fast predictions trained on 20,000 designs made by the engine itself (synthetic data) |
| Optimiser | `src/optimizer.py` | NSGA-II over columns and grade; candidates are re-computed on the real engine |
| Adaptive re-optimiser | `src/adaptive_reoptimizer.py` | Re-plans when stock, budget or site limits change |
| Construction tracker | `src/construction_tracker.py` | Stage locks, stock, minimal-change options, as-built check |
| Regional planner | `src/regional_planner.py` | Demand forecast, storage, best grouping of zones into tanks |
| Web app | `src/app.py` | Roles, project pages, design options, 3D view, printable summary, regional planner |

## Run it (Windows CMD, from the `src` folder)
```
pip install numpy pandas scikit-learn joblib pymoo plotly flask
python generate_dataset.py
python train_surrogate.py
python validate_engine.py
python app.py
```
Open http://127.0.0.1:5000 . Demo accounts (change before any real use):

| User | Password | Role | Can |
|---|---|---|---|
| manager | Manager@123 | Manager | everything, including accepting a design |
| site | Site@123 | Site engineer | log progress, stock and site data |
| client | Client@123 | Client | view only |

## Pages
- **Overview / Site desk / Advice**: project state, stage progress, stock, and the tracker's advice when something changes.
- **Design**: enter capacity and site values, get the Pareto options (cost against load on columns), each with a **Details and 3D** page.
- **Design details**: full engine output, warnings, assumptions, a 3D model and a print / save-as-PDF button.
- **Regional**: paste a zone list (CSV), get the cheapest grouping of zones into tanks, a map and a sensitivity table.

## Test
```
python test_app.py
```
Checks login, role limits, CSRF, input validation, and that no page links to an outside website.

## Honest limits
Relative costs only; wall steel uses 130 MPa (walls up to 225 mm) or 150 MPa (thicker), taken from textbook summaries of IS 3370 and still to be checked against the printed table; wind and seismic by simplified static methods; ring beam, cone, raft and bracing use placeholder rules;
no live load; not yet compared with a real project or the original VB5 tool. Decision-support only: a licensed structural
engineer must check and sign off any design.
