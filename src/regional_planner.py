"""
Regional planner -- from a service area to a set of designed Intze tanks.

Input: zones (manual, GPS point, drawn polygon, or an uploaded CSV).
For each zone: population (typed, or area x density, or polygon area x
density), growth rate, litres per head per day, and site data (soil
bearing capacity, wind speed, seismic zone factor).

Steps
  1. Forecast each zone's population to the design year and compute its
     daily demand and the storage it needs.
  2. Try every way of grouping zones so that each group is served by ONE
     tank (placed at the demand-weighted centre of the group). Groups that
     break the service-radius limit or the maximum tank size are rejected.
  3. Design each group's tank with the real engineering engine: the
     tank capacity is rounded up to a standard size, site data is the
     most demanding of the group (lowest soil bearing, highest wind and
     seismic), and the design is the compromise pick of the cost-versus-
     lateral-load trade-off (same rule as the optimizer).
  4. Total system cost = tank structures + a fixed overhead per tank site
     + a distribution proxy (daily demand x distance, summed over zones).
  5. Report the cheapest arrangement, the best arrangement for each number
     of tanks, and how sensitive the answer is to the per-tank overhead.

ASSUMPTIONS TO CONFIRM (all values below are editable, none are standards
unless stated):
  - Storage = 1/3 of daily demand (typical balancing storage guidance for
    intermittent supply); fire/emergency reserve NOT included.
  - Design period 30 years, geometric population growth.
  - Staging height from a placeholder hydraulic rule (12 m + 2 m per km to
    the farthest zone, 12-24 m) -- to be replaced by a real hydraulic
    analysis.
  - Per-tank site overhead and the distribution cost per (ML/day x km) are
    ILLUSTRATIVE relative-cost numbers, not rate-card values; the
    sensitivity table shows how much the answer depends on them.
  - Tank at the weighted centre of its group; straight-line distances, with
    a 0.5 km minimum (local distribution inside a zone).
  - Tank structure cost scales almost linearly with capacity in the engine,
    so merging zones saves little structure cost; consolidation is driven
    by the per-tank overhead -- read the sensitivity table, not one number.
"""

import csv
import math
import sys
import time

from models import DesignInputs
from intze_design_engine import design_intze_tank
from cost_model import total_relative_cost
from location_input import polygon_area_km2, gps_distance_km

# ---- editable assumptions ----
DESIGN_YEARS = 30
STORAGE_FRACTION = 1.0 / 3.0
STANDARD_CAPACITIES_KL = [50, 100, 150, 200, 250, 300, 400, 500, 600, 750, 1000, 1250, 1500, 2000]
MAX_SERVICE_RADIUS_KM = 2.5
SITE_OVERHEAD = 20.0          # relative cost units per tank site
DIST_COST_PER_ML_KM = 8.0     # relative cost units per (ML/day x km)
INTRA_ZONE_KM = 0.5           # minimum effective distribution distance (local mains inside a zone)
HD_RATIO = 0.9                # same baseline as the dataset / surrogate
MAX_ZONES_EXACT = 8

COLUMN_OPTIONS = [6, 8, 10, 12]
GRADE_OPTIONS = [20, 25, 30, 35, 40]


# ------------------------------------------------------------------ zones
def _f(v, default=None):
    v = (v or "").strip()
    return float(v) if v else default


def load_zones(path):
    zones = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            z = {"name": row["name"].strip(), "notes": []}
            lat, lon = _f(row.get("lat")), _f(row.get("lon"))
            area = _f(row.get("area_km2"))
            poly = (row.get("polygon") or "").strip()
            if poly:
                pts = [tuple(float(x) for x in p.split()) for p in poly.split(";")]
                area = polygon_area_km2(pts)
                lat = sum(p[0] for p in pts) / len(pts)
                lon = sum(p[1] for p in pts) / len(pts)
                z["notes"].append(f"area {area:.2f} km2 from drawn polygon")
            if lat is None or lon is None:
                raise ValueError(f"Zone '{z['name']}' needs lat/lon or a polygon.")
            pop = _f(row.get("population"))
            if pop is None:
                dens = _f(row.get("density_per_km2"))
                if area is None or dens is None:
                    raise ValueError(f"Zone '{z['name']}' needs a population, or area and density.")
                pop = area * dens
                z["notes"].append(f"population = {area:.2f} km2 x {dens:.0f}/km2")
            z.update({
                "lat": lat, "lon": lon, "population": pop,
                "soil": _f(row.get("soil_bearing_kpa"), 150.0),
                "wind": _f(row.get("wind_speed_m_s"), 44.0),
                "seismic": _f(row.get("seismic_zone_factor"), 0.16),
                "growth": _f(row.get("growth_rate_pct"), 1.5),
                "lpcd": _f(row.get("lpcd"), 135.0),
            })
            z["design_pop"] = pop * (1 + z["growth"] / 100) ** DESIGN_YEARS
            z["demand_kl_day"] = z["design_pop"] * z["lpcd"] / 1000
            z["storage_kl"] = z["demand_kl_day"] * STORAGE_FRACTION
            zones.append(z)
    return zones


