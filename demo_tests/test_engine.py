"""Check target-platform scope and the replay's connection to MPCS results."""

from math import isclose
from types import SimpleNamespace

import networkx as nx

from maps_demo.capa import CAPAAuctioneer
from maps_demo.engine import POLICIES, _vehicle_display, build_config, run_comparison, run_demo, source_options
from maps_demo.figures import map_dynamic_traces, minute_profit_figure
from maps_demo.presets import PresetSteps, _FrameWriter, _write_gzip, load_preset
from maps_demo.ramcom import RamCOMAuctioneer
from mpcs.core.RoadNetwork import RoadNetwork


def settings(algorithm="rl-capa"):
    return {
        "dataset": "synthetic", "platforms": 4, "pickups_per_platform": 10,
        "dropoffs_per_platform": 0, "vehicles_per_platform": 2,
        "step_size_s": 30, "seed": 11, "service_radius_km": 10.0,
        "deadline_s": 60, "sharing_rate": 0.3,
        "primary_platform": "P1", "algorithm": algorithm,
    }


def test_target_replay_uses_only_target_origin_metrics_and_parcels():
    run = run_demo(settings())
    summary = run["summary"]
    target = run["meta"]["primary_platform"]
    assert summary["total"] == sum(item["origin"] == target for item in run["catalog"].values())
    assert summary["assigned"] == summary["local_count"] + summary["cross_count"]
    assert isclose(summary["profit"], summary["profit_by_platform"][target])
    assert set(summary["platform_archive"]) == {target}
    assert set(summary["ledger_breakdown"]) == {target}
    assert summary["bpt_s"] > 0
    assert len(run["steps"]) == 5 * len(run["batches"])
    assert all(run["catalog"][pid]["origin"] == target
               for step in run["steps"] for pid in step["batch_parcels"])
    assert all(run["catalog"][pid]["origin"] == target
               for step in run["steps"] for pid in step["details"])
    assert len(run["catalog"]) == summary["total"]
    assert {vehicle["platform"] for vehicle in run["steps"][-1]["state"]["vehicles"].values()} == set(
        run["meta"]["platforms"])
    assert isclose(sum(minute_profit_figure(run, target).data[0].y[:-1]), summary["profit"])
    assert run["batches"][-1]["decision_time_s"] >= run["meta"]["analysis_end_s"]
    geography = run["geography"]
    assert geography["node_count"] == 2
    assert geography["arc_count"] == 2
    assert geography["segments"] == [[104.0, 30.7, 104.001, 30.7]]


def test_rl_capa_target_only_map():
    run = run_demo(settings())
    for step in run["steps"]:
        if step["stage"] != "settlement":
            continue
        parcel_traces = (trace for trace in map_dynamic_traces(run, step["index"], "P1", None)
                         if trace.name and trace.name.endswith("parcels"))
        for trace in parcel_traces:
            for _, parcel_id, _ in trace.customdata:
                assert run["catalog"][parcel_id]["origin"] == "P1"
                assert step["state"]["parcels"][parcel_id]["status"] in {
                    "waiting", "cross_pool", "public_this_step",
                }


def test_comparison_runs_all_algorithms_on_same_target_workload():
    selected = settings()
    selected["algorithms"] = ["rl-capa", "impgta", "mra", "greedy", "ramcom", "localsum"]
    result = run_comparison(selected)
    assert list(result["runs"]) == selected["algorithms"]
    assert len(result["catalog"]) == 10
    for name, run in result["runs"].items():
        assert run["meta"]["algorithm"] == name
        assert run["meta"]["primary_platform"] == "P1"
        assert run["summary"]["total"] == 10
        assert run["summary"]["bpt_s"] > 0
        assert "catalog" not in run and "geography" not in run


def test_ramcom_releases_low_value_relative_to_sampled_threshold_and_assigns_cross():
    selected = settings("ramcom")
    selected["seed"] = 5
    run = run_demo(selected)
    released = [value for step in run["steps"] if step["stage"] == "parcel"
                for value in step["decisions"].values()]
    assert "RELEASE" in released
    assert run["summary"]["cross_count"] > 0
    assert any(detail.get("awards") for step in run["steps"] if step["stage"] == "settlement"
               for detail in step["details"].values())


def test_ramcom_payment_and_sampled_acceptance_fit_mpcs_award():
    auction = RamCOMAuctioneer({"low": (2.0, 2.0), "high": (5.0, 1.0)}, seed=4)
    lot = SimpleNamespace(parcel_token="parcel", fare_amount=10.0, decision_frame_id="frame")
    intents = tuple(SimpleNamespace(server_payload=SimpleNamespace(
        parcel_token="parcel", intent_token=token, bidder_platform_id=platform,
    )) for token, platform in (("low", "P2"), ("high", "P3")))
    award, = auction.settle((lot,), intents, None)
    assert award.payment_amount == 2.0
    assert award.winner_platform_id == "P3"
    assert award.valid_bidder_count == 2
    assert award.winner_bid_amount == award.payment_amount


