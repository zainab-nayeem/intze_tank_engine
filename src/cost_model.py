"""
Relative cost model.

Concrete grade isn't cost-neutral -- higher grades (more cement, more
quality control) cost more per m3 even though they need less total
volume. Without this, "always use M30" looks free in the optimizer,
which isn't true in practice. Factors below are illustrative relative
multipliers (M20 = baseline 1.0), not sourced from a live price index
-- flagged as such; a real deployment would pull current local rates.

PER-COLUMN OVERHEAD (added once wind/seismic was wired in):
Under the current working-stress, axial-only column design, total
staging concrete volume is nearly INVARIANT to num_columns -- splitting
the same total load across more, thinner columns uses almost exactly
the same concrete, verified directly by brute-force comparison across
the (num_columns x concrete_grade) grid. This is a genuine, confirmed
property of this simplified design method (it only sizes columns for
direct compressive stress, with a slenderness check, not a bending/
foundation-layout model) -- not a bug. On its own this means a pure
concrete-volume objective will always prefer the FEWEST columns,
hiding the real benefit of more columns: each column carries a smaller
share of the wind/seismic overturning moment (see wind_seismic.py),
i.e. a genuine structural safety-margin improvement.

In real construction, more columns also mean more footings/excavation
pits, more formwork faces, and more column-to-bracing-beam junctions
to execute correctly on site -- a real incremental cost that doesn't
show up in concrete volume. We model that here as a flat relative
overhead per column. The number below is illustrative (not sourced
from a live rate card), flagged as such; it exists so the optimizer's
cost objective reflects this real-world cost driver instead of only
material volume, so that choosing more columns for better lateral-load
safety shows up as a genuine cost trade-off rather than looking free.
"""

GRADE_COST_FACTOR = {
    20: 1.00,
    25: 1.12,
    30: 1.28,
    35: 1.45,
    40: 1.65,
}

# Relative overhead per staging column (excavation, formwork, bracing
# junctions), in the same relative-cost units as concrete volume x
# grade factor. Illustrative placeholder value -- flag in assumptions
# wherever this is used.
PER_COLUMN_OVERHEAD_RELATIVE = 3.0


# Reinforcement steel price in the same relative units (1.0 = one m3 of M20
# concrete). Illustrative: roughly Rs 65-75 per kg of steel against roughly
# Rs 6,500-7,500 per m3 of M20 concrete, i.e. 1 kg steel ~ 0.01 m3 concrete.
# Replace with current local rates before real use.
STEEL_COST_PER_KG_RELATIVE = 0.01


def total_relative_cost(concrete_volume_m3: float, concrete_grade_mpa: float,
                         num_columns: int = None, steel_kg: float = None) -> float:
    grade_key = int(concrete_grade_mpa)
    factor = GRADE_COST_FACTOR.get(grade_key, 1.0)
    cost = concrete_volume_m3 * factor
    if steel_kg is not None:
        cost += steel_kg * STEEL_COST_PER_KG_RELATIVE
    if num_columns is not None:
        cost += num_columns * PER_COLUMN_OVERHEAD_RELATIVE
    return cost