# ------------------------------------------------------------------ one tank
_design_cache = {}


def design_tank(capacity_kl, staging_m, soil, wind, seismic):
    """Compromise-pick design over (columns x grade) with the real engine."""
    key = (capacity_kl, staging_m, round(soil), round(wind, 1), round(seismic, 3))
    if key in _design_cache:
        return _design_cache[key]
    cands = []
    for n in COLUMN_OPTIONS:
        for g in GRADE_OPTIONS:
            o = design_intze_tank(DesignInputs(
                capacity_liters=capacity_kl * 1000, staging_height_m=staging_m, num_columns=n,
                soil_bearing_capacity_kpa=soil, concrete_grade_mpa=float(g),
                basic_wind_speed_m_s=wind, seismic_zone_factor=seismic, hd_ratio=HD_RATIO))
            cands.append({"n": n, "grade": g,
                          "cost": total_relative_cost(o.concrete_volume_m3, g, n),
                          "axial": o.staging_extra_axial_per_column_kn,
                          "col_dia": o.staging_column_diameter_mm, "foundation": o.foundation_type,
                          "diameter": o.internal_diameter_m, "volume": o.concrete_volume_m3,
                          "case": o.governing_lateral_case,
                          "slender_warn": any("Slenderness" in w for w in o.warnings)})
    front = [a for a in cands if not any(
        b["cost"] <= a["cost"] and b["axial"] <= a["axial"] and (b["cost"] < a["cost"] or b["axial"] < a["axial"])
        for b in cands if b is not a)]
    cmin, cmax = min(a["cost"] for a in front), max(a["cost"] for a in front)
    amin, amax = min(a["axial"] for a in front), max(a["axial"] for a in front)
    def dist(a):
        return math.hypot((a["cost"] - cmin) / ((cmax - cmin) or 1), (a["axial"] - amin) / ((amax - amin) or 1))
    best = min(front, key=dist)
    _design_cache[key] = best
    return best


# ------------------------------------------------------------------ groups
def set_partitions(items):
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for part in set_partitions(rest):
        for i in range(len(part)):
            yield part[:i] + [[first] + part[i]] + part[i + 1:]
        yield [[first]] + part


_group_cache = {}


def evaluate_group(zones, idx):
    """Cost and design of one tank serving the zones in idx (tuple of indices)."""
    if idx in _group_cache:
        return _group_cache[idx]
    members = [zones[i] for i in idx]
    w = sum(z["demand_kl_day"] for z in members)
    lat = sum(z["lat"] * z["demand_kl_day"] for z in members) / w
    lon = sum(z["lon"] * z["demand_kl_day"] for z in members) / w
    dists = [gps_distance_km(lat, lon, z["lat"], z["lon"]) for z in members]
    need = sum(z["storage_kl"] for z in members)
    cap = next((c for c in STANDARD_CAPACITIES_KL if c >= need), None)
    result = {"zones": idx, "lat": lat, "lon": lon, "need_kl": need, "dists": dists}
    if cap is None:
        result["infeasible"] = f"needs {need:.0f} kL, above the largest standard tank ({STANDARD_CAPACITIES_KL[-1]} kL)"
    elif max(dists) > MAX_SERVICE_RADIUS_KM:
        result["infeasible"] = f"farthest zone is {max(dists):.1f} km away (limit {MAX_SERVICE_RADIUS_KM} km)"
    else:
        staging = int(min(24, max(12, round(12 + 2.0 * max(dists)))))
        d = design_tank(cap, staging, min(z["soil"] for z in members),
                        max(z["wind"] for z in members), max(z["seismic"] for z in members))
        result.update({"capacity_kl": cap, "staging_m": staging, "design": d,
                       "tank_cost": d["cost"],
                       "dist_cost": DIST_COST_PER_ML_KM * sum(z["demand_kl_day"] / 1000 * max(dd, INTRA_ZONE_KM)
                                                              for z, dd in zip(members, dists))})
    _group_cache[idx] = result
    return result


def plan(zones):
    if len(zones) > MAX_ZONES_EXACT:
        raise SystemExit(f"{len(zones)} zones is too many for exact search (max {MAX_ZONES_EXACT}). "
                         "Merge neighbouring zones and try again.")
    arrangements = []
    for part in set_partitions(list(range(len(zones)))):
        groups = [evaluate_group(zones, tuple(sorted(g))) for g in part]
        if any("infeasible" in g for g in groups):
            continue
        arrangements.append({"groups": groups, "k": len(groups),
                             "tank_cost": sum(g["tank_cost"] for g in groups),
                             "dist_cost": sum(g["dist_cost"] for g in groups)})
    return arrangements


