"""
Data models for the Intze Tank Design Engine.

INPUT SOURCE TRACKING:
Every user-facing parameter can arrive two ways:
  - "manual"     -- typed in directly by the engineer, treated as verified
  - "auto_map"   -- derived from a map/GPS interaction or a bundled dataset
                    (population grid, soil-type map, drawn polygon area)
Auto-derived values -- especially soil bearing capacity -- are NEVER
treated as equal-confidence to a manual entry. They get flagged in
DesignOutputs.warnings until the engineer confirms/overrides them.
This mirrors the existing assumptions/warnings transparency pattern
in the design engine.
"""

from dataclasses import dataclass, field


@dataclass
class InputField:
    """A single parameter value plus where it came from."""
    value: float
    source: str = "manual"   # "manual" | "auto_map"
    confidence_note: str = ""  # populated automatically for auto_map sources


@dataclass
class SiteLocation:
    """Optional location context, captured via map click / GPS / drawn polygon."""
    latitude: float = None
    longitude: float = None
    polygon_coords: list = field(default_factory=list)  # [(lat, lon), ...] if drawn
    area_km2: float = None          # computed from polygon if drawn
    population: float = None
    population_source: str = "manual"   # "manual" | "auto_map"


@dataclass
class DesignInputs:
    """Parameters the engineer/user provides."""
    capacity_liters: float          # required water storage capacity
    staging_height_m: float         # height from ground to bottom of tank
    num_columns: int = 8            # staging columns (6, 8, 10, 12 typical)
    soil_bearing_capacity_kpa: float = 150.0   # from soil report
    soil_source: str = "manual"     # "manual" | "auto_map" -- see note below
    free_board_m: float = 0.30      # air gap above water level
    top_dome_rise_ratio: float = 0.15   # rise / diameter, typical 1/5 to 1/6
    bottom_dome_rise_ratio: float = 0.20
    cone_angle_deg: float = 45.0    # angle of conical bottom with horizontal
    concrete_grade_mpa: float = 25.0    # M25 typical for water-retaining
    steel_grade_mpa: float = 415.0      # Fe415 typical
    permissible_bearing_kpa: float = None  # if None, taken = soil_bearing_capacity_kpa
    location: SiteLocation = None
    basic_wind_speed_m_s: float = 44.0   # IS 875 basic wind speed, site-dependent
    seismic_zone_factor: float = 0.16    # IS 1893 zone factor (Zone III default)


@dataclass
class DesignOutputs:
    """Computed geometry, thicknesses, and material estimates."""
    internal_diameter_m: float = None
    cylindrical_wall_height_m: float = None
    cylindrical_wall_thickness_mm: float = None
    cylindrical_wall_hoop_steel_mm2_per_m: float = None
    top_dome_radius_m: float = None
    top_dome_rise_m: float = None
    top_dome_thickness_mm: float = None
    bottom_dome_radius_m: float = None
    bottom_dome_rise_m: float = None
    bottom_dome_thickness_mm: float = None
    cone_slant_height_m: float = None
    cone_bottom_diameter_m: float = None
    ring_beam_hoop_tension_kn: float = None
    ring_beam_width_mm: float = None
    ring_beam_depth_mm: float = None
    staging_column_diameter_mm: float = None
    staging_num_bracing_tiers: int = None
    foundation_type: str = None
    foundation_size_m: float = None
    total_dead_load_kn: float = None
    concrete_volume_m3: float = None
    estimated_steel_kg: float = None
    warnings: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
