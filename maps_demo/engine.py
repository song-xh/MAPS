"""Run one MPCS episode and capture the facts needed for a stage replay."""

from __future__ import annotations

from dataclasses import replace
from math import ceil, fsum
from pathlib import Path
from typing import Any

from mpcs.config import DatasetSplit
from mpcs.core.Domain import ParcelAction, ParcelDecision, PlatformActionBatch
from mpcs.core.Framework import Environment
from mpcs.core.LocalMatching import build_local_matchers
from mpcs.data.Adapters import prepare_environment_split
from mpcs.experiments.Runner import builtin_algorithms, builtin_cross_mechanisms
from mpcs.experiments.Presets import dataset_preset


STAGES = ("workload", "parcel", "local", "auction", "settlement")
POLICIES = ("local-first", "release-first", "wait-first", "localsum", "rl-capa", "mra", "impgta", "fed-ltd")
MECHANISMS = ("paper", "regional-fixed", "pool-random")
MATCHERS = ("greedy", "km")


def build_config(settings: dict[str, Any]):
    """Apply the controls that affect this demo to a validated MPCS preset."""
    dataset = settings["dataset"]
    platforms = int(settings["platforms"])
    config = dataset_preset(
        dataset,
        output_root=Path("output/maps-demo").resolve(),
        platform_count=platforms if dataset == "synthetic" else None,
    )
    step_size = int(settings["step_size_s"])
    if dataset == "synthetic":
        config = replace(
            config,
            dataset=replace(
                config.dataset,
                pickup_count_per_platform=int(settings["pickups_per_platform"]),
                dropoff_count_per_platform=int(settings["dropoffs_per_platform"]),
            ),
            ev=replace(
                config.ev,
                vehicles_per_platform=int(settings["vehicles_per_platform"]),
                service_radius_km=float(settings.get("service_radius_km", config.ev.service_radius_km)),
            ),
            parcel=replace(
                config.parcel,
                pickup_deadline_min_s=int(settings.get("deadline_s", config.parcel.pickup_deadline_min_s)),
                pickup_deadline_max_s=int(settings.get("deadline_s", config.parcel.pickup_deadline_max_s)),
            ),
        )
    config = replace(
        config,
        master_seed=int(settings["seed"]),
        auction=replace(
            config.auction,
            sharing_rate=float(settings.get("sharing_rate", config.auction.sharing_rate)),
        ),
        simulation=replace(config.simulation, step_size_s=step_size, cpu_workers=1),
        training=replace(
            config.training,
            max_steps_per_episode=ceil(
                (config.simulation.end_time_s - config.simulation.start_time_s) / step_size
            ),
        ),
    )
    config.validate()
    return config


def _point(point: Any) -> list[float]:
    return [float(point.longitude_deg), float(point.latitude_deg)]


def _world_snapshot(environment: Environment) -> dict[str, Any]:
    # The demo is a trusted spectator of the single local simulation.
    world = environment._world
    assert world is not None
    return {
        "parcels": {
            parcel_id: {
                "status": lifecycle.status.value,
                "serving_platform": lifecycle.serving_platform_id,
                "vehicle_id": lifecycle.vehicle_id,
            }
            for parcel_id, lifecycle in world.lifecycles_by_parcel_id.items()
            if world.parcels_by_id[parcel_id].parcel_type.value == "pickup"
        },
        "vehicles": {
            vehicle_id: {
                "platform": vehicle.platform_id,
                "point": _point(vehicle.current_location),
                "status": vehicle.status.value,
                "load": vehicle.load_count,
                "capacity": vehicle.max_capacity,
                "route": [stop.road_node_id for stop in vehicle.route_stops],
            }
            for vehicle_id, vehicle in world.vehicles_by_id.items()
        },
    }


class _RecordingPlanning:
    def __init__(self, delegate: Any, trace: dict[str, Any]):
        self.delegate = delegate
        self.trace = trace
        self.platform_id = delegate.platform_id

    def _capture(self, options: Any) -> Any:
        for option in options:
            self.trace["local_options"].append({
                "parcel_id": option.parcel_id,
                "vehicle_id": option.vehicle_id,
                "extra_km": float(option.extra_distance_km),
                "eta_s": float(option.projected_pickup_time_s),
            })
        return options

    def feasible_insertions(self, parcel: Any, state: Any) -> Any:
        return self._capture(self.delegate.feasible_insertions(parcel, state))

    def all_feasible_insertions(self, parcel: Any, state: Any) -> Any:
        return self._capture(self.delegate.all_feasible_insertions(parcel, state))


class _RecordingMatcher:
    def __init__(self, delegate: Any, trace: dict[str, Any]):
        self.delegate = delegate
        self.trace = trace
        self.platform_id = delegate.platform_id

    def plan(self, actions: Any, state: Any, planning: Any) -> Any:
        proposals = self.delegate.plan(actions, state, _RecordingPlanning(planning, self.trace))
        for proposal in proposals:
            self.trace["local_matches"].append({
                "parcel_id": proposal.parcel_id,
                "platform": proposal.platform_id,
                "vehicle_id": proposal.vehicle_id,
                "extra_km": float(proposal.insertion.extra_distance_km),
                "eta_s": float(proposal.insertion.projected_pickup_time_s),
            })
        return proposals


