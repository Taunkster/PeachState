#!/usr/bin/env python3
"""Build Georgia corridor road graphs (OSMnx) + static route nodes (Day 2).

Outputs (all under ``data/``):
    ga_roads_i16.gml       — I-16 corridor graph (Macon -> Savannah)
    ga_roads_i75.gml       — I-75 corridor graph (Macon -> Valdosta)
    ga_roads.gml           — combined corridor graph (I-16 + I-75)
    corridor_nodes.json    — static route nodes {route_id, seq, lat, lon,
                             distance_mi} for offline demo (no graph needed)

Filtering: highway in ["motorway", "trunk", "primary"], simplify=True.
Budget: each graph < 2 s to load; combined < 5000 nodes.

Usage:
    python scripts/build_roads.py [--no-fetch]   # --no-fetch re-emits nodes only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fortyguard_sdk.clustering import route_nodes  # noqa: E402
from fortyguard_sdk.georgia import GA_BBOX  # noqa: E402
from osmnx._errors import InsufficientResponseError  # noqa: E402

DATA = REPO / "data"
I16_GML = DATA / "ga_roads_i16.gml"
I75_GML = DATA / "ga_roads_i75.gml"
ALL_GML = DATA / "ga_roads.gml"
NODES_JSON = DATA / "corridor_nodes.json"

HIGHWAY_FILTER = '["highway"~"motorway|trunk|primary"]'

# ---- corridor bboxes (west, south, east, north) --------------------------
# Used only for the chunked fallback; the primary path fetches a narrow
# corridor polygon (route anchors buffered to CORRIDOR_BAND_M).
I16_BBOX = (-84.05, 31.85, -80.80, 33.15)   # Macon -> Savannah
I75_BBOX = (-84.50, 30.60, -83.00, 33.15)   # Macon -> Valdosta (I-75 spine)

# half-width of the corridor band around the route polyline (meters).
# 3 km total band keeps the Overpass query under osmnx's max area size.
CORRIDOR_BAND_M = 1500.0

# Preferred Overpass mirror (overpass-api.de is often congested).
OVERPASS_URL = "https://overpass-api.de/api"


def _overpass_status_pause(minimum: float = 2.0) -> float:
    """Read the Overpass status endpoint and return the slot-aware pause."""
    import re
    import subprocess

    try:
        p = subprocess.run(
            ["curl", "-s", "--max-time", "15",
             OVERPASS_URL.rstrip("/") + "/status"],
            capture_output=True, text=True, check=False,
        )
        text = p.stdout or ""
        m = re.search(r"Rate limit:\s*(\d+)", text)
        n_slots = int(m.group(1)) if m else 2
        m2 = re.search(r"(\d+)\s+slot", text)
        available = int(m2.group(1)) if m2 else 0
        if available < n_slots:
            return 30.0
        return minimum
    except Exception:  # noqa: BLE001
        return minimum


def _curl_overpass_request(data: dict) -> dict:
    """Overpass POST via curl subprocess.

    This environment's python requests/httpx connections to public Overpass
    mirrors get queued/throttled (slot management), while curl connects
    reliably. osmnx's ``_overpass_request`` is patched to delegate here.
    Handles HTTP 429/504 by pausing and retrying; respects slot availability.
    """
    import json
    import subprocess
    import time

    url = OVERPASS_URL.rstrip("/") + "/interpreter"
    query = data["data"]
    last_err: Exception | None = None
    for attempt in range(6):
        time.sleep(_overpass_status_pause(minimum=5.0))
        try:
            p = subprocess.run(
                ["curl", "-s", "--max-time", "180",
                 "--connect-timeout", "20",
                 "-w", "\n__HTTP__%{http_code}",
                 "-d", f"data={query}", url],
                capture_output=True, text=True, check=False,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
        body, _, code = p.stdout.rpartition("\n__HTTP__")
        http_code = int(code) if code.isdigit() else 0
        if http_code in (429, 504):
            print(f"    overpass {http_code}; pausing 60s ...")
            time.sleep(60)
            continue
        if http_code != 200 or not body.strip():
            last_err = ConnectionError(
                f"overpass HTTP {http_code} rc={p.returncode} "
                f"stderr={p.stderr[:150]}"
            )
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(15)
            continue
        if not isinstance(parsed, dict) or not parsed.get("elements"):
            # empty element list — retry once more, then raise
            if attempt >= 3:
                raise InsufficientResponseError(
                    "No data elements in server response. Check query "
                    "location/filters and log."
                )
            time.sleep(15)
            continue
        return parsed
    raise RuntimeError(f"overpass fetch failed after retries: {last_err}")


def _patch_osmnx_transport() -> None:
    """Point osmnx's Overpass request at curl; skip status/DNS round-trips."""
    import osmnx as ox
    from osmnx import _http, _overpass

    _overpass._overpass_request = _curl_overpass_request
    _http._config_dns = lambda url: None
    _overpass._get_overpass_pause = lambda *a, **k: 0
    ox.settings.overpass_url = OVERPASS_URL
    ox.settings.overpass_settings = "[out:json][timeout:120]{maxsize}"
    ox.settings.overpass_rate_limit = False
    ox.settings.requests_timeout = 120
    ox.settings.use_cache = True