def total(a, overhead=None):
    oh = SITE_OVERHEAD if overhead is None else overhead
    return a["tank_cost"] + a["dist_cost"] + oh * a["k"]


# ------------------------------------------------------------------ report
def report(zones, arrangements):
    print("=" * 74 + "\nREGIONAL PLAN\n" + "=" * 74)
    print(f"Design year: +{DESIGN_YEARS} years | storage = {STORAGE_FRACTION:.2f} x daily demand | "
          f"max service radius {MAX_SERVICE_RADIUS_KM} km")
    print(f"\n{'zone':<14}{'pop now':>9}{'pop design':>11}{'lpcd':>6}{'demand kL/d':>12}{'storage kL':>11}")
    for z in zones:
        print(f"{z['name']:<14}{z['population']:>9.0f}{z['design_pop']:>11.0f}{z['lpcd']:>6.0f}"
              f"{z['demand_kl_day']:>12.0f}{z['storage_kl']:>11.0f}")
        for n in z["notes"]:
            print(f"{'':<14}({n})")
    tot_storage = sum(z["storage_kl"] for z in zones)
    print(f"{'TOTAL':<14}{'':>9}{sum(z['design_pop'] for z in zones):>11.0f}{'':>6}"
          f"{sum(z['demand_kl_day'] for z in zones):>12.0f}{tot_storage:>11.0f}")

    if not arrangements:
        print("\nNO FEASIBLE ARRANGEMENT: no grouping satisfies the radius and tank-size limits. "
              "Increase the service radius, allow bigger tanks, or add zones.")
        return None

    best = min(arrangements, key=total)
    print(f"\n--- Cheapest arrangement: {best['k']} tank(s), total relative cost {total(best):.0f} ---")
    print(f"    (tank structures {best['tank_cost']:.0f} + site overhead {SITE_OVERHEAD * best['k']:.0f} "
          f"+ distribution proxy {best['dist_cost']:.0f})")
    for i, g in enumerate(sorted(best["groups"], key=lambda g: g["zones"]), 1):
        d = g["design"]
        names = ", ".join(zones[j]["name"] for j in g["zones"])
        print(f"\n  Tank {i}: {g['capacity_kl']} kL at {g['lat']:.4f}, {g['lon']:.4f}   serves: {names}")
        print(f"    needs {g['need_kl']:.0f} kL | staging {g['staging_m']} m | farthest zone "
              f"{max(g['dists']):.2f} km")
        print(f"    design: {d['n']} columns, M{d['grade']}, column dia {d['col_dia']:.0f} mm, "
              f"tank dia {d['diameter']:.1f} m, {d['foundation']}, lateral load {d['axial']:.0f} kN/column "
              f"({d['case']} governs), concrete {d['volume']:.0f} m3")
        if d["slender_warn"]:
            print("    WARNING: column slenderness limit exceeded -- add bracing tiers before use")

    print("\nBest arrangement for each number of tanks:")
    print(f"  {'tanks':>5} {'total':>8} {'structures':>11} {'overhead':>9} {'distribution':>13}")
    for k in sorted({a["k"] for a in arrangements}):
        a = min((x for x in arrangements if x["k"] == k), key=total)
        mark = "  <-- cheapest" if a is best else ""
        print(f"  {k:>5} {total(a):>8.0f} {a['tank_cost']:>11.0f} {SITE_OVERHEAD * k:>9.0f} {a['dist_cost']:>13.0f}{mark}")

    print("\nSensitivity: how many tanks are cheapest as the per-tank site overhead changes")
    print("  (overhead is an illustrative number -- this shows how much the answer depends on it)")
    prev = None
    for oh in [0, 10, 20, 40, 80, 160, 320]:
        b = min(arrangements, key=lambda a: total(a, oh))
        print(f"  overhead {oh:>4}: {b['k']} tank(s), total {total(b, oh):.0f}")
    return best