class _RecordingSanitizer:
    def __init__(self, delegate: Any, trace: dict[str, Any]):
        self.delegate = delegate
        self.trace = trace
        self.platform_id = delegate.platform_id

    def sanitize(self, view: Any) -> Any:
        descriptors = self.delegate.sanitize(view)
        if descriptors:
            self.trace["tokens"][descriptors[0].parcel_token] = view.parcels[0].parcel_id
        return descriptors


class _RecordingBidder:
    def __init__(self, delegate: Any, trace: dict[str, Any]):
        self.delegate = delegate
        self.trace = trace
        self.platform_id = delegate.platform_id

    def build_intents(self, snapshot: Any, state: Any) -> Any:
        bundles = self.delegate.build_intents(snapshot, state)
        for bundle in bundles:
            self.trace["intent_candidates"].append({
                "token": bundle.server_payload.parcel_token,
                "platform": bundle.server_payload.bidder_platform_id,
                "vehicle_ids": list(bundle.private_receipt.private_candidate_vehicle_ids),
            })
        return bundles


class _RecordingAuctioneer:
    def __init__(self, delegate: Any, trace: dict[str, Any]):
        self.delegate = delegate
        self.trace = trace

    def settle(self, lots: Any, intents: Any, quality: Any) -> Any:
        awards = self.delegate.settle(lots, intents, quality)
        for intent in intents:
            bid = intent.server_payload
            self.trace["valid_bids"].append({
                "token": bid.parcel_token,
                "platform": bid.bidder_platform_id,
                "amount": float(bid.frozen_offer_amount),
            })
        for award in awards:
            self.trace["awards"].append({
                "token": award.parcel_token,
                "winner": award.winner_platform_id,
                "winner_bid": float(award.winner_bid_amount),
                "payment": float(award.payment_amount),
                "valid_bidder_count": award.valid_bidder_count,
            })
        return awards


def _empty_trace() -> dict[str, Any]:
    return {
        "local_options": [], "local_matches": [], "tokens": {},
        "intent_candidates": [], "valid_bids": [], "awards": [],
    }


def _trace_for_frame(trace: dict[str, Any], result: Any) -> dict[str, Any]:
    tokens = trace["tokens"]
    details: dict[str, dict[str, Any]] = {}
    for name in ("local_options", "local_matches", "intent_candidates", "valid_bids", "awards"):
        for entry in trace[name]:
            parcel_id = entry.get("parcel_id") or tokens.get(entry.get("token"))
            if parcel_id is None:
                continue
            value = {key: item for key, item in entry.items() if key != "token"}
            details.setdefault(parcel_id, {}).setdefault(name, []).append(value)
    for platform_result in result.platform_results.values():
        for outcome in platform_result.decision_outcomes:
            details.setdefault(outcome.parcel_id, {})["outcome"] = outcome.outcome_code.value
        for receipt in platform_result.origin_assignment_receipts:
            details.setdefault(receipt.parcel_id, {})["origin_receipt"] = {
                "utility": float(receipt.origin_utility_amount),
                "payment": None if receipt.cooperation_fee_amount is None else float(receipt.cooperation_fee_amount),
                "assignment_id": receipt.assignment_id,
            }
        for item in platform_result.item_economic_attributions:
            details.setdefault(item.parcel_id, {})["item_utility"] = float(item.raw_item_economic_reward_amount)
    return details


def _catalog(prepared: Any) -> dict[str, dict[str, Any]]:
    catalog = {}
    for platform_id, dataset in prepared.task_partition.datasets.items():
        for number, parcel in enumerate(dataset.pickup_parcels, start=1):
            catalog[parcel.parcel_id] = {
                "label": f"{platform_id} · #{number:02d}",
                "origin": parcel.origin_platform_id,
                "point": _point(parcel.location),
                "arrival_s": parcel.arrival_time_s,
                "deadline_s": parcel.deadline_s,
                "fare": float(parcel.fare_amount),
                "region": parcel.region_id,
            }
    return catalog


def _simple_action(name: str) -> ParcelAction:
    return {
        "local-first": ParcelAction.LOCAL,
        "release-first": ParcelAction.RELEASE,
        "wait-first": ParcelAction.WAIT,
    }[name]