# ---- route anchor towns (approx real corridors) -------------------------
# Anchor pairs are (lon, lat) to match the SDK's (lon, lat) convention.
I16_ANCHORS = [
    (-83.6324, 32.8407),   # Macon
    (-83.7520, 32.6540),   # Byron
    (-82.9038, 32.5404),   # Dublin
    (-82.4135, 32.2177),   # Vidalia
    (-82.0601, 32.3971),   # Metter
    (-81.7832, 32.4488),   # Statesboro
    (-81.2471, 32.1155),   # Pooler
    (-81.0912, 32.0809),   # Savannah
]

I75_ANCHORS = [
    (-83.6324, 32.8407),   # Macon
    (-83.7316, 32.4582),   # Perry
    (-83.7824, 31.9635),   # Cordele
    (-83.5085, 31.4505),   # Tifton
    (-83.2783, 30.8325),   # Valdosta
    (-82.7476, 31.0369),   # Homerville (US-84 east)
    (-82.3549, 31.2136),   # Waycross
    (-81.8854, 31.6074),   # Jesup
    (-81.7426, 31.7085),   # Ludowici
    (-81.5959, 31.8469),   # Hinesville
    (-81.3037, 31.9363),   # Richmond Hill (I-95)
    (-81.0912, 32.0809),   # Savannah
]


def _project_buffer(anchors: list[tuple[float, float]], band_m: float):
    """Buffer a lon/lat polyline by `band_m` meters, returning a WGS84 polygon."""
    import pyproj
    from shapely.geometry import LineString
    from shapely.ops import transform

    line = LineString(anchors)
    cx, cy = line.centroid.x, line.centroid.y
    aeqd = pyproj.Proj(proj="aeqd", lat_0=cy, lon_0=cx, ellps="WGS84")
    wgs = pyproj.Proj(proj="latlong", datum="WGS84")
    to_local = pyproj.Transformer.from_proj(wgs, aeqd, always_xy=True).transform
    to_wgs = pyproj.Transformer.from_proj(aeqd, wgs, always_xy=True).transform
    local_line = transform(to_local, line)
    return transform(to_wgs, local_line.buffer(band_m))


