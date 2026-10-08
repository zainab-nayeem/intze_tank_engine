"""
3D parametric visualization of the Intze tank.

Runs the optimizer for a site, takes every Pareto-optimal design it
finds, re-computes each with the real engine, and draws them as an
interactive 3D model in one HTML file (tank_3d.html). A dropdown in
the file switches between the candidate designs; rotate with the
mouse, zoom with the scroll wheel.

Everything drawn comes straight from the engine's outputs (diameter,
wall height, dome rises, cone geometry, staging height, number of
columns, column diameter, bracing tiers, water level) -- nothing is
hand-drawn. Elements the engine does not size are marked "schematic"
in the figure.
"""

import math
import numpy as np
import plotly.graph_objects as go

from models import DesignInputs
from intze_design_engine import design_intze_tank
from cost_model import total_relative_cost

COL_CONCRETE = "#9aa0a6"
COL_WATER = "#3b82f6"
COL_RING = "#5f6368"
COL_GROUND = "#c8b89a"

N_THETA = 60


def _surface(X, Y, Z, color, opacity=1.0, name="", hover=None):
    return go.Surface(
        x=X, y=Y, z=Z, showscale=False, opacity=opacity, name=name,
        colorscale=[[0, color], [1, color]], hoverinfo="text" if hover else "skip",
        text=hover, lighting=dict(ambient=0.6, diffuse=0.7, specular=0.1),
    )


def _revolve(radii, zs, color, opacity=1.0, name="", hover=None):
    theta = np.linspace(0, 2 * math.pi, N_THETA)
    r = np.array(radii)[:, None]
    X = r * np.cos(theta)[None, :]
    Y = r * np.sin(theta)[None, :]
    Z = np.array(zs)[:, None] * np.ones_like(theta)[None, :]
    return _surface(X, Y, Z, color, opacity, name, hover)


def _dome(base_radius, rise, z_base, upward, color, name, hover):
    Rs = (base_radius ** 2 + rise ** 2) / (2 * rise)
    phi_max = math.asin(min(1.0, base_radius / Rs))
    phis = np.linspace(0, phi_max, 20)
    radii = Rs * np.sin(phis)
    height = Rs * np.cos(phis) - (Rs - rise)
    zs = z_base + height if upward else z_base - height
    return _revolve(radii, zs, color, 1.0, name, hover)