def save_outputs(zones, best):
    with open("regional_plan.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tank", "capacity_kl", "lat", "lon", "serves", "staging_m", "columns", "grade_M",
                    "column_dia_mm", "foundation", "lateral_kn_per_column", "concrete_m3", "relative_cost"])
        for i, g in enumerate(sorted(best["groups"], key=lambda g: g["zones"]), 1):
            d = g["design"]
            w.writerow([i, g["capacity_kl"], round(g["lat"], 5), round(g["lon"], 5),
                        "; ".join(zones[j]["name"] for j in g["zones"]), g["staging_m"], d["n"], d["grade"],
                        round(d["col_dia"]), d["foundation"], round(d["axial"]), round(d["volume"], 1),
                        round(d["cost"], 1)])
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        for g in best["groups"]:
            for j in g["zones"]:
                z = zones[j]
                fig.add_trace(go.Scattermap(lat=[g["lat"], z["lat"]], lon=[g["lon"], z["lon"]], mode="lines",
                                            line=dict(width=2, color="#888"), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scattermap(
            lat=[z["lat"] for z in zones], lon=[z["lon"] for z in zones], mode="markers+text",
            text=[z["name"].replace("DEMO ", "") for z in zones], textposition="bottom center",
            marker=dict(size=[max(10, min(40, z["demand_kl_day"] / 40)) for z in zones], color="#2b7de9", opacity=0.75),
            hovertext=[f"{z['name']}<br>design population {z['design_pop']:.0f}<br>storage {z['storage_kl']:.0f} kL"
                       for z in zones], hoverinfo="text", name="Zones"))
        fig.add_trace(go.Scattermap(
            lat=[g["lat"] for g in best["groups"]], lon=[g["lon"] for g in best["groups"]], mode="markers+text",
            text=[f"{g['capacity_kl']} kL" for g in best["groups"]], textposition="top center",
            marker=dict(size=22, color="#e23b3b", symbol="circle"),
            hovertext=[f"Tank {g['capacity_kl']} kL, staging {g['staging_m']} m, "
                       f"{g['design']['n']} columns M{g['design']['grade']}" for g in best["groups"]],
            hoverinfo="text", name="Tanks"))
        fig.update_layout(map=dict(style="open-street-map",
                                   center=dict(lat=sum(z["lat"] for z in zones) / len(zones),
                                               lon=sum(z["lon"] for z in zones) / len(zones)), zoom=12.5),
                          margin=dict(l=0, r=0, t=40, b=0), height=700,
                          title=f"Regional plan: {best['k']} tank(s) (zones blue, tanks red)")
        fig.write_html("regional_map.html", include_plotlyjs=True)
        save_plain_map(zones, best)
        print("\nSaved: regional_plan.csv, regional_map_plain.html, regional_map.html (street map, needs internet)")
    except Exception as e:                                   # map is a bonus; never block the plan
        print(f"\nSaved: regional_plan.csv  (map skipped: {e})")


def save_plain_map(zones, best):
    """Offline map (no tiles needed): zones, tanks and service links on lat/lon axes."""
    import plotly.graph_objects as go
    fig = go.Figure()
    for g in best["groups"]:
        for j in g["zones"]:
            z = zones[j]
            fig.add_trace(go.Scatter(x=[g["lon"], z["lon"]], y=[g["lat"], z["lat"]], mode="lines",
                                     line=dict(width=2, color="#9aa0a6"), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=[z["lon"] for z in zones], y=[z["lat"] for z in zones], mode="markers+text",
        text=[z["name"].replace("DEMO ", "") for z in zones], textposition="bottom center",
        marker=dict(size=[max(14, min(46, z["demand_kl_day"] / 35)) for z in zones], color="#2b7de9", opacity=0.75),
        hovertext=[f"{z['name']}<br>design population {z['design_pop']:.0f}<br>storage {z['storage_kl']:.0f} kL"
                   for z in zones], hoverinfo="text", name="Zones (size = demand)"))
    fig.add_trace(go.Scatter(
        x=[g["lon"] for g in best["groups"]], y=[g["lat"] for g in best["groups"]], mode="markers+text",
        text=[f"{g['capacity_kl']} kL" for g in best["groups"]], textposition="top center",
        marker=dict(size=20, color="#e23b3b", symbol="star"),
        hovertext=[f"Tank {g['capacity_kl']} kL, staging {g['staging_m']} m, {g['design']['n']} columns "
                   f"M{g['design']['grade']}" for g in best["groups"]], hoverinfo="text", name="Tanks"))
    mean_lat = sum(z["lat"] for z in zones) / len(zones)
    fig.update_layout(
        title=f"Regional plan: {best['k']} tank(s)  (blue = zones, red stars = tanks, grey = service links)",
        xaxis=dict(title="longitude", showgrid=True, gridcolor="#e6e6e6"),
        yaxis=dict(title="latitude", showgrid=True, gridcolor="#e6e6e6",
                   scaleanchor="x", scaleratio=1 / math.cos(math.radians(mean_lat))),
        plot_bgcolor="white", paper_bgcolor="white", height=700, margin=dict(l=60, r=20, t=60, b=50))
    fig.write_html("regional_map_plain.html", include_plotlyjs=True)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "zones_demo.csv"
    t0 = time.time()
    zones = load_zones(path)
    arrangements = plan(zones)
    best = report(zones, arrangements)
    if best:
        save_outputs(zones, best)
    print(f"\n(computed in {time.time() - t0:.0f} s)")