def test_real_source_dates_and_window_scope():
    chosen = source_options("chengdu")[10:14]
    selected = settings()
    selected.update(dataset="chengdu", split="validation", window_start="07:00",
                    window_end="07:01", sources={f"P{index}": day
                                                for index, day in enumerate(chosen, start=1)},
                    pickups_per_platform=2, dropoffs_per_platform=1)
    config = build_config(selected)
    assert config.dataset.validation_source_files == tuple(chosen)
    assert config.simulation.start_time_s == 7 * 3600
    assert config.simulation.end_time_s == 7 * 3600 + 120
    run = run_demo(selected)
    assert run["meta"]["split"] == "validation"
    assert run["summary"]["total"] == 2
    assert run["summary"]["batch"] == 2
    assert len(run["batches"]) == 4


def test_vehicle_display_advances_on_road_path():
    graph = nx.Graph()
    for index in range(3):
        graph.add_node(f"n{index}", x=float(index), y=0.0)
    graph.add_edge("n0", "n1", length_m=100.0)
    graph.add_edge("n1", "n2", length_m=100.0)
    road = RoadNetwork(graph, source_cache_size=4)
    try:
        vehicle = SimpleNamespace(
            current_road_node_id="n0", current_location=road.location("n0"),
            active_leg_target_stop_id="s1", active_leg_remaining_distance_km=0.15,
            route_stops=[SimpleNamespace(road_node_id="n2")],
        )
        point, navigation = _vehicle_display(vehicle, road, {})
        assert point == [0.5, 0.0]
        assert navigation == [[0.5, 0.0], [1.0, 0.0], [2.0, 0.0]]
    finally:
        road.close()


def test_dapa_rejects_bids_above_primary_payment_limit():
    auction = CAPAAuctioneer(sharing_rate=0.3, platform_ids=("P1", "P2"))
    lot = SimpleNamespace(parcel_token="parcel", fare_amount=1.0, decision_frame_id="frame")
    intent = SimpleNamespace(server_payload=SimpleNamespace(
        parcel_token="parcel", bidder_platform_id="P2", frozen_offer_amount=1.0,
    ))
    quality = SimpleNamespace(scores_by_platform_id={"P2": 0.5})
    assert auction.settle((lot,), (intent,), quality) == ()
    assert auction.last_bids[0]["valid"] is False


def test_dapa_uses_second_platform_bid_for_payment():
    auction = CAPAAuctioneer(sharing_rate=0.3, platform_ids=("P1", "P2", "P3"))
    lot = SimpleNamespace(parcel_token="parcel", fare_amount=10.0, decision_frame_id="frame")
    intents = tuple(SimpleNamespace(server_payload=SimpleNamespace(
        parcel_token="parcel", bidder_platform_id=platform, frozen_offer_amount=amount,
        intent_token=platform,
    )) for platform, amount in (("P2", 1.0), ("P3", 2.0)))
    quality = SimpleNamespace(scores_by_platform_id={"P2": 1.0, "P3": 1.0})
    award, = auction.settle((lot,), intents, quality)
    assert award.winner_platform_id == "P2"
    assert award.winner_bid_amount == 4.0
    assert award.payment_amount == 5.0


def test_rl_capa_waits_for_ten_consecutive_batches_without_a_feasible_local_match():
    selected = settings()
    selected.update(step_size_s=20, deadline_s=240, service_radius_km=0.0001)
    run = run_demo(selected)
    histories = {}
    for step in run["steps"]:
        if step["stage"] == "parcel":
            for parcel_id, action in step["decisions"].items():
                histories.setdefault(parcel_id, []).append((
                    action, step["details"].get(parcel_id, {}).get("no_local_checks"),
                ))
    ten_checks = [history for history in histories.values()
                  if len(history) >= 10 and history[9][1] == 10]
    assert ten_checks
    assert any(history[:10] == [("WAIT", index) for index in range(1, 10)]
               + [("RELEASE", 10)] for history in ten_checks)


def test_preset_chunks_restore_all_display_stages(tmp_path):
    writer = _FrameWriter(tmp_path, "rl-capa")
    run = run_demo(settings(), batch_sink=writer.append)
    writer.flush()
    steps = PresetSteps(tmp_path, writer.files, writer.frame_count)
    assert run["steps"] == []
    assert len(steps) == 5 * len(run["batches"])
    assert [steps[index]["stage"] for index in range(5)] == [
        "workload", "parcel", "local", "auction", "settlement",
    ]
    assert steps[-1]["metrics"] == run["batches"][-1]
    assert steps[run["summary"]["flow_step_index"]]["batch"] == run["summary"]["batch"]


def test_preset_manifest_loads_comparison_and_selected_stage(tmp_path):
    directory = tmp_path / "fixture"
    writer = _FrameWriter(directory, "rl-capa")
    run = run_demo(settings(), batch_sink=writer.append)
    writer.flush()
    _write_gzip(directory / "shared.json.gz", {
        "catalog": run["catalog"], "geography": run["geography"],
    })
    _write_gzip(directory / "manifest.json.gz", {
        "settings": {"preset": "fixture"}, "counts": {"P1": {"pickup": 10, "dropoff": 0}},
        "runs": {name: {
            "meta": {**run["meta"], "algorithm": name}, "batches": run["batches"],
            "summary": run["summary"], "frame_count": writer.frame_count,
            "files": writer.files,
        } for name in POLICIES},
    })
    loaded = load_preset("fixture", tmp_path)
    assert list(loaded["runs"]) == list(POLICIES)
    assert loaded["runs"]["rl-capa"]["steps"][4]["stage"] == "settlement"
    assert loaded["runs"]["mra"]["meta"]["source"] == "replay"
    assert loaded["catalog"] == run["catalog"]