def build_design_traces(inputs, out):
    traces = []
    D = out.internal_diameter_m
    R = D / 2
    h_s = inputs.staging_height_m
    n = inputs.num_columns
    col_r = out.staging_column_diameter_mm / 2000
    r_b = out.cone_bottom_diameter_m / 2

    cone_v = (R - r_b) * math.tan(math.radians(inputs.cone_angle_deg))
    z_cone_bot = h_s
    z0 = z_cone_bot + cone_v                    # cylinder bottom
    cyl_h = out.cylindrical_wall_height_m       # includes free board
    water_h = cyl_h - inputs.free_board_m
    z_top = z0 + cyl_h

    # --- staging columns ---
    theta = np.linspace(0, 2 * math.pi, 24)
    for k in range(n):
        a = 2 * math.pi * k / n
        cx, cy = R * math.cos(a), R * math.sin(a)
        X = np.array([[cx + col_r * math.cos(t) for t in theta]] * 2)
        Y = np.array([[cy + col_r * math.sin(t) for t in theta]] * 2)
        Z = np.array([[0.0] * len(theta), [h_s] * len(theta)])
        traces.append(_surface(X, Y, Z, COL_CONCRETE, 1.0, "column",
                               f"Staging column {k+1}<br>dia {out.staging_column_diameter_mm:.0f} mm"))

    # --- bracing rings at each tier (between columns) ---
    tiers = out.staging_num_bracing_tiers
    for t in range(1, tiers + 1):
        z = h_s * t / tiers
        xs = [R * math.cos(2 * math.pi * k / n) for k in range(n + 1)]
        ys = [R * math.sin(2 * math.pi * k / n) for k in range(n + 1)]
        traces.append(go.Scatter3d(x=xs, y=ys, z=[z] * (n + 1), mode="lines",
                                   line=dict(color=COL_RING, width=6),
                                   hoverinfo="text", text=f"Bracing ring, tier {t}",
                                   name="bracing"))

    # --- schematic radial beams: column tops -> cone bottom ring ---
    for k in range(n):
        a = 2 * math.pi * k / n
        traces.append(go.Scatter3d(
            x=[R * math.cos(a), r_b * math.cos(a)],
            y=[R * math.sin(a), r_b * math.sin(a)],
            z=[h_s, h_s], mode="lines", line=dict(color="#b0b4b9", width=4, dash="dot"),
            hoverinfo="text", text="Support beam (schematic)", name="support beam"))

    # --- foundation ---
    if out.foundation_type == "isolated_footings":
        side = out.foundation_size_m
        for k in range(n):
            a = 2 * math.pi * k / n
            cx, cy = R * math.cos(a), R * math.sin(a)
            X = np.array([[cx - side/2, cx + side/2, cx + side/2, cx - side/2, cx - side/2]] * 2)
            Y = np.array([[cy - side/2, cy - side/2, cy + side/2, cy + side/2, cy - side/2]] * 2)
            Z = np.array([[-0.5] * 5, [0.0] * 5])
            traces.append(_surface(X, Y, Z, COL_GROUND, 1.0, "footing",
                                   f"Isolated footing, side {side:.2f} m"))
    else:
        raft_r = max(out.foundation_size_m / 2, R + col_r + 0.8)
        traces.append(_revolve([0, raft_r], [0, 0], COL_GROUND, 1.0, "raft",
                               f"Raft foundation (schematic extent). Required equivalent "
                               f"diameter from bearing check: {out.foundation_size_m:.2f} m"))
        traces.append(_revolve([raft_r, raft_r], [-0.5, 0], COL_GROUND, 1.0, "raft edge", None))

    # --- bottom dome (bulges downward) ---
    traces.append(_dome(r_b, out.bottom_dome_rise_m, z_cone_bot, False, COL_CONCRETE,
                        "bottom dome", f"Bottom dome, thickness {out.bottom_dome_thickness_mm:.0f} mm"))
    # --- conical wall ---
    traces.append(_revolve([r_b, R], [z_cone_bot, z0], COL_CONCRETE, 1.0, "cone",
                           f"Conical wall, slant {out.cone_slant_height_m:.2f} m"))
    # --- cylindrical wall ---
    traces.append(_revolve([R, R], [z0, z_top], COL_CONCRETE, 0.55, "wall",
                           f"Cylindrical wall<br>thickness {out.cylindrical_wall_thickness_mm:.0f} mm"
                           f"<br>hoop steel {out.cylindrical_wall_hoop_steel_mm2_per_m:.0f} mm2/m"))
    # --- ring beam at cone/cylinder junction ---
    depth = out.ring_beam_depth_mm / 1000
    traces.append(_revolve([R + 0.12, R + 0.12], [z0 - depth, z0], COL_RING, 1.0, "ring beam",
                           f"Ring beam {out.ring_beam_width_mm:.0f} x {out.ring_beam_depth_mm:.0f} mm"))
    # --- top dome ---
    traces.append(_dome(R, out.top_dome_rise_m, z_top, True, COL_CONCRETE,
                        "top dome", f"Top dome, thickness {out.top_dome_thickness_mm:.0f} mm"))
    # --- water ---
    traces.append(_revolve([r_b, R, R], [z_cone_bot, z0, z0 + water_h], COL_WATER, 0.35,
                           "water", "Water"))
    traces.append(_revolve([0, R], [z0 + water_h, z0 + water_h], COL_WATER, 0.45, "water surface", "Water level"))
    return traces


FOOTNOTE = dict(
    text="Schematic: column pitch circle follows the engine's assumption (= tank diameter); "
         "dotted support beams and foundation extent are illustrative.",
    x=0.5, y=0.0, xref="paper", yref="paper", showarrow=False,
    font=dict(size=11, color="#555"), yanchor="bottom")


