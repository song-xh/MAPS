"""Evidence that the demo replay reflects the executed MPCS episode."""

from math import isclose

from maps_demo.engine import build_config, run_demo, source_options
from maps_demo.figures import minute_profit_figure


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
