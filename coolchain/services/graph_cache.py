"""PeachState CoolChain services — OSMnx graph cache (Georgia corridors).

Pre-build Macon-Savannah corridor road graphs ONCE and save to disk
(GraphML) so the demo runs fully offline. Deterministic + versioned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_ga_corridor_graph(
    out_path: Path = Path("data/graphs/ga_i75_i16.graphml"),
    place: str = "Macon, Georgia, USA",
) -> Path:
    """Build the GA corridor road network and persist as GraphML.

    Uses OSMnx drive network around the Macon->Savannah corridor bbox.
    """
    import osmnx as ox

    # corridor bbox covering Macon(32.84,-83.63) -> Savannah(32.08,-81.09)
    bbox = (31.5, 33.5, -84.0, -80.5)  # (north, south, west, east)
    G = ox.graph_from_bbox(bbox, network_type="drive")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, out_path)
    return out_path


def load_graph(path: Path) -> Any:
    """Load a cached GraphML corridor graph (fast, offline)."""
    import osmnx as ox

    return ox.load_graphml(path)


def get_ga_corridor_graph(
    path: Path = Path("data/graphs/ga_i75_i16.graphml"),
    force_rebuild: bool = False,
) -> Any:
    """Load from disk; build once if missing. Offline-safe."""
    if path.exists() and not force_rebuild:
        return load_graph(path)
    return build_ga_corridor_graph(path)