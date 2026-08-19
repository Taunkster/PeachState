"""FortyGuard SDK — heatmap request/response models.

Empirically validated response shapes (probe 5, 2026-08-18):

    analytic_type="tcm":
        map_data.features[i].properties = {
            tile_id, average_temperature, min_temperature, max_temperature}
        stats_data.temperature_stats = {min, max, mean, standard_deviation}

    analytic_type in ("exceedance", "persistence", "time_of_measure"):
        map_data.features[i].properties = {tile_id, value}   # value in hours
        stats_data = {analytic_type, units: "hour", n_cells, min, max, mean}

IMPORTANT (F3): there is NO multi-analytic param. tcm + exceedance +
persistence must be issued as 3 concurrent calls.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import DateTimeFilter, DateTimeWindow, PolygonAOI

AnalyticType = Literal["tcm", "time_of_measure", "exceedance", "persistence"]
ThresholdDirection = Literal["above", "below"]

# Georgia crop air-temp thresholds (°F) used as exceedance/persistence
# thresholds. GA crops are canopy/2m-air based (Employee 1: valid in GA's
# humid climate). NOTE: the API threshold expects °C.
# Synced with data/crop_thresholds.json (canonical demo source).
GA_CROP_THRESHOLDS_F = {
    "peach": 95.0,
    "pecan": 95.0,
    "blueberry": 90.0,
    "onion": 85.0,
    "watermelon": 95.0,
}


def ga_threshold_c(crop: str, fahrenheit: float | None = None) -> float:
    """Convert GA crop threshold to °C for the API's threshold field."""
    f = fahrenheit or GA_CROP_THRESHOLDS_F.get(crop, 95.0)
    return round((f - 32.0) * 5.0 / 9.0, 2)


class HeatmapRequest(BaseModel):
    polygon_aoi: PolygonAOI | dict[str, Any]  # GeoJSON FeatureCollection
    date_time: DateTimeWindow
    granularity: int = Field(100, ge=60, le=100)
    analytic_type: AnalyticType = "tcm"
    threshold: float | None = None       # used by exceedance/persistence (default 30°C)
    direction: ThresholdDirection | None = None  # above (default) / below

    def to_payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {
            "polygon_aoi": _fc(self.polygon_aoi),
            "date_time": self.date_time.to_payload(),
            "granularity": self.granularity,
            "analytic_type": self.analytic_type,
        }
        if self.threshold is not None:
            p["threshold"] = self.threshold
        if self.direction is not None:
            p["direction"] = self.direction
        return p


def _fc(aoi: PolygonAOI | dict[str, Any]) -> dict[str, Any]:
    """Normalize polygon_aoi (PolygonAOI model or raw dict) to a dict."""
    return aoi.to_dict() if isinstance(aoi, PolygonAOI) else aoi


class Tile(BaseModel):
    tile_id: int = 0
    average_temperature: float | None = None  # tcm
    min_temperature: float | None = None      # tcm
    max_temperature: float | None = None      # tcm
    value: float | None = None                # exceedance/persistence/time_of_measure
    geometry: dict[str, Any] = {}             # GeoJSON polygon

    @classmethod
    def from_feature(cls, f: dict[str, Any]) -> "Tile":
        props = f.get("properties", {}) or {}
        return cls(
            tile_id=int(props.get("tile_id", 0)),
            average_temperature=props.get("average_temperature"),
            min_temperature=props.get("min_temperature"),
            max_temperature=props.get("max_temperature"),
            value=props.get("value"),
            geometry=f.get("geometry", {}),
        )


class TemperatureStats(BaseModel):
    """tcm (temperature) analytic statistics.

    Mirrors the API's ``stats_data.temperature_stats`` object plus the
    optional overall temperature distribution histogram.
    """

    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    standard_deviation: float | None = None
    overall_temperature_distribution: Any = None  # list/dict histogram if present

    def __getitem__(self, key: str) -> Any:
        """Dict-style access (``stats["mean"]``) for backward compatibility."""
        return getattr(self, key)


class AnalyticStats(BaseModel):
    """exceedance / persistence / time_of_measure analytic statistics.

    Mirrors the API's flat ``stats_data`` for non-tcm analytics:
    {analytic_type, units, n_cells, min, max, mean}.
    """

    activity_id: str | None = None
    analytic_type: str | None = None
    units: str | None = None          # "hour" for exceedance/persistence
    n_cells: int = 0
    min: float | None = None
    max: float | None = None
    mean: float | None = None


class HeatmapStats(BaseModel):
    analytic_type: str | None = None
    units: str | None = None                 # "hour" or "°C"
    n_cells: int = 0
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    temperature_stats: TemperatureStats | None = None  # tcm analytics (typed)
    analytic_stats: AnalyticStats | None = None        # non-tcm analytics (typed)