def run_demo(settings: dict[str, Any]) -> dict[str, Any]:
    """Compute one complete held-out episode and serialize its actual process."""
    if settings["mechanism"] not in MECHANISMS or settings["matcher"] not in MATCHERS:
        raise ValueError("Unknown matching or auction mechanism")
    config = build_config(settings)
    policies = {platform: settings["policies"][platform] for platform in config.platform_ids}
    if any(policy not in POLICIES for policy in policies.values()):
        raise ValueError("Unknown platform policy")
    seed = int(settings["seed"])
    prepared = prepare_environment_split(config, DatasetSplit.TEST)
    environment = None
    try:
        catalog = _catalog(prepared)
        sessions = {}
        registry = builtin_algorithms()
        for policy in set(policies.values()) - {"local-first", "release-first", "wait-first"}:
            sessions[policy] = registry.create_pool_policy(policy, config, prepared, seed)
        trace = _empty_trace()
        kwargs = dict(builtin_cross_mechanisms()[settings["mechanism"]](config, prepared, seed))
        kwargs["local_matchers"] = {
            platform: _RecordingMatcher(matcher, trace)
            for platform, matcher in build_local_matchers(config.platform_ids, settings["matcher"]).items()
        }
        kwargs["release_sanitizers"] = {
            platform: _RecordingSanitizer(sanitizer, trace)
            for platform, sanitizer in kwargs["release_sanitizers"].items()
        }
        kwargs["cross_bidders"] = {
            platform: _RecordingBidder(bidder, trace)
            for platform, bidder in kwargs["cross_bidders"].items()
        }
        kwargs["auctioneer"] = _RecordingAuctioneer(kwargs["auctioneer"], trace)
        environment = Environment.from_prepared(config=config, prepared=prepared, **kwargs)
        observations = environment.reset(seed)
        steps: list[dict[str, Any]] = []
        batches: list[dict[str, Any]] = []
        batch = 0
        while not environment.done:
            batch += 1
            before = _world_snapshot(environment)
            decision_time = environment.current_time_s
            for value in trace.values():
                value.clear()
            actions = {}
            for platform in config.platform_ids:
                policy = policies[platform]
                if policy in sessions:
                    actions[platform] = sessions[policy].decide(platform, observations[platform], config)
                else:
                    action = _simple_action(policy)
                    actions[platform] = PlatformActionBatch(
                        frame=observations[platform].frame,
                        platform_id=platform,
                        decisions=tuple(
                            ParcelDecision(parcel_id=parcel.parcel_id, action=action)
                            for parcel in observations[platform].waiting_pickups
                        ),
                    )
            decisions = {
                decision.parcel_id: decision.action.name
                for action_batch in actions.values()
                for decision in action_batch.decisions
            }
            result = environment.step(actions)
            after = _world_snapshot(environment)
            metrics = environment.metrics
            progress = environment.pickup_progress_snapshot
            details = _trace_for_frame(trace, result)
            for platform_result in result.platform_results.values():
                for receipt in platform_result.serving_assignment_receipts:
                    for parcel_id, item in details.items():
                        origin = item.get("origin_receipt")
                        if origin and origin["assignment_id"] == receipt.assignment_id:
                            item["serving_receipt"] = {
                                "platform": receipt.serving_platform_id,
                                "vehicle_id": receipt.vehicle_id,
                                "utility": float(receipt.winner_utility_amount),
                                "payment": float(receipt.cooperation_fee_amount),
                            }
            totals = {key: float(value) for key, value in metrics.ledger_totals_by_platform.items()}
            record = {
                "batch": batch,
                "decision_time_s": decision_time,
                "time_s": environment.current_time_s,
                "waiting": progress.waiting,
                "assigned": progress.assigned,
                "expired": progress.expired,
                "total": progress.total,
                "collected": metrics.pickup_collected_count,
                "unloaded": metrics.pickup_unloaded_count,
                "local_count": metrics.local_assignment_count,
                "cross_count": metrics.cross_assignment_count,
                "profit": fsum(totals.values()),
                "profit_by_platform": totals,
            }
            batches.append(record)
            for stage in STAGES:
                steps.append({
                    "index": len(steps), "batch": batch, "stage": stage,
                    "decision_time_s": decision_time, "time_s": record["time_s"],
                    "state": after if stage == "settlement" else before,
                    "decisions": decisions,
                    "details": details,
                    "metrics": record if stage == "settlement" else (batches[-2] if len(batches) > 1 else {
                        **record, "assigned": 0, "expired": 0, "collected": 0,
                        "unloaded": 0, "local_count": 0, "cross_count": 0,
                        "profit": 0.0, "profit_by_platform": {p: 0.0 for p in config.platform_ids},
                    }),
                })
            observations = result.next_platform_observations
        final = batches[-1]
        return {
            "meta": {
                "dataset": settings["dataset"], "split": "test", "seed": seed,
                "platforms": list(config.platform_ids), "policies": policies,
                "matcher": settings["matcher"], "mechanism": settings["mechanism"],
                "settings": settings, "source": "computed",
            },
            "catalog": catalog, "steps": steps, "batches": batches,
            "summary": {
                **final,
                "assignment_rate": final["assigned"] / final["total"] if final["total"] else 0.0,
                "ledger_breakdown": {
                    platform: breakdown.to_dict()
                    for platform, breakdown in metrics.platform_profit_breakdowns.items()
                },
            },
        }
    finally:
        if environment is not None:
            environment.close()
        prepared.road_network.close()
