"""A released parcel remains auctionable while it waits in the cross pool."""

from maps_demo.capa import CAPABidder
from maps_demo.engine import run_demo


def test_unmatched_cross_pool_parcel_is_auctioned_again_next_batch(monkeypatch):
    attempts = set()

    def unavailable_partner(self, public_snapshot, own_planning_state):
        if self.platform_id == "P2":
            attempts.update(
                (own_planning_state.frame.current_time_s, self.tokens[item.parcel_token])
                for item in public_snapshot.descriptors
            )
        return ()

    monkeypatch.setattr(CAPABidder, "build_intents", unavailable_partner)
    run = run_demo({
        "dataset": "synthetic", "platforms": 4,
        "pickups_per_platform": 30, "dropoffs_per_platform": 0,
        "vehicles_per_platform": 1, "step_size_s": 20, "seed": 11,
        "service_radius_km": 0.0001, "deadline_s": 240,
        "sharing_rate": 0.3, "primary_platform": "P1",
        "algorithm": "rl-capa", "window_start": "00:00", "window_end": "00:05",
    })
    pooled = [
        (step["decision_time_s"], parcel_id)
        for step in run["steps"] if step["stage"] == "workload"
        for parcel_id, state in step["state"]["parcels"].items()
        if parcel_id in run["catalog"] and state["status"] == "cross_pool"
    ]
    auction_details = {
        step["decision_time_s"]: step["details"]
        for step in run["steps"] if step["stage"] == "auction"
    }
    assert pooled
    assert all(item in attempts for item in pooled)
    assert all(auction_details[time_s].get(parcel_id, {}).get("auction_attempts")
               for time_s, parcel_id in pooled)
