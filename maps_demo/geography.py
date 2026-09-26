"""Map layers read from the operational road graph and station index."""

from __future__ import annotations

from typing import Any


def prepared_geography(prepared: Any) -> dict[str, Any]:
    """Serialize every road connection and station in a prepared scenario."""
    road = prepared.road_network
    coordinates = road._coordinates
    csr = road._directed_csr
    segments: list[list[float]] = []
    seen: set[tuple[int, int]] = set()
    for source in range(len(road.node_ids)):
        for arc in range(int(csr.indptr[source]), int(csr.indptr[source + 1])):
            target = int(csr.indices[arc])
            pair = (min(source, target), max(source, target))
            if source == target or pair in seen:
                continue
            seen.add(pair)
            x0, y0 = coordinates[source]
            x1, y1 = coordinates[target]
            segments.append([float(x0), float(y0), float(x1), float(y1)])

    stations = [
        {
            "id": station.station_id,
            "node": station.road_node_id,
            "point": [float(value) for value in coordinates[road._node_positions[station.road_node_id]]],
        }
        for station in prepared.station_index.stations
    ]
    return {
        "node_count": len(road.node_ids),
        "arc_count": road.edge_count,
        "display_segment_count": len(segments),
        "segments": segments,
        "stations": stations,
    }