def build_graph(
    name: str, anchors: list[tuple[float, float]]
) -> "nx.MultiDiGraph":
    """Download the corridor road network along `anchors`.

    The route is split into ~0.25 deg chunks; each chunk's bbox (slightly
    inflated) is fetched via ``ox.graph_from_bbox`` and the chunk graphs are
    composed. Bbox ``(…;>;);out`` queries are fast on the public server,
    whereas complex ``poly:`` band polygons 504.
    """
    import networkx as nx
    import osmnx as ox
    from shapely.geometry import LineString

    _patch_osmnx_transport()

    line = LineString(anchors)
    n_chunks = max(1, int(line.length / 0.25))  # ~0.25 deg (~17 mi) per chunk
    combined: nx.MultiDiGraph | None = None
    t0 = time.monotonic()
    for i in range(n_chunks):
        a = line.length * i / n_chunks
        b = line.length * (i + 1) / n_chunks
        sub = _slice_line(line, a, b)
        minx, miny, maxx, maxy = sub.bounds
        pad = 0.03
        west, south = minx - pad, miny - pad
        east, north = maxx + pad, maxy + pad
        print(f"[{name}] chunk {i + 1}/{n_chunks}: bbox "
              f"({west:.3f},{south:.3f},{east:.3f},{north:.3f}) ...")
        try:
            Gc = ox.graph_from_bbox(
                (west, south, east, north),
                network_type="drive",
                simplify=True,
                retain_all=False,
                custom_filter=HIGHWAY_FILTER,
            )
        except Exception as exc:  # noqa: BLE001 — retry with a wider pad once
            print(f"    chunk failed ({type(exc).__name__}); widening bbox ...")
            Gc = ox.graph_from_bbox(
                (minx - 0.08, miny - 0.08, maxx + 0.08, maxy + 0.08),
                network_type="drive",
                simplify=True,
                retain_all=False,
                custom_filter=HIGHWAY_FILTER,
            )
        print(f"    chunk {i + 1}: {len(Gc.nodes)} nodes")
        combined = Gc if combined is None else nx.compose(combined, Gc)
    G = ox.convert.to_undirected(combined)
    print(
        f"[{name}] fetched: {len(G.nodes)} nodes, {G.number_of_edges()} edges "
        f"in {time.monotonic() - t0:.1f}s"
    )
    return G


def _slice_line(line, a_deg: float, b_deg: float):
    from shapely.geometry import LineString

    n = max(12, int((b_deg - a_deg) / 0.01))
    pts = [line.interpolate(a_deg + (b_deg - a_deg) * i / n) for i in range(n + 1)]
    return LineString(pts)


def save_graph(G, path: Path) -> None:
    import osmnx as ox

    path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, path)
    print(f"  saved {path.relative_to(REPO)}")


def load_graph_seconds(path: Path) -> tuple[int, int, float]:
    import osmnx as ox

    t0 = time.monotonic()
    G = ox.load_graphml(path)
    return len(G.nodes), G.number_of_edges(), time.monotonic() - t0


def emit_nodes() -> None:
    i16 = route_nodes(I16_ANCHORS, "I16", spacing_mi=5.0)
    i75 = route_nodes(I75_ANCHORS, "I75", spacing_mi=5.0)
    payload = {
        "schema_version": 1,
        "description": "Static corridor route nodes for offline demo "
                       "(no graph library required). spacing ~5 mi.",
        "generated_by": "scripts/build_roads.py",
        "routes": {"I16": {"anchors": len(I16_ANCHORS), "nodes": len(i16)},
                   "I75": {"anchors": len(I75_ANCHORS), "nodes": len(i75)}},
        "nodes": i16 + i75,
    }
    NODES_JSON.write_text(json.dumps(payload, indent=2))
    print(
        f"wrote {len(i16) + len(i75)} corridor nodes "
        f"({len(i16)} I16 + {len(i75)} I75) -> {NODES_JSON.relative_to(REPO)}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip OSM downloads; only re-emit corridor_nodes.json")
    args = ap.parse_args()

    if not args.no_fetch:
        import networkx as nx

        g16 = build_graph("I16", I16_ANCHORS)
        save_graph(g16, I16_GML)
        g75 = build_graph("I75", I75_ANCHORS)
        save_graph(g75, I75_GML)
        # combined graph (union keeps shared OSM nodes)
        combined = nx.compose(g16, g75)
        save_graph(combined, ALL_GML)
        print(f"  combined: {len(combined.nodes)} nodes")

        # verify load budget
        for p in (I16_GML, I75_GML, ALL_GML):
            n, e, secs = load_graph_seconds(p)
            print(f"  load {p.name}: {n} nodes, {e} edges in {secs:.2f}s")
            assert secs < 2.0, f"{p.name} load > 2s"
        n_all, _, _ = load_graph_seconds(ALL_GML)
        assert n_all < 5000, f"combined graph {n_all} nodes >= 5000"

    emit_nodes()
    return 0


if __name__ == "__main__":
    sys.exit(main())