def make_figure(site, candidates):
    all_traces = []
    counts = []
    labels = []
    notes = []
    for c in candidates:
        inputs = DesignInputs(
            capacity_liters=site["capacity_liters"], staging_height_m=site["staging_height_m"],
            num_columns=c["num_columns"], soil_bearing_capacity_kpa=site["soil_bearing_kpa"],
            concrete_grade_mpa=float(c["concrete_grade_mpa"]),
            basic_wind_speed_m_s=site["wind_speed_m_s"], seismic_zone_factor=site["seismic_zone_factor"],
        )
        out = design_intze_tank(inputs)
        cost = total_relative_cost(out.concrete_volume_m3, c["concrete_grade_mpa"], c["num_columns"], out.estimated_steel_kg)
        tr = build_design_traces(inputs, out)
        all_traces.append(tr)
        counts.append(len(tr))
        labels.append(f"{c['num_columns']} columns, M{c['concrete_grade_mpa']}  |  cost {cost:.0f}  |  "
                      f"lateral load/column {out.staging_extra_axial_per_column_kn:.0f} kN")
        notes.append(
            f"<b>{c['num_columns']} columns, M{c['concrete_grade_mpa']}</b><br>"
            f"Capacity {site['capacity_liters']/1000:.0f} kL · staging {site['staging_height_m']:.0f} m<br>"
            f"Tank dia {out.internal_diameter_m:.2f} m · column dia {out.staging_column_diameter_mm:.0f} mm<br>"
            f"Concrete {out.concrete_volume_m3:.1f} m3 · relative cost {cost:.0f}<br>"
            f"Governing lateral case: {out.governing_lateral_case}<br>"
            f"Extra load per column: {out.staging_extra_axial_per_column_kn:.0f} kN<br>"
            f"Foundation: {out.foundation_type}"
        )

    fig = go.Figure()
    for tr in all_traces:
        for t in tr:
            fig.add_trace(t)
    total = sum(counts)

    buttons = []
    start = 0
    for i, cnt in enumerate(counts):
        vis = [False] * total
        for j in range(start, start + cnt):
            vis[j] = True
        buttons.append(dict(
            label=labels[i], method="update",
            args=[{"visible": vis},
                  {"annotations": [dict(text=notes[i], x=0.01, y=0.99, xref="paper", yref="paper",
                                        showarrow=False, align="left", xanchor="left", yanchor="top",
                                        bgcolor="rgba(255,255,255,0.85)", bordercolor="#999",
                                        borderpad=8, font=dict(size=13, color="#222")), FOOTNOTE]}]))
        start += cnt

    for j in range(total):
        fig.data[j].visible = j < counts[0]

    fig.update_layout(
        title=dict(text="Intze tank - Pareto-optimal designs (select a design in the dropdown)",
                   font=dict(size=16, color="#222")),
        paper_bgcolor="white", showlegend=False,
        scene=dict(aspectmode="data", xaxis=dict(visible=False), yaxis=dict(visible=False),
                   zaxis=dict(title="height (m)", backgroundcolor="white", gridcolor="#ddd"),
                   bgcolor="white", camera=dict(eye=dict(x=1.6, y=1.6, z=0.7))),
        updatemenus=[dict(buttons=buttons, direction="down", x=0.99, xanchor="right",
                          y=1.0, yanchor="top", bgcolor="white", font=dict(color="#222"))],
        annotations=[dict(text=notes[0], x=0.01, y=0.99, xref="paper", yref="paper", showarrow=False,
                          align="left", xanchor="left", yanchor="top", bgcolor="rgba(255,255,255,0.85)",
                          bordercolor="#999", borderpad=8, font=dict(size=13, color="#222")),
                     FOOTNOTE],
        margin=dict(l=0, r=0, t=50, b=30), height=720,
    )
    return fig


if __name__ == "__main__":
    import webbrowser, os
    from optimizer import run_optimization

    SITE = {"capacity_liters": 500_000, "staging_height_m": 16.0, "soil_bearing_kpa": 150.0,
            "wind_speed_m_s": 44.0, "seismic_zone_factor": 0.16}
    candidates = run_optimization(SITE)
    print(f"Drawing {len(candidates)} Pareto-optimal designs...")
    fig = make_figure(SITE, candidates)
    fig.write_html("tank_3d.html", include_plotlyjs=True)
    path = os.path.abspath("tank_3d.html")
    print(f"Saved: {path}")
    webbrowser.open("file:///" + path.replace("\\", "/"))
