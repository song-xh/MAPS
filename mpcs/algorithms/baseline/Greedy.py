"""Deterministic greedy policy and exact local matcher baseline."""

from __future__ import annotations

from math import isfinite

from mpcs.config import ExperimentConfig, GreedyConfig, RoutingConfig
from mpcs.core.Domain import (
    FrozenFederatedEmbedding,
    FrozenFederatedKnowledgeBatch,
    LocalAssignmentProposal,
    OwnReleaseHistorySnapshot,
    ParcelAction,
    ParcelDecision,
    ParcelDecisionObservation,
    PickupPlanningRequest,
    PlatformActionBatch,
    PlatformLocalActionView,
    PlatformObservation,
    PlatformPlanningSnapshot,
    PolicyDecisionContext,
    RouteInsertionOption,
    RoutePlanningService,
)
from mpcs.core.GraphUtils import RoadNetwork
from mpcs.core.LocalMatching import route_option_priority
from mpcs.core.RouteUtils import InsertionPlanner


class GreedyParcelPolicy:
    """Match one batch in descending fare order, releasing unmatched parcels."""

    __slots__ = (
        "_planner",
        "_road_node_ids",
        "platform_id",
        "_planned_frame",
        "_planned_proposals",
        "last_candidate_pairs",
    )

    def __init__(
        self,
        *,
        platform_id: str,
        road_network: RoadNetwork,
        greedy_config: GreedyConfig,
        routing_config: RoutingConfig,
        travel_cost_per_km: float,
    ) -> None:
        if not platform_id:
            raise ValueError("platform_id must be non-empty")
        greedy_config.validate()
        routing_config.validate()
        if not isfinite(float(travel_cost_per_km)) or travel_cost_per_km < 0:
            raise ValueError("travel_cost_per_km must be finite and non-negative")
        self.platform_id = platform_id
        shortcut_mode = routing_config.shortcut_mode
        shortcut_candidate_ev_limit = routing_config.shortcut_candidate_ev_limit
        shortcut_rescue_ev_limit = routing_config.shortcut_rescue_ev_limit
        if routing_config.candidate_ev_limit is not None:
            shortcut_mode = "balanced-shortcut-v1"
            shortcut_candidate_ev_limit = (
                routing_config.candidate_ev_limit
                if shortcut_candidate_ev_limit is None
                else min(
                    shortcut_candidate_ev_limit,
                    routing_config.candidate_ev_limit,
                )
            )
            shortcut_rescue_ev_limit = (
                routing_config.candidate_ev_limit
                if shortcut_rescue_ev_limit is None
                else min(
                    shortcut_rescue_ev_limit,
                    routing_config.candidate_ev_limit,
                )
            )
            if (
                shortcut_candidate_ev_limit is not None
                and shortcut_rescue_ev_limit is not None
                and shortcut_rescue_ev_limit < shortcut_candidate_ev_limit
            ):
                shortcut_candidate_ev_limit = shortcut_rescue_ev_limit
        self._planner = InsertionPlanner(
            road_network,
            insertion_candidate_limit=(routing_config.insertion_candidate_limit),
            shortcut_mode=shortcut_mode,
            shortcut_candidate_ev_limit=shortcut_candidate_ev_limit,
            shortcut_rescue_ev_limit=shortcut_rescue_ev_limit,
        )
        self._road_node_ids = road_network.node_id_set
        self._planned_frame = None
        self._planned_proposals: tuple[LocalAssignmentProposal, ...] = ()
        self.last_candidate_pairs: tuple[dict[str, float | str], ...] = ()

    def decide(
        self,
        context: PolicyDecisionContext,
    ) -> PlatformActionBatch:
        observation = context.raw_environment_observation
        if observation.platform_id != self.platform_id:
            raise ValueError("greedy policy received another platform")
        ordered_pickups = tuple(
            sorted(
                observation.waiting_pickups,
                key=lambda pickup: (
                    -pickup.fare_amount,
                    pickup.deadline_s,
                    pickup.arrival_time_s,
                    pickup.parcel_id,
                ),
            )
        )
        used_vehicle_ids: set[str] = set()
        decisions: list[ParcelDecision] = []
        proposals: list[LocalAssignmentProposal] = []
        candidate_pairs: list[dict[str, float | str]] = []
        for pickup in ordered_pickups:
            options = self._local_options(pickup=pickup, observation=observation)
            candidate_pairs.extend({
                "parcel_id": pickup.parcel_id,
                "vehicle_id": option.vehicle_id,
                "extra_km": float(option.extra_distance_km),
                "eta_s": float(option.projected_pickup_time_s),
            } for option in options)
            option = min(
                (item for item in options if item.vehicle_id not in used_vehicle_ids),
                key=route_option_priority,
                default=None,
            )
            decisions.append(ParcelDecision(
                parcel_id=pickup.parcel_id,
                action=ParcelAction.LOCAL if option is not None else ParcelAction.RELEASE,
            ))
            if option is None:
                continue
            used_vehicle_ids.add(option.vehicle_id)
            proposals.append(LocalAssignmentProposal(
                proposal_token=(
                    f"greedy-batch:{observation.frame.decision_frame_id}:"
                    f"{self.platform_id}:{pickup.parcel_id}"
                ),
                frame=observation.frame,
                platform_id=self.platform_id,
                parcel_id=pickup.parcel_id,
                vehicle_id=option.vehicle_id,
                insertion=option,
            ))
        self._planned_frame = observation.frame
        self._planned_proposals = tuple(proposals)
        self.last_candidate_pairs = tuple(candidate_pairs)
        return PlatformActionBatch(
            frame=observation.frame,
            platform_id=self.platform_id,
            decisions=tuple(decisions),
        )

    def plan(
        self,
        local_actions: PlatformLocalActionView,
        own_shadow_state: PlatformPlanningSnapshot,
        planning: RoutePlanningService,
    ) -> tuple[LocalAssignmentProposal, ...]:
        if (
            local_actions.platform_id != self.platform_id
            or own_shadow_state.platform_id != self.platform_id
            or planning.platform_id != self.platform_id
            or local_actions.frame != self._planned_frame
            or {item.parcel_id for item in local_actions.local_pickups}
            != {item.parcel_id for item in self._planned_proposals}
        ):
            raise ValueError("greedy matcher received a different decision batch")
        return self._planned_proposals

    def _best_local_option(
        self,
        *,
        pickup: ParcelDecisionObservation,
        observation: PlatformObservation,
    ) -> RouteInsertionOption | None:
        return min(
            self._local_options(pickup=pickup, observation=observation),
            key=route_option_priority,
            default=None,
        )

    def _local_options(
        self,
        *,
        pickup: ParcelDecisionObservation,
        observation: PlatformObservation,
    ) -> tuple[RouteInsertionOption, ...]:
        request = _planning_request(pickup)
        vehicles = tuple(
            vehicle
            for vehicle in observation.vehicles
            if (
                vehicle.current_road_node_id in self._road_node_ids
                and all(
                    stop.road_node_id in self._road_node_ids
                    for stop in vehicle.route_stops
                )
            )
        )
        return self._planner.feasible_insertions(
            parcel=request,
            vehicles=vehicles,
            current_time_s=observation.frame.current_time_s,
        )


def build_neutral_greedy_context(
    *,
    observation: PlatformObservation,
    config: ExperimentConfig,
) -> PolicyDecisionContext:
    """Build fixed zero knowledge inputs when the baseline runs without FL."""
    return PolicyDecisionContext(
        raw_environment_observation=observation,
        own_release_history=OwnReleaseHistorySnapshot(
            platform_id=observation.platform_id,
            schema_version=1,
            normalized_features=((0.0,) * config.ddqn.release_history_dim),
        ),
        federated_knowledge=FrozenFederatedKnowledgeBatch(
            frame=observation.frame,
            platform_id=observation.platform_id,
            federated_round_id=0,
            federated_model_version=0,
            embeddings_by_parcel_id={
                pickup.parcel_id: FrozenFederatedEmbedding(
                    federated_round_id=0,
                    federated_model_version=0,
                    values=((0.0,) * config.ddqn.federated_embedding_dim),
                )
                for pickup in observation.waiting_pickups
            },
        ),
    )


def _planning_request(
    pickup: ParcelDecisionObservation,
) -> PickupPlanningRequest:
    return PickupPlanningRequest(
        parcel_id=pickup.parcel_id,
        origin_platform_id=pickup.origin_platform_id,
        road_node_id=pickup.road_node_id,
        arrival_time_s=pickup.arrival_time_s,
        deadline_s=pickup.deadline_s,
        capacity_units=pickup.capacity_units,
    )
