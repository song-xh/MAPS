"""Exact-route CAPA bidding for the selected origin platform's demo run."""

from __future__ import annotations

from collections import defaultdict

from mpcs.core.Domain import (
    CandidateIntentBundle, CandidatePrivateReceipt, OpaqueAuctionAward,
    PickupPlanningRequest, SealedBidIntent, StopType,
)
from mpcs.core.RouteUtils import RoutePlanningServiceImpl

FIRST_LAYER_SHARE = 0.3
PLATFORM_BASE_PRICE = 1.0
COURIER_DETOUR_WEIGHT = 0.5
COURIER_SERVICE_SCORE = 0.8


class CAPABidder:
    """Send one FPSA offer whenever this partner has a feasible courier."""

    candidate_mode = "all"
    cross_selection_mode = "auction"

    def __init__(self, platform_id, primary, parcels, tokens, road, stations, sharing_rate):
        self.platform_id = platform_id
        self.primary = primary
        self.parcels = parcels
        self.tokens = tokens
        self.road = road
        self.stations = stations
        self.sharing_rate = sharing_rate
        self.planner = RoutePlanningServiceImpl(platform_id, road)

    def _detour_ratio(self, vehicle, request, option):
        route = [vehicle.current_road_node_id, *(stop.road_node_id for stop in vehicle.route_stops)]
        if not vehicle.route_stops or vehicle.route_stops[-1].stop_type is not StopType.STATION_RETURN:
            route.append(self.stations.nearest_station(route[-1]).road_node_id)
        start, end = route[option.insertion_index:option.insertion_index + 2]
        original = self.road.shortest_distance_m(start, end) / 1000.0
        detour = (self.road.shortest_distance_m(start, request.road_node_id)
                  + self.road.shortest_distance_m(request.road_node_id, end)) / 1000.0
        return original / detour if detour > 0 else 1.0

    def build_intents(self, public_snapshot, own_planning_state):
        if self.platform_id == self.primary:
            return ()
        vehicles = {vehicle.vehicle_id: vehicle for vehicle in own_planning_state.vehicles}
        bundles = []
        for descriptor in public_snapshot.descriptors:
            parcel_id = self.tokens.get(descriptor.parcel_token)
            parcel = self.parcels.get(parcel_id)
            if parcel is None or parcel.origin_platform_id != self.primary:
                continue
            request = PickupPlanningRequest(
                parcel_id=parcel.parcel_id, origin_platform_id=parcel.origin_platform_id,
                road_node_id=parcel.road_node_id, arrival_time_s=parcel.arrival_time_s,
                deadline_s=parcel.deadline_s, capacity_units=parcel.capacity_units,
            )
            bids = []
            for option in self.planner.all_feasible_insertions(request, own_planning_state):
                ratio = self._detour_ratio(vehicles[option.vehicle_id], request, option)
                courier_bid = PLATFORM_BASE_PRICE + (
                    COURIER_DETOUR_WEIGHT * ratio
                    + (1.0 - COURIER_DETOUR_WEIGHT) * COURIER_SERVICE_SCORE
                ) * self.sharing_rate * FIRST_LAYER_SHARE * parcel.fare_amount
                bids.append((courier_bid, option.vehicle_id))
            if not bids:
                continue
            amount, vehicle_id = max(bids, key=lambda item: (item[0], item[1]))
            token = f"capa:{descriptor.decision_frame_id}:{descriptor.parcel_token}:{self.platform_id}"
            bundles.append(CandidateIntentBundle(
                server_payload=SealedBidIntent(
                    intent_token=token, parcel_token=descriptor.parcel_token,
                    bidder_platform_id=self.platform_id, privacy_query_id=token,
                    decision_frame_id=descriptor.decision_frame_id, frozen_offer_amount=amount,
                ),
                private_receipt=CandidatePrivateReceipt(
                    intent_token=token, bidder_platform_id=self.platform_id,
                    true_potential_component=0.0, true_beta=0.0,
                    private_candidate_vehicle_ids=(vehicle_id,),
                ),
            ))
        return tuple(bundles)


class CAPAAuctioneer:
    """DAPA second-layer platform auction over validated FPSA offers."""

    def __init__(self, sharing_rate, platform_ids):
        self.sharing_rate = sharing_rate
        self.platform_order = {platform: index for index, platform in enumerate(platform_ids)}
        self.last_bids = []

    def settle(self, lots, intents, quality):
        grouped = defaultdict(list)
        for intent in intents:
            grouped[intent.server_payload.parcel_token].append(intent.server_payload)
        self.last_bids = []
        awards = []
        for lot in lots:
            offers = grouped.get(lot.parcel_token, [])
            if not offers:
                continue
            scores = quality.scores_by_platform_id
            maximum = max(scores.get(offer.bidder_platform_id, 0.0) for offer in offers)
            ranked = []
            for offer in offers:
                factor = 1.0
                if len(offers) > 1:
                    factor = (scores.get(offer.bidder_platform_id, 0.0) / maximum
                              if maximum > 0 else 0.0)
                platform_bid = offer.frozen_offer_amount + factor * self.sharing_rate * lot.fare_amount
                valid = platform_bid <= (FIRST_LAYER_SHARE + self.sharing_rate) * lot.fare_amount
                self.last_bids.append({
                    "token": lot.parcel_token, "platform": offer.bidder_platform_id,
                    "courier_bid": offer.frozen_offer_amount, "amount": platform_bid,
                    "valid": valid,
                })
                if valid:
                    ranked.append((platform_bid, offer))
            ranked.sort(key=lambda item: (item[0], self.platform_order[item[1].bidder_platform_id]))
            if not ranked:
                continue
            winner_bid, winner = ranked[0]
            payment = ranked[1][0] if len(ranked) > 1 else winner_bid
            awards.append(OpaqueAuctionAward(
                parcel_token=lot.parcel_token, winner_intent_token=winner.intent_token,
                winner_platform_id=winner.bidder_platform_id, payment_amount=payment,
                winner_bid_amount=winner_bid, valid_bidder_count=len(ranked),
                decision_frame_id=lot.decision_frame_id,
            ))
        return tuple(awards)
