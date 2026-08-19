"""FortyGuard SDK — env_params request/response models.

Empirically validated (probe 1, 2026-08-18):
    response.metadata: {timezone, timezone_offset_hours, time_range, timestamps}
    response.locations[0]: {lat, lon, elevation, temperature,
                            parameters: {name: [v,...]}, solar_irradiance}
    Missing values: null (new) or legacy -999. MUST NOT be treated as 0.

Georgia Pipeline A needs: heat_index, WBGT, humidity, GHI (solar irradiance).
Basic caps `analysis` at 3/request -> 2 requests (heat_index+WBGT+humidity,
then solar_irradiance). Premium: 1 request with all.

Day 2 additions (PeachState CoolChain):
    - `temperature` is REQUIRED by the API (422 without it) but the *model*
      allows None so the client method can chain it from a heatmap tile temp
      or a last-known reading before POSTing.
    - The API reports **Celsius**; for the Georgia demo we expose °F variants
      (``temperature_f``, ``heat_index_f``, ...) alongside the raw °C series.
    - AQI convenience accessors: ``aqi`` -> air_quality:idx, ``pm2p5``,
      ``pm10``, ``no2``, ``co``, ``o3``, ``so2``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import DateTimeWindow

# Full documented parameter names.
ENV_PARAM_NAMES: tuple[str, ...] = (
    # thermal & atmospheric
    "heat_index_celsius",
    "apparent_temperature_celsius",
    "wet_bulb_temperature_celsius",
    "relative_humidity_percent",
    "precipitation_mm",
    "cloud_cover_octas",
    "elevation",
    # air quality (US AQI) & gases
    "air_quality:idx",
    "air_quality_pm2p5:idx",
    "air_quality_pm10:idx",
    "air_quality_no2:idx",
    "aqi_us_co",
    "air_quality_o3:idx",
    "air_quality_so2:idx",
    "methane_ppb",
    "co2_ppm",
    # solar
    "solar_irradiance",  # GHI / DNI / DHI grouping
)

# Temperature-style params (reported °C) that the GA demo displays in °F.
# Maps "short" name -> API parameter name.
TEMP_PARAMS_C: dict[str, str] = {
    "temperature": "temperature",          # scalar on the location object
    "heat_index": "heat_index_celsius",
    "apparent_temperature": "apparent_temperature_celsius",
    "wet_bulb": "wet_bulb_temperature_celsius",
}

# AQI short name -> API parameter name.
AQI_PARAMS: dict[str, str] = {
    "idx": "air_quality:idx",
    "pm2p5": "air_quality_pm2p5:idx",
    "pm10": "air_quality_pm10:idx",
    "no2": "air_quality_no2:idx",
    "co": "aqi_us_co",
    "o3": "air_quality_o3:idx",
    "so2": "air_quality_so2:idx",
}

# PeachState CoolChain Pipeline A required params.
GA_PIPELINE_A_PARAMS = (
    "heat_index_celsius",
    "wet_bulb_temperature_celsius",
    "relative_humidity_percent",
    "solar_irradiance",  # GHI
)

MISSING_SENTINELS = (None, -999)


def c_to_f(c: float | None) -> float | None:
    """Celsius -> Fahrenheit (None-safe)."""
    if c is None:
        return None
    return round(c * 9.0 / 5.0 + 32.0, 2)


def f_to_c(f: float | None) -> float | None:
    """Fahrenheit -> Celsius (None-safe)."""
    if f is None:
        return None
    return round((f - 32.0) * 5.0 / 9.0, 2)


class EnvParamsRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    # REQUIRED by API (F9) — but optional here so the client method can
    # chain a value (heatmap tile temp / last-known) before POSTing.
    temperature: float | None = None
    date_time: DateTimeWindow
    analysis: list[str] | None = None     # None = all (Premium); Basic capped at 3

    def to_payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "date_time": self.date_time.to_payload(),
        }
        if self.temperature is not None:
            p["temperature"] = self.temperature
        if self.analysis:
            p["analysis"] = self.analysis
        return p


class SolarIrradiance(BaseModel):
    clear_sky: dict[str, float] = {}  # {"ghi":.., "dni":.., "dhi":..}
    description: str = ""

    def ghi(self) -> float | None:
        v = self.clear_sky.get("ghi")
        return None if v in MISSING_SENTINELS else v

    def dni(self) -> float | None:
        v = self.clear_sky.get("dni")
        return None if v in MISSING_SENTINELS else v

    def dhi(self) -> float | None:
        v = self.clear_sky.get("dhi")
        return None if v in MISSING_SENTINELS else v


class LocationParams(BaseModel):
    """Single point-sampled env_params location (all params, °C + °F)."""

    lat: float
    lon: float
    elevation: float | None = None
    temperature: float | None = None          # °C (as returned by the API)
    parameters: dict[str, list[float | None]] = {}
    solar_irradiance: SolarIrradiance | None = None

    # --- raw series access -------------------------------------------------
    def series(self, name: str) -> list[float | None]:
        return self.parameters.get(name, [])

    def latest(self, name: str) -> float | None:
        s = self.series(name)
        return s[-1] if s else None

    # --- °C -> °F conveniences (Georgia demo uses °F) ----------------------
    @property
    def temperature_f(self) -> float | None:
        return c_to_f(self.temperature)

    @property
    def heat_index_c(self) -> float | None:
        return self.latest("heat_index_celsius")

    @property
    def heat_index_f(self) -> float | None:
        return c_to_f(self.heat_index_c)

    @property
    def apparent_temperature_f(self) -> float | None:
        return c_to_f(self.latest("apparent_temperature_celsius"))

    @property
    def wet_bulb_c(self) -> float | None:
        return self.latest("wet_bulb_temperature_celsius")

    @property
    def wet_bulb_f(self) -> float | None:
        return c_to_f(self.wet_bulb_c)

    @property
    def relative_humidity_percent(self) -> float | None:
        return self.latest("relative_humidity_percent")

    @property
    def precipitation_mm(self) -> float | None:
        return self.latest("precipitation_mm")

    @property
    def cloud_cover_octas(self) -> float | None:
        return self.latest("cloud_cover_octas")

    @property
    def methane_ppb(self) -> float | None:
        return self.latest("methane_ppb")

    @property
    def co2_ppm(self) -> float | None:
        return self.latest("co2_ppm")

    # --- AQI (short-name accessors) ---------------------------------------
    def aqi(self, short: str) -> float | None:
        name = AQI_PARAMS.get(short)
        return self.latest(name) if name else None

    @property
    def aqi_idx(self) -> float | None:
        return self.aqi("idx")

    @property
    def pm2p5(self) -> float | None:
        return self.aqi("pm2p5")

    @property
    def pm10(self) -> float | None:
        return self.aqi("pm10")

    @property
    def no2(self) -> float | None:
        return self.aqi("no2")

    @property
    def co(self) -> float | None:
        return self.aqi("co")

    @property
    def o3(self) -> float | None:
        return self.aqi("o3")

    @property
    def so2(self) -> float | None:
        return self.aqi("so2")

    # --- aggregates ---------------------------------------------------------
    def fahrenheit(self) -> dict[str, Any]:
        """Return a demo-friendly °F snapshot of this location."""
        return {
            "lat": self.lat,
            "lon": self.lon,
            "elevation": self.elevation,
            "temperature_c": self.temperature,
            "temperature_f": self.temperature_f,
            "heat_index_c": self.heat_index_c,
            "heat_index_f": self.heat_index_f,
            "apparent_temperature_f": self.apparent_temperature_f,
            "wet_bulb_f": self.wet_bulb_f,
            "relative_humidity_percent": self.relative_humidity_percent,
            "precipitation_mm": self.precipitation_mm,
            "cloud_cover_octas": self.cloud_cover_octas,
            "aqi": {"idx": self.aqi_idx, "pm2p5": self.pm2p5, "pm10": self.pm10,
                    "no2": self.no2, "co": self.co, "o3": self.o3,
                    "so2": self.so2},
            "methane_ppb": self.methane_ppb,
            "co2_ppm": self.co2_ppm,
            "solar_irradiance": (
                self.solar_irradiance.model_dump() if self.solar_irradiance else None
            ),
        }


class EnvMetadata(BaseModel):
    timezone: str | None = None
    timezone_offset_hours: int | None = None
    time_range: dict[str, Any] = {}
    timestamps: list[str] = []


class EnvParamsResult(BaseModel):
    metadata: EnvMetadata = EnvMetadata()
    locations: list[LocationParams] = []

    def fahrenheit(self) -> list[dict[str, Any]]:
        """All locations as °F demo snapshots."""
        return [loc.fahrenheit() for loc in self.locations]

    @classmethod
    def from_result(cls, result: dict[str, Any]) -> "EnvParamsResult":
        meta = result.get("metadata", {}) or {}
        locs: list[LocationParams] = []
        for loc in result.get("locations", []) or []:
            si = loc.get("solar_irradiance")
            locs.append(
                LocationParams(
                    lat=float(loc.get("lat", 0.0)),
                    lon=float(loc.get("lon", 0.0)),
                    elevation=_num(loc.get("elevation")),
                    temperature=_num(loc.get("temperature")),
                    parameters={k: v for k, v in (loc.get("parameters") or {}).items()},
                    solar_irradiance=(
                        SolarIrradiance(
                            clear_sky=si.get("clear_sky", {}),
                            description=si.get("description", ""),
                        )
                        if si
                        else None
                    ),
                )
            )
        return cls(
            metadata=EnvMetadata(
                timezone=meta.get("timezone"),
                timezone_offset_hours=meta.get("timezone_offset_hours"),
                time_range=meta.get("time_range", {}),
                timestamps=meta.get("timestamps", []),
            ),
            locations=locs,
        )


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f in MISSING_SENTINELS else f
