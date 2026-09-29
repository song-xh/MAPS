"""Check the target's batch matcher and partner courier auction."""

from types import SimpleNamespace

from maps_demo.capa import CAPABidder
from mpcs.algorithms.baseline.Greedy import GreedyParcelPolicy
from mpcs.core.Domain import (
    DecisionFrameRef,
    GeoPoint,
    ParcelDecisionObservation,
    ParcelStatus,
    PlatformObservation,
    RouteInsertionOption,
    RouteStop,
    StopType,
)


def _option(parcel_id: str, vehicle_id: str, distance: float) -> RouteInsertionOption:
    stop = RouteStop(
        stop_id=f"{parcel_id}:{vehicle_id}:{distance}",
        stop_type=StopType.PICKUP,
        road_node_id="n",
        parcel_id=parcel_id,
        station_id=None,
        deadline_s=120,
        load_delta=1,
    )
    return RouteInsertionOption(
        parcel_id=parcel_id,
        vehicle_id=vehicle_id,
        insertion_index=0,
        extra_distance_km=distance,
        projected_pickup_time_s=0.0,
        base_route_version=0,
        proposed_route_stops=(stop,),
        projected_arrival_times_s=(0.0,),
        projected_load_counts=(1,),
    )


def test_greedy_matches_once_in_descending_fare_order(monkeypatch):
    frame = DecisionFrameRef(environment_id="demo", episode_id="one",
                             decision_frame_id="batch", current_time_s=20)
    point = GeoPoint(longitude_deg=104.0, latitude_deg=30.7)
    parcels = tuple(ParcelDecisionObservation(
        parcel_id=parcel_id, origin_platform_id="P1", road_node_id="n",
        location=point, region_id="r", arrival_time_s=0, deadline_s=120,
        fare_amount=fare, status=ParcelStatus.WAITING,
    ) for parcel_id, fare in (("low", 10.0), ("mid", 15.0), ("high", 20.0)))
    observation = PlatformObservation(
        frame=frame, platform_id="P1", waiting_pickups=parcels,
        vehicles=(), station_queues=(),
    )
    options = {
        "high": (_option("high", "C1", 1.0),),
        "mid": (_option("mid", "C1", 1.0), _option("mid", "C2", 2.0)),
        "low": (_option("low", "C1", 1.0), _option("low", "C2", 2.0)),
    }
    visited = []

    def local_options(_self, *, pickup, observation):
        visited.append(pickup.parcel_id)
        return options[pickup.parcel_id]

    monkeypatch.setattr(GreedyParcelPolicy, "_local_options", local_options)
    greedy = object.__new__(GreedyParcelPolicy)
    greedy.platform_id = "P1"
    batch = greedy.decide(SimpleNamespace(raw_environment_observation=observation))
    assert visited == ["high", "mid", "low"]
    assert [(item.parcel_id, item.action.name) for item in batch.decisions] == [
        ("high", "LOCAL"), ("mid", "LOCAL"), ("low", "RELEASE"),
    ]
    proposals = greedy.plan(
        SimpleNamespace(platform_id="P1", frame=frame,
                        local_pickups=(SimpleNamespace(parcel_id="high"),
                                       SimpleNamespace(parcel_id="mid"))),
        SimpleNamespace(platform_id="P1"), SimpleNamespace(platform_id="P1"),
    )
    assert [(item.parcel_id, item.vehicle_id) for item in proposals] == [
        ("high", "C1"), ("mid", "C2"),
    ]
    assert visited == ["high", "mid", "low"]


def test_partner_submits_lowest_internal_courier_bid(monkeypatch):
    parcel = SimpleNamespace(
        parcel_id="parcel", origin_platform_id="P1", road_node_id="n",
        arrival_time_s=0, deadline_s=120, capacity_units=1, fare_amount=10.0,
    )
    planner = SimpleNamespace(all_feasible_insertions=lambda *_: (
        _option("parcel", "C1", 0.8), _option("parcel", "C1", 0.4),
        _option("parcel", "C2", 0.2),
    ))
    monkeypatch.setattr("maps_demo.capa.RoutePlanningServiceImpl", lambda *_: planner)
    bidder = CAPABidder("P2", "P1", {"parcel": parcel}, {"token": "parcel"},
                        SimpleNamespace(), SimpleNamespace(), 0.3)
    bidder._auction_detour_term = lambda _vehicle, _request, option: option.extra_distance_km
    snapshot = SimpleNamespace(descriptors=(SimpleNamespace(
        parcel_token="token", decision_frame_id="batch",
    ),))
    state = SimpleNamespace(vehicles=(SimpleNamespace(vehicle_id="C1"),
                                      SimpleNamespace(vehicle_id="C2")))
    bundle, = bidder.build_intents(snapshot, state)
    assert bundle.private_receipt.private_candidate_vehicle_ids == ("C2",)
    assert len(bidder.last_courier_bids) == 2
    assert {item["vehicle_id"] for item in bidder.last_courier_bids if item["selected"]} == {"C2"}
    assert bundle.server_payload.frozen_offer_amount == min(
        item["amount"] for item in bidder.last_courier_bids
    )
