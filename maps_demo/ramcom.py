"""RamCOM's value threshold and expected-revenue cooperation rule in MPCS."""

from __future__ import annotations

from dataclasses import replace
from math import ceil, exp, log, prod
from random import Random

from mpcs.algorithms.baseline.Greedy import GreedyParcelPolicy
from mpcs.core.Domain import (
    CandidateIntentBundle, CandidatePrivateReceipt, LocalAssignmentProposal,
    OpaqueAuctionAward, ParcelAction, ParcelDecision, PickupPlanningRequest,
    PlatformActionBatch, PlatformPlanningSnapshot, SealedBidIntent, VehicleStatus,
)
from mpcs.core.RouteUtils import RoutePlanningServiceImpl


class RamCOMPolicy:
    def __init__(self, platform, config, road, fares, seed):
        self.platform_id = platform
        self.rng = Random(seed)
        maximum = max(fares, default=0.0)
        theta = max(1, ceil(log(maximum + 1.0)))
        self.threshold = exp(self.rng.randint(1, theta))
        self.planner = GreedyParcelPolicy(
            platform_id=platform, road_network=road, greedy_config=config.greedy,
            routing_config=config.routing, travel_cost_per_km=config.reward.travel_cost_per_km,
        )

    def decide(self, observation):
        decisions = []
        for pickup in observation.waiting_pickups:
            local = (pickup.fare_amount > self.threshold
                     and self.planner._best_local_option(pickup=pickup, observation=observation) is not None)
            decisions.append(ParcelDecision(
                parcel_id=pickup.parcel_id,
                action=ParcelAction.LOCAL if local else ParcelAction.RELEASE,
            ))
        return PlatformActionBatch(
            frame=observation.frame, platform_id=self.platform_id, decisions=tuple(decisions),
        )


class RamCOMLocalMatcher:
    def __init__(self, platform, seed):
        self.platform_id = platform
        self.rng = Random(seed)

    def plan(self, actions, state, planning):
        proposals = []
        shadow = state
        for parcel in sorted(actions.local_pickups, key=lambda item: (item.deadline_s, item.parcel_id)):
            options = planning.all_feasible_insertions(parcel, shadow)
            if not options:
                continue
            option = self.rng.choice(options)
            proposals.append(LocalAssignmentProposal(
                proposal_token=f"ramcom:{actions.frame.decision_frame_id}:{parcel.parcel_id}",
                frame=actions.frame, platform_id=self.platform_id, parcel_id=parcel.parcel_id,
                vehicle_id=option.vehicle_id, insertion=option,
            ))
            shadow = PlatformPlanningSnapshot(
                frame=shadow.frame, platform_id=self.platform_id,
                vehicles=tuple(replace(vehicle, status=VehicleStatus.EN_ROUTE,
                                       route_stops=option.proposed_route_stops,
                                       route_version=vehicle.route_version + 1)
                               if vehicle.vehicle_id == option.vehicle_id else vehicle
                               for vehicle in shadow.vehicles),
            )
        return tuple(proposals)


class RamCOMBidder:
    candidate_mode = "all"
    cross_selection_mode = "auction"

    def __init__(self, platform, primary, parcels, tokens, road, offers):
        self.platform_id = platform
        self.primary = primary
        self.parcels = parcels
        self.tokens = tokens
        self.planner = RoutePlanningServiceImpl(platform, road)
        self.offers = offers

    def build_intents(self, snapshot, state):
        if self.platform_id == self.primary:
            return ()
        result = []
        for descriptor in snapshot.descriptors:
            parcel = self.parcels.get(self.tokens.get(descriptor.parcel_token))
            if parcel is None or parcel.origin_platform_id != self.primary or parcel.fare_amount <= 0:
                continue
            request = PickupPlanningRequest(
                parcel_id=parcel.parcel_id, origin_platform_id=parcel.origin_platform_id,
                road_node_id=parcel.road_node_id, arrival_time_s=parcel.arrival_time_s,
                deadline_s=parcel.deadline_s, capacity_units=parcel.capacity_units,
            )
            options = self.planner.all_feasible_insertions(request, state)
            if not options:
                continue
            option = min(options, key=lambda item: (item.extra_distance_km, item.vehicle_id))
            reservation = min(float(parcel.fare_amount),
                              max(1e-9, 0.2 * float(parcel.fare_amount) + option.extra_distance_km))
            token = f"ramcom:{descriptor.decision_frame_id}:{descriptor.parcel_token}:{self.platform_id}"
            self.offers[token] = (reservation, option.extra_distance_km)
            result.append(CandidateIntentBundle(
                server_payload=SealedBidIntent(
                    intent_token=token, parcel_token=descriptor.parcel_token,
                    bidder_platform_id=self.platform_id, privacy_query_id=token,
                    decision_frame_id=descriptor.decision_frame_id, frozen_offer_amount=reservation,
                ),
                private_receipt=CandidatePrivateReceipt(
                    intent_token=token, bidder_platform_id=self.platform_id,
                    true_potential_component=0.0, true_beta=0.0,
                    private_candidate_vehicle_ids=(option.vehicle_id,),
                ),
            ))
        return tuple(result)


class RamCOMAuctioneer:
    """Maximize expected origin revenue, then sample partner acceptance."""

    def __init__(self, offers, seed):
        self.offers = offers
        self.rng = Random(seed)
        self.last_bids = []

    def settle(self, lots, intents, _quality):
        grouped = {}
        for intent in intents:
            grouped.setdefault(intent.server_payload.parcel_token, []).append(intent.server_payload)
        awards = []
        self.last_bids = []
        for lot in lots:
            candidates = grouped.get(lot.parcel_token, [])
            if not candidates:
                continue
            fare = lot.fare_amount
            prices = {fare, *(self.offers[bid.intent_token][0] for bid in candidates)}
            def acceptance(price, bid):
                return min(1.0, price / self.offers[bid.intent_token][0])
            payment = max(sorted(prices), key=lambda price: (
                (fare - price) * (1.0 - prod(1.0 - acceptance(price, bid) for bid in candidates)),
                -price,
            ))
            accepted = []
            for bid in candidates:
                valid = self.rng.random() <= acceptance(payment, bid)
                self.last_bids.append({
                    "token": lot.parcel_token, "platform": bid.bidder_platform_id,
                    "amount": self.offers[bid.intent_token][0], "payment": payment,
                    "valid": valid,
                })
                if valid:
                    accepted.append(bid)
            if not accepted:
                continue
            winner = min(accepted, key=lambda bid: (
                self.offers[bid.intent_token][1], bid.bidder_platform_id,
            ))
            awards.append(OpaqueAuctionAward(
                parcel_token=lot.parcel_token, winner_intent_token=winner.intent_token,
                winner_platform_id=winner.bidder_platform_id, payment_amount=payment,
                winner_bid_amount=payment,
                valid_bidder_count=len(candidates), decision_frame_id=lot.decision_frame_id,
            ))
        return tuple(awards)
