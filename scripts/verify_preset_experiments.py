"""Verify that both fixed city comparisons replay from saved artifacts."""

from __future__ import annotations

import json
from datetime import datetime
from math import ceil, isclose

from maps_demo.app import _batch_detail, _cache_run, render_analysis, simulation_result
from maps_demo.engine import POLICIES, STAGES, parse_clock
from maps_demo.figures import (
    comparison_metric_figure,
    comparison_profit_figure,
    flow_figure,
    map_figure,
)
from maps_demo.presets import PRESET_ROOT, PRESETS, load_preset, preset_settings


def verify() -> dict:
    report = {"status": "passed", "checked_at": datetime.now().astimezone().isoformat(), "cities": {}}
    for city, spec in PRESETS.items():
        result = load_preset(city)
        settings = preset_settings(city)
        assert result["settings"] == settings
        assert list(result["runs"]) == list(POLICIES)
        assert len(result["catalog"]) == result["counts"]["P1"]["pickup"]
        geography = result["geography"]
        assert geography["node_count"] > 1000
        assert geography["display_segment_count"] == len(geography["segments"])
        assert geography["stations"]
        expected_frames = ceil((3600 + 720) / 20)
        cutoff = parse_clock(spec["end"])
        city_report = {"pickup_counts": result["counts"], "road_nodes": geography["node_count"],
                       "road_arcs": geography["arc_count"], "algorithms": {}}
        runs = {name: {**run, "catalog": result["catalog"], "geography": geography}
                for name, run in result["runs"].items()}
        for name, run in runs.items():
            steps = run["steps"]
            assert len(run["batches"]) == expected_frames
            assert len(steps) == expected_frames * len(STAGES)
            assert run["meta"]["analysis_end_s"] == cutoff
            assert run["summary"]["total"] == result["counts"]["P1"]["pickup"]
            assert run["summary"]["assigned"] == run["summary"]["local_count"] + run["summary"]["cross_count"]
            assert isclose(run["summary"]["profit"], run["summary"]["profit_by_platform"]["P1"])
            assert steps[run["summary"]["flow_step_index"]]["stage"] == "settlement"
            bids = awards = tenth_releases = 0
            auction_step_index = None
            for index in range(0, len(steps), len(STAGES)):
                first = steps[index]
                settled = steps[index + len(STAGES) - 1]
                assert first["stage"] == "workload" and settled["stage"] == "settlement"
                assert first["batch"] == settled["batch"] == index // len(STAGES) + 1
                assert len(first["state"]["vehicles"]) == 4 * spec["vehicles"]
                assert len(first["state"]["parcels"]) == len(result["catalog"])
                for parcel_id, detail in settled["details"].items():
                    assert parcel_id in result["catalog"]
                    bids += len(detail.get("platform_bids", ()))
                    awards += len(detail.get("awards", ()))
                    if detail.get("awards") and auction_step_index is None:
                        auction_step_index = index + 3
                    tenth_releases += (detail.get("no_local_checks") == 10
                                       and settled["decisions"].get(parcel_id) == "RELEASE")
            if name == "rl-capa":
                assert bids > 0 and awards > 0
                assert _batch_detail(run, auction_step_index)
            city_report["algorithms"][name] = {
                "frames": expected_frames, "target_pickups": run["summary"]["total"],
                "assigned": run["summary"]["assigned"], "profit": run["summary"]["profit"],
                "bid_records": bids, "awards": awards,
                "tenth_check_releases": tenth_releases,
            }
        assert len(comparison_profit_figure(runs, per_minute=False).data) == len(POLICIES)
        assert len(comparison_profit_figure(runs, per_minute=True).data) == len(POLICIES)
        assert len(comparison_metric_figure(runs, "assignment_rate").data) == 1
        assert len(flow_figure(runs["rl-capa"]).data) == 1
        assert len(map_figure(runs["rl-capa"], 0, "P1", None).data) > 2
        reference = _cache_run(result)
        assert simulation_result(reference)
        cards, analysis = render_analysis(reference)
        assert len(cards) == 4 and analysis is not None
        report["cities"][city] = city_report
    PRESET_ROOT.mkdir(parents=True, exist_ok=True)
    (PRESET_ROOT / "verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> None:
    report = verify()
    print(f"Verified {len(report['cities'])} city presets and {len(POLICIES)} algorithms per city")


if __name__ == "__main__":
    main()
