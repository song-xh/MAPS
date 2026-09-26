"""Evidence that the demo replay reflects the executed MPCS episode."""

from math import isclose

from maps_demo.engine import run_demo


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
    assert run["steps"][-1]["metrics"]["profit"] == summary["profit"]
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