class HeatmapResult(BaseModel):
    map_data: dict[str, Any] = {}            # raw GeoJSON FeatureCollection
    stats_data: HeatmapStats = HeatmapStats()
    tiles: list[Tile] = []
    n_cells: int = 0

    @classmethod
    def from_result(cls, result: dict[str, Any]) -> "HeatmapResult":
        md = result.get("map_data", {}) or {}
        sd = result.get("stats_data", {}) or {}
        features = md.get("features", []) if isinstance(md, dict) else []
        n_cells = int((sd.get("n_cells") if isinstance(sd, dict) else 0) or len(features))
        stats = cls._parse_stats(sd, result.get("activity_id"))
        return cls(
            map_data=md,
            stats_data=stats,
            tiles=[Tile.from_feature(f) for f in features],
            n_cells=n_cells,
        )

    @staticmethod
    def _parse_stats(
        sd: Any, activity_id: str | None
    ) -> "HeatmapStats":
        if not isinstance(sd, dict):
            return HeatmapStats()
        temp_stats = None
        analytic_stats = None
        ts = sd.get("temperature_stats")
        if isinstance(ts, dict):
            temp_stats = TemperatureStats(**ts)
        if sd.get("analytic_type"):
            analytic_stats = AnalyticStats(
                activity_id=activity_id,
                analytic_type=sd.get("analytic_type"),
                units=sd.get("units"),
                n_cells=sd.get("n_cells") or 0,
                min=sd.get("min"),
                max=sd.get("max"),
                mean=sd.get("mean"),
            )
        return HeatmapStats(
            analytic_type=sd.get("analytic_type"),
            units=sd.get("units"),
            n_cells=sd.get("n_cells") or 0,
            min=sd.get("min"),
            max=sd.get("max"),
            mean=sd.get("mean"),
            temperature_stats=temp_stats,
            analytic_stats=analytic_stats,
        )


def estimate_aoe_area_sqmi(fc: dict[str, Any]) -> float:
    """True geodesic area in mi² of a FeatureCollection, for the plan guard.

    Computes the sum of the polygon areas in a local equal-area projection
    (not a bounding-box envelope). This matches what the API actually bills,
    so thin diagonal corridor tiles (whose bbox would overestimate by 2-3x)
    are sized correctly against the 10/50 mi² plan caps.
    """
    polys: list[Any] = []
    for feat in fc.get("features", []):
        geom = feat.get("geometry", {})
        _collect_polys(geom, polys)
    if not polys:
        return 0.0
    total_sqkm = sum(_polygon_area_sqkm(g) for g in polys)
    return total_sqkm * 0.386102  # km² -> mi²


def _collect_polys(geom: dict[str, Any], out: list[Any]) -> None:
    t = geom.get("type")
    if t == "Polygon":
        out.append(geom)
    elif t == "MultiPolygon":
        for poly in geom.get("coordinates", []):
            out.append({"type": "Polygon", "coordinates": poly})
    elif t == "GeometryCollection":
        for g in geom.get("geometries", []):
            _collect_polys(g, out)


def _polygon_area_sqkm(geom: dict[str, Any]) -> float:
    from shapely.geometry import shape
    from shapely.ops import transform

    import pyproj

    try:
        poly = shape(geom)
    except Exception:
        return 0.0
    if poly.is_empty or poly.area == 0.0:
        return 0.0
    try:
        c = poly.representative_point()
    except Exception:
        return 0.0
    aea = pyproj.Proj(
        proj="aea", lat_1=c.y - 1.0, lat_2=c.y + 1.0, lat_0=c.y, lon_0=c.x,
        ellps="WGS84",
    )
    wgs = pyproj.Proj(proj="latlong", datum="WGS84")
    t = pyproj.Transformer.from_proj(wgs, aea, always_xy=True).transform
    try:
        return transform(t, poly).area / 1_000_000.0
    except Exception:
        return 0.0


def estimate_area_mi2(
    polygon: PolygonAOI | dict[str, Any],
) -> float:
    """Public area helper (mi²) for a heatmap AOI polygon (plan guard).

    Accepts a raw GeoJSON FeatureCollection dict or a typed
    :class:`PolygonAOI` model.
    """
    return estimate_aoe_area_sqmi(_fc(polygon))


def _walk(geom: dict[str, Any], out: list[tuple[float, float]]) -> None:
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Point":
        out.append((c[0], c[1]))
    elif t == "Polygon":
        for ring in c:
            for pt in ring:
                out.append((pt[0], pt[1]))
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                for pt in ring:
                    out.append((pt[0], pt[1]))
    elif t == "GeometryCollection":
        for g in c:
            _walk(g, out)