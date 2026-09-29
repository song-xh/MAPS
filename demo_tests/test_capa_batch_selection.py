"""Check value priority, courier fallback, and threshold release in one batch."""

from types import SimpleNamespace

from mpcs.algorithms.baseline.Common import BaselineConfig, BaselineMethod
from mpcs.algorithms.baseline.Framework import _LocalAlgorithm
from mpcs.algorithms.baseline.RLCAPA import RLCAPARule
from mpcs.core.Domain import (
    DecisionFrameRef,
    GeoPoint,
    ParcelDecisionObservation,
    ParcelStatus,
    ParcelType,
    PlatformObservation,
    RouteInsertionOption,
    RouteStop,
    StopType,
    VehicleSnapshot,
    VehicleStatus,
)
from mpcs.core.SettlementUtils import _local_proposal_priority


def test_capa_prioritizes_value_retries_other_courier_and_releases_below_threshold(monkeypatch):
    point = GeoPoint(longitude_deg=104.0, latitude_deg=30.7)
    frame = DecisionFrameRef(environment_id="demo", episode_id="episode",
                             decision_frame_id="batch-1", current_time_s=0)
    vehicles = tuple(VehicleSnapshot(
        vehicle_id=f"P1-C{i}", platform_id="P1", current_road_node_id="n",
        current_location=point, status=VehicleStatus.IDLE, max_capacity=1,
        speed_km_per_s=0.01, service_radius_km=10.0, load_count=0,
        route_version=0, route_stops=(), onboard_parcel_ids=(),
        active_leg_target_stop_id=None, active_leg_remaining_distance_km=0.0,
    ) for i in range(1, 4))
    parcels = tuple(ParcelDecisionObservation(
        parcel_id=name, origin_platform_id="P1", road_node_id="n",
        location=point, region_id="r", arrival_time_s=0,
        deadline_s=deadline, fare_amount=fare, status=ParcelStatus.WAITING,
    ) for name, deadline, fare in (("mid", 90, 15.0), ("high", 100, 20.0),
                                  ("low", 110, 1.0)))

    class Planner:
        platform_id = "P1"

        def feasible_insertions(self, request, state):
            allowed = {"high": {"P1-C1", "P1-C2"},
                       "mid": {"P1-C1", "P1-C2"}, "low": {"P1-C3"}}
            options = []
            for vehicle in state.vehicles:
                if vehicle.vehicle_id not in allowed[request.parcel_id] or vehicle.route_version:
                    continue
                stop = RouteStop(
                    stop_id=f"{request.parcel_id}:{vehicle.vehicle_id}",
                    stop_type=StopType.PICKUP, road_node_id="n",
                    parcel_id=request.parcel_id, station_id=None,
                    deadline_s=request.deadline_s, load_delta=1,
                )
                options.append(RouteInsertionOption(
                    parcel_id=request.parcel_id, vehicle_id=vehicle.vehicle_id,
                    insertion_index=0, extra_distance_km=float(vehicle.vehicle_id[-1]),
                    projected_pickup_time_s=0.0, base_route_version=vehicle.route_version,
                    proposed_route_stops=(stop,), projected_arrival_times_s=(0.0,),
                    projected_load_counts=(1,),
                ))
            return tuple(options)

    planner = Planner()
    monkeypatch.setattr("mpcs.algorithms.baseline.Framework.RoutePlanningServiceImpl",
                        lambda *_args, **_kwargs: planner)
    monkeypatch.setattr(RLCAPARule, "_capa_pair_utility",
                        lambda _self, _request, option, _vehicle, _cache:
                        option.extra_distance_km)
    algorithm = _LocalAlgorithm(
        method=BaselineMethod.RL_CAPA, platform_id="P1",
        road_network=SimpleNamespace(node_id_set=frozenset({"n"})),
        config=BaselineConfig(),
    )
    observation = PlatformObservation(
        frame=frame, platform_id="P1", waiting_pickups=parcels,
        vehicles=vehicles, station_queues=(),
    )

    batch = algorithm.decide(SimpleNamespace(raw_environment_observation=observation))
    actions = {item.parcel_id: item.action.name for item in batch.decisions}
    proposals = {item.parcel_id: item.vehicle_id
                 for item in algorithm.cache.get_for_frame(frame).proposals}

    assert actions == {"mid": "LOCAL", "high": "LOCAL", "low": "RELEASE"}
    assert proposals == {"high": "P1-C1", "mid": "P1-C2"}
    assert algorithm.last_threshold > 0.8

    only_one_courier = _LocalAlgorithm(
        method=BaselineMethod.RL_CAPA, platform_id="P1",
        road_network=SimpleNamespace(node_id_set=frozenset({"n"})),
        config=BaselineConfig(),
    )
    constrained = PlatformObservation(
        frame=frame, platform_id="P1", waiting_pickups=parcels,
        vehicles=vehicles[:1], station_queues=(),
    )
    constrained_batch = only_one_courier.decide(
        SimpleNamespace(raw_environment_observation=constrained))
    constrained_actions = {item.parcel_id: item.action.name
                           for item in constrained_batch.decisions}
    assert constrained_actions == {"mid": "WAIT", "high": "LOCAL", "low": "RELEASE"}
    assert only_one_courier.last_no_local_checks["mid"] == 1
    assert "low" not in only_one_courier.last_no_local_checks


def test_capa_reuses_route_capacity_after_value_ordered_first_round(monkeypatch):
    point = GeoPoint(longitude_deg=104.0, latitude_deg=30.7)
    frame = DecisionFrameRef(environment_id="demo", episode_id="episode",
                             decision_frame_id="batch-2", current_time_s=20)
    vehicle = VehicleSnapshot(
        vehicle_id="P1-C1", platform_id="P1", current_road_node_id="n",
        current_location=point, status=VehicleStatus.IDLE, max_capacity=2,
        speed_km_per_s=0.01, service_radius_km=10.0, load_count=0,
        route_version=0, route_stops=(), onboard_parcel_ids=(),
        active_leg_target_stop_id=None, active_leg_remaining_distance_km=0.0,
    )
    parcels = tuple(ParcelDecisionObservation(
        parcel_id=name, origin_platform_id="P1", road_node_id="n",
        location=point, region_id="r", arrival_time_s=0,
        deadline_s=deadline, fare_amount=fare, status=ParcelStatus.WAITING,
    ) for name, deadline, fare in (("mid", 90, 15.0), ("high", 120, 20.0)))

    class Planner:
        platform_id = "P1"

        def feasible_insertions(self, request, state):
            courier = state.vehicles[0]
            if request.parcel_id == "high" and courier.route_version:
                return ()
            previous = courier.route_stops
            stop = RouteStop(
                stop_id=request.parcel_id, stop_type=StopType.PICKUP,
                road_node_id="n", parcel_id=request.parcel_id,
                station_id=None, deadline_s=request.deadline_s, load_delta=1,
            )
            return (RouteInsertionOption(
                parcel_id=request.parcel_id, vehicle_id=courier.vehicle_id,
                insertion_index=len(previous), extra_distance_km=0.0,
                projected_pickup_time_s=20.0,
                base_route_version=courier.route_version,
                proposed_route_stops=(*previous, stop),
                projected_arrival_times_s=(20.0,) * (len(previous) + 1),
                projected_load_counts=tuple(range(1, len(previous) + 2)),
            ),)

    monkeypatch.setattr("mpcs.algorithms.baseline.Framework.RoutePlanningServiceImpl",
                        lambda *_args, **_kwargs: Planner())
    monkeypatch.setattr(RLCAPARule, "_capa_pair_utility",
                        lambda *_args: 1.0)
    algorithm = _LocalAlgorithm(
        method=BaselineMethod.RL_CAPA, platform_id="P1",
        road_network=SimpleNamespace(node_id_set=frozenset({"n"})),
        config=BaselineConfig(),
    )
    observation = PlatformObservation(
        frame=frame, platform_id="P1", waiting_pickups=parcels,
        vehicles=(vehicle,), station_queues=(),
    )
    batch = algorithm.decide(SimpleNamespace(raw_environment_observation=observation))
    proposals = algorithm.cache.get_for_frame(frame).proposals
    assert {item.parcel_id: item.action.name for item in batch.decisions} == {
        "high": "LOCAL", "mid": "LOCAL",
    }
    assert [(item.parcel_id, item.insertion.base_route_version) for item in proposals] == [
        ("high", 0), ("mid", 1),
    ]


def test_local_settlement_preserves_same_courier_route_versions():
    world = SimpleNamespace(parcels_by_id={
        "high": SimpleNamespace(parcel_id="high", parcel_type=ParcelType.PICKUP,
                                deadline_s=120, arrival_time_s=0),
        "mid": SimpleNamespace(parcel_id="mid", parcel_type=ParcelType.PICKUP,
                               deadline_s=90, arrival_time_s=0),
    })
    proposals = [SimpleNamespace(
        parcel_id=parcel_id, proposal_token=parcel_id, vehicle_id="P1-C1",
        insertion=SimpleNamespace(base_route_version=version),
    ) for parcel_id, version in (("mid", 1), ("high", 0))]
    assert [item.parcel_id for item in sorted(
        proposals, key=lambda item: _local_proposal_priority(world, item)
    )] == ["high", "mid"]
