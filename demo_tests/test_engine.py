"""Evidence that the demo replay reflects the executed MPCS episode."""

from math import isclose
from types import SimpleNamespace

import networkx as nx

from maps_demo.engine import _vehicle_display, build_config, run_demo, source_options
from maps_demo.capa import CAPAAuctioneer
from maps_demo.figures import map_dynamic_traces, minute_profit_figure
from mpcs.core.RoadNetwork import RoadNetwork


def settings(mechanism="paper"):
    return {
        "dataset": "synthetic",
        "platforms": 4,
        "pickups_per_platform": 3,
        "dropoffs_per_platform": 1,
        "vehicles_per_platform": 2,
        "step_size_s": 30,
        "seed": 11,
        "matcher": "km",
        "mechanism": mechanism,
        "service_radius_km": 10.0,
        "deadline_s": 60,
        "sharing_rate": 0.3,
        "policies": {
            "P1": "release-first", "P2": "local-first",
            "P3": "mra", "P4": "impgta",
        },
    }


def test_paper_replay_contains_actual_second_price_and_receipts():
    run = run_demo(settings())
    summary = run["summary"]
    assert summary["assigned"] == summary["local_count"] + summary["cross_count"]
    assert isclose(summary["profit"], sum(summary["profit_by_platform"].values()))
    assert len(run["steps"]) == 5 * len(run["batches"])
    analyzed = [batch for batch in run["batches"]
                if batch["decision_time_s"] < run["meta"]["analysis_end_s"]]
    assert analyzed[-1]["profit"] == summary["profit"]
    assert run["batches"][-1]["decision_time_s"] >= run["meta"]["analysis_end_s"]
    assert isclose(sum(minute_profit_figure(run, "P1").data[0].y), summary["profit"])
    assert set(summary["platform_archive"]) == set(run["meta"]["platforms"])
    geography = run["geography"]
    assert geography["node_count"] == 2
    assert geography["arc_count"] == 2
    assert geography["segments"] == [[104.0, 30.7, 104.001, 30.7]]
    assert {station["node"] for station in geography["stations"]} == {"n0", "n1"}
    assert len(geography["stations"]) == 2

    multi_bid_lots = []
    for step in run["steps"]:
        if step["stage"] != "settlement":
            continue
        for detail in step["details"].values():
            bids = sorted(bid["amount"] for bid in detail.get("valid_bids", ()))
            awards = detail.get("awards", ())
            if len(bids) > 1 and awards:
                award = awards[0]
                multi_bid_lots.append(award)
                assert isclose(award["winner_bid"], bids[0])
                assert isclose(award["payment"], bids[1])
                assert isclose(detail["origin_receipt"]["payment"], award["payment"])
                assert isclose(detail["serving_receipt"]["payment"], award["payment"])
    assert multi_bid_lots


def test_fixed_payment_replay_uses_selected_mechanism():
    run = run_demo(settings("regional-fixed"))
    awards = [
        (run["catalog"][parcel_id], award)
        for step in run["steps"] if step["stage"] == "settlement"
        for parcel_id, detail in step["details"].items()
        for award in detail.get("awards", ())
    ]
    assert awards
    for parcel, award in awards:
        assert isclose(award["payment"], parcel["fare"] * 0.3)


def test_selected_split_dates_and_window_build_a_valid_config():
    chosen = source_options("chengdu")[10:14]
    selected = settings()
    selected.update(
        dataset="chengdu", split="validation", window_start="07:00",
        window_end="07:01", deadline_s=60,
        sources={f"P{index}": day for index, day in enumerate(chosen, start=1)},
    )
    config = build_config(selected)
    assert config.dataset.validation_source_files == tuple(chosen)
    assert config.simulation.start_time_s == 7 * 3600
    assert config.simulation.end_time_s == 7 * 3600 + 120


def test_real_date_selection_runs_with_selected_split_and_window():
    chosen = source_options("chengdu")[10:14]
    selected = settings()
    selected.update(
        dataset="chengdu", split="validation", window_start="07:00",
        window_end="07:01", deadline_s=60,
        pickups_per_platform=2, dropoffs_per_platform=1,
        sources={f"P{index}": day for index, day in enumerate(chosen, start=1)},
    )
    run = run_demo(selected)
    assert run["meta"]["split"] == "validation"
    assert run["summary"]["total"] == len(run["catalog"]) == 8
    assert run["summary"]["batch"] == 2
    assert len(run["batches"]) == 4


def test_rl_capa_batch_uses_all_eligible_partner_bids_and_dapa_payment():
    selected = settings()
    selected.update(primary_platform="P1", vehicles_per_platform=1,
                    pickups_per_platform=10, service_radius_km=0.1)
    selected["policies"]["P1"] = "rl-capa"
    run = run_demo(selected)
    assert run["meta"]["mechanism"] == "dapa"
    assert run["summary"]["cross_count"] > 0
    assert any(step["batch_parcels"] for step in run["steps"])
    revenue_history = []
    for step in run["steps"]:
        if step["stage"] != "settlement":
            continue
        revenue_history.extend(
            option["revenue_score"]
            for parcel_id, detail in step["details"].items()
            if run["catalog"][parcel_id]["origin"] == "P1"
            for option in detail.get("local_options", ())
            if "revenue_score" in option
        )
        if revenue_history:
            assert isclose(step["thresholds"]["P1"],
                           0.7 * sum(revenue_history) / len(revenue_history))
        for parcel_id, detail in step["details"].items():
            for award in detail.get("awards", ()):
                bids = sorted(bid["amount"] for bid in detail["valid_bids"] if bid["valid"])
                assert run["catalog"][parcel_id]["origin"] == "P1"
                assert {bid["platform"] for bid in detail["valid_bids"]} <= {"P2", "P3", "P4"}
                assert isclose(award["winner_bid"], bids[0])
                assert isclose(award["payment"], bids[1] if len(bids) > 1 else bids[0])
        parcel_traces = (trace for trace in map_dynamic_traces(run, step["index"], "P1", None)
                         if trace.name and trace.name.endswith("parcels"))
        for trace in parcel_traces:
            for _, parcel_id, _ in trace.customdata:
                assert step["state"]["parcels"][parcel_id]["status"] in {
                    "waiting", "cross_pool", "public_this_step",
                }


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
