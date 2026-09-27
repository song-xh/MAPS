"""Run one MPCS episode and capture the facts needed for a stage replay."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from functools import lru_cache
from math import ceil, fsum, isfinite
from pathlib import Path
from typing import Any

from maps_demo.geography import prepared_geography
from maps_demo.capa import CAPAAuctioneer, CAPABidder, FIRST_LAYER_SHARE
from mpcs.config import DatasetSplit, PlatformSourceFiles
from mpcs.core.Domain import ParcelAction, ParcelDecision, PlatformActionBatch
from mpcs.core.Framework import Environment
from mpcs.core.LocalMatching import build_local_matchers
from mpcs.core.TaskUtils import (
    ParcelType, _claim_seen_id, _disk_seen_ids, _iter_canonical_orders,
    _order_in_region_bounds, read_canonical_orders,
)
from mpcs.data.Adapters import (
    _build_order_station_grid, _load_parcel_road_network, prepare_environment_split,
)
from mpcs.experiments.Presets import dataset_preset
from mpcs.experiments.Runner import builtin_algorithms, builtin_cross_mechanisms

STAGES = ("workload", "parcel", "local", "auction", "settlement")
POLICIES = ("local-first", "release-first", "wait-first", "localsum", "rl-capa", "mra", "impgta", "fed-ltd")
MECHANISMS = ("paper", "regional-fixed", "pool-random")
MATCHERS = ("greedy", "km")


def clock_time(seconds: int | float) -> str:
    minutes = int(seconds) // 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_clock(value: str) -> int:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except (AttributeError, ValueError) as error:
        raise ValueError("Time must use HH:MM") from error
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be within one day")
    return hour * 3600 + minute * 60


def source_options(dataset: str) -> list[str]:
    if dataset == "synthetic":
        return []
    preset = dataset_preset(dataset, output_root=Path("output/maps-demo"))
    return sorted(path.name for path in preset.paths.dataset_root.glob("order_*"))


def _selected_sources(config: Any, split: DatasetSplit, selected: dict[str, str]) -> Any:
    if len(set(selected.values())) != len(selected):
        raise ValueError("Each platform must select a different order date")
    available = set(source_options(config.dataset.name))
    if set(selected) != set(config.platform_ids) or not set(selected.values()) <= available:
        raise ValueError("Select one available order date for every platform")
    used = set(selected.values())
    alternatives = [source for source in source_options(config.dataset.name) if source not in used]
    roles = {}
    for role in DatasetSplit:
        if role is split:
            roles[role] = tuple(selected[platform] for platform in config.platform_ids)
        elif config.dataset.name == "chengdu":
            original = config.dataset.source_files_for(role)
            free = [source for source in original if source not in used]
            free += [source for source in alternatives if source not in free]
            roles[role] = tuple(free[:len(config.platform_ids)])
            used.update(roles[role])
            alternatives = [source for source in alternatives if source not in used]
        else:
            roles[role] = tuple(f"unused-{role.value}-{index}" for index in range(1, len(config.platform_ids) + 1))
    mappings = tuple(PlatformSourceFiles(
        platform_id=platform,
        train_source_files=(roles[DatasetSplit.TRAIN][index],),
        validation_source_files=(roles[DatasetSplit.VALIDATION][index],),
        test_source_files=(roles[DatasetSplit.TEST][index],),
    ) for index, platform in enumerate(config.platform_ids))
    return replace(
        config.dataset,
        train_source_files=roles[DatasetSplit.TRAIN],
        validation_source_files=roles[DatasetSplit.VALIDATION],
        test_source_files=roles[DatasetSplit.TEST],
        platform_source_files=mappings,
    )


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
    split = DatasetSplit(settings.get("split", "test"))
    start = parse_clock(settings["window_start"]) if "window_start" in settings else config.dataset.arrival_window_start_s
    end = parse_clock(settings["window_end"]) if "window_end" in settings else config.dataset.arrival_window_end_s
    if start >= end:
        raise ValueError("Arrival window end must follow its start")
    deadline = int(settings.get("deadline_s", config.parcel.pickup_deadline_min_s))
    dataset_config = config.dataset
    if dataset != "synthetic" and settings.get("sources"):
        dataset_config = _selected_sources(config, split, settings["sources"])
    pickups = settings.get("pickups_per_platform", 3)
    dropoffs = settings.get("dropoffs_per_platform", 1)
    if pickups == "all" or dropoffs == "all":
        counts = available_orders(settings)
        if pickups == "all":
            pickup_counts = tuple(counts[p]["pickup"] for p in config.platform_ids)
            pickups = 0
        else:
            pickup_counts = None
        if dropoffs == "all":
            dropoff_counts = tuple(counts[p]["dropoff"] for p in config.platform_ids)
            dropoffs = 0
        else:
            dropoff_counts = None
    else:
        pickup_counts = dropoff_counts = None
    config = replace(
        config,
        dataset=replace(
            dataset_config,
            pickup_count_per_platform=int(pickups),
            dropoff_count_per_platform=int(dropoffs),
            pickup_counts_per_platform=pickup_counts,
            dropoff_counts_per_platform=dropoff_counts,
            arrival_window_start_s=start,
            arrival_window_end_s=end,
        ),
        ev=replace(
            config.ev,
            vehicles_per_platform=int(settings["vehicles_per_platform"]),
            service_radius_km=float(settings.get("service_radius_km", config.ev.service_radius_km)),
        ),
        parcel=replace(
            config.parcel,
            pickup_deadline_min_s=deadline,
            pickup_deadline_max_s=deadline,
        ),
        master_seed=int(settings["seed"]),
        auction=replace(
            config.auction,
            sharing_rate=float(settings.get("sharing_rate", config.auction.sharing_rate)),
        ),
        simulation=replace(config.simulation, start_time_s=start, end_time_s=end + deadline,
                           step_size_s=step_size, cpu_workers=1),
        training=replace(
            config.training,
            max_steps_per_episode=ceil((end + deadline - start) / step_size),
        ),
    )
    config.validate()
    return config


@lru_cache(maxsize=3)
def _count_region(dataset: str):
    config = dataset_preset(dataset, output_root=Path("output/maps-demo"))
    road, _ = _load_parcel_road_network(config, road_artifact_dir=None)
    try:
        reference = read_canonical_orders(
            (config.paths.dataset_root / config.stations.reference_source_file,),
            replace(config.dataset, arrival_window_start_s=0, arrival_window_end_s=86400),
        )
        points = tuple(point for order in reference for point in (order.pickup_location, order.dropoff_location))
        region, _, _ = _build_order_station_grid(config, road, points)
        return region
    finally:
        road.close()


@lru_cache(maxsize=16)
def _available_real(dataset: str, split_name: str, names: tuple[str, ...], start: int, end: int):
    config = dataset_preset(dataset, output_root=Path("output/maps-demo"))
    region = _count_region(dataset)
    window = replace(config.dataset, arrival_window_start_s=start, arrival_window_end_s=end)
    result = {}
    with _disk_seen_ids() as seen:
        for index, source in enumerate(names, start=1):
            counts = {"pickup": 0, "dropoff": 0}
            for order in _iter_canonical_orders((config.paths.dataset_root / source,), window):
                if not _claim_seen_id(seen, "semantic_ids", order.semantic_order_id):
                    continue
                if not _claim_seen_id(seen, "canonical_ids", order.canonical_order_id):
                    continue
                if not _order_in_region_bounds(order, region):
                    continue
                for parcel_type in ParcelType:
                    if order.parcel_type is None or order.parcel_type is parcel_type:
                        counts[parcel_type.value] += 1
            result[f"P{index}"] = counts
    return result


def available_orders(settings: dict[str, Any]) -> dict[str, dict[str, int]]:
    dataset = settings["dataset"]
    platforms = [f"P{i}" for i in range(1, int(settings["platforms"]) + 1)]
    if dataset == "synthetic":
        return {p: {"pickup": int(settings["pickups_per_platform"]),
                    "dropoff": int(settings["dropoffs_per_platform"])} for p in platforms}
    config = dataset_preset(dataset, output_root=Path("output/maps-demo"))
    split = DatasetSplit(settings.get("split", "test"))
    sources = settings.get("sources") or {
        p: config.dataset.source_files_for_platform(p, split)[0] for p in platforms
    }
    _selected_sources(config, split, sources)
    names = tuple(sources[p] for p in platforms)
    start = parse_clock(settings["window_start"])
    end = parse_clock(settings["window_end"])
    if start >= end:
        raise ValueError("Arrival window end must follow its start")
    return _available_real(dataset, split.value, names, start, end)


def _point(point: Any) -> list[float]:
    return [float(point.longitude_deg), float(point.latitude_deg)]


def _vehicle_display(vehicle: Any, road: Any, path_cache: dict) -> tuple[list[float], list[list[float]]]:
    def path(start: str, end: str) -> tuple[list[list[float]], list[float]]:
        key = (start, end)
        if key not in path_cache:
            nodes = road.shortest_path(start, end) or (start,)
            path_cache[key] = (
                [_point(road.location(node)) for node in nodes],
                [road.shortest_distance_m(left, right) for left, right in zip(nodes, nodes[1:])],
            )
        return path_cache[key]

    stops = [stop.road_node_id for stop in vehicle.route_stops]
    if not stops:
        return _point(vehicle.current_location), []
    segment, edge_lengths = path(vehicle.current_road_node_id, stops[0])
    if vehicle.active_leg_target_stop_id is None:
        point = _point(vehicle.current_location)
        remaining = segment
    else:
        progress_m = max(0.0, road.shortest_distance_m(vehicle.current_road_node_id, stops[0])
                         - vehicle.active_leg_remaining_distance_km * 1000.0)
        remaining = segment
        point = segment[0]
        for index, edge_m in enumerate(edge_lengths):
            start, end = segment[index:index + 2]
            if progress_m <= edge_m or index == len(segment) - 2:
                fraction = min(1.0, max(0.0, progress_m / edge_m)) if edge_m else 0.0
                point = [start[0] + (end[0] - start[0]) * fraction,
                         start[1] + (end[1] - start[1]) * fraction]
                remaining = [point, *segment[index + 1:]]
                break
            progress_m -= edge_m
    navigation = list(remaining)
    for start, end in zip(stops, stops[1:]):
        navigation.extend(path(start, end)[0][1:])
    return point, navigation


def _world_snapshot(environment: Environment, road: Any, path_cache: dict) -> dict[str, Any]:
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
                "point": display[0], "navigation": display[1],
                "status": vehicle.status.value,
                "load": vehicle.load_count,
                "capacity": vehicle.max_capacity,
                "route": [stop.road_node_id for stop in vehicle.route_stops],
            }
            for vehicle_id, vehicle in world.vehicles_by_id.items()
            for display in (_vehicle_display(vehicle, road, path_cache),)
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
        if hasattr(self.delegate, "last_bids"):
            self.trace["platform_bids"].extend(self.delegate.last_bids)
            self.trace["valid_bids"].extend(
                bid for bid in self.delegate.last_bids if bid["valid"]
            )
        else:
            for intent in intents:
                bid = intent.server_payload
                self.trace["valid_bids"].append({
                    "token": bid.parcel_token,
                    "platform": bid.bidder_platform_id,
                    "amount": float(bid.frozen_offer_amount), "valid": True,
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
        "intent_candidates": [], "platform_bids": [], "valid_bids": [], "awards": [],
    }


def _trace_for_frame(trace: dict[str, Any], result: Any) -> dict[str, Any]:
    tokens = trace["tokens"]
    details: dict[str, dict[str, Any]] = {}
    for name in ("local_options", "local_matches", "intent_candidates", "platform_bids", "valid_bids", "awards"):
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


class _DemoStageReporter:
    def __init__(self, notify):
        self.notify = notify
        self.completed = 0

    @contextmanager
    def stage(self, stage_id: str, **_details):
        labels = {
            "graph_load": "Loading road network", "region_build": "Building station grid",
            "station_build": "Preparing stations", "dataset_parse": "Sampling orders",
            "platform_partition": "Building parcels", "fleet_init": "Initializing vehicles",
        }
        self.notify(min(58, self.completed * 10), labels.get(stage_id, stage_id))
        facts = {}
        yield facts
        self.completed += 1
        self.notify(min(60, self.completed * 10), labels.get(stage_id, stage_id) + " complete")


def run_demo(settings: dict[str, Any], progress=None) -> dict[str, Any]:
    """Compute one selected episode and serialize its actual process."""
    if settings["mechanism"] not in MECHANISMS or settings["matcher"] not in MATCHERS:
        raise ValueError("Unknown matching or auction mechanism")
    config = build_config(settings)
    policies = {platform: settings["policies"][platform] for platform in config.platform_ids}
    if any(policy not in POLICIES for policy in policies.values()):
        raise ValueError("Unknown platform policy")
    primary = settings.get("primary_platform", config.platform_ids[0])
    capa_platforms = [platform for platform, policy in policies.items() if policy == "rl-capa"]
    if capa_platforms and capa_platforms != [primary]:
        raise ValueError("Select exactly one RL-CAPA policy on the focus platform")
    if capa_platforms and config.auction.sharing_rate > 1.0 - FIRST_LAYER_SHARE:
        raise ValueError("DAPA requires cooperation sharing rate ≤ 0.7 (μ1 = 0.3)")
    seed = int(settings["seed"])
    split = DatasetSplit(settings.get("split", "test"))
    if progress:
        progress(0, "Preparing scenario")
    prepared = prepare_environment_split(
        config, split, stage_reporter=_DemoStageReporter(progress) if progress else None,
        station_reference_source_file=(config.stations.reference_source_file
                                       if settings["dataset"] != "synthetic" else None),
    )
    environment = None
    try:
        catalog = _catalog(prepared)
        geography = prepared_geography(prepared)
        sessions = {}
        registry = builtin_algorithms()
        for policy in set(policies.values()) - {"local-first", "release-first", "wait-first"}:
            sessions[policy] = registry.create_pool_policy(policy, config, prepared, seed)
        trace = _empty_trace()
        kwargs = dict(builtin_cross_mechanisms()[settings["mechanism"]](config, prepared, seed))
        matchers = dict(build_local_matchers(config.platform_ids, settings["matcher"]))
        for platform, policy in policies.items():
            if policy == "rl-capa":
                matchers[platform] = sessions[policy].local_matchers[platform]
        kwargs["local_matchers"] = {
            platform: _RecordingMatcher(matcher, trace) for platform, matcher in matchers.items()
        }
        kwargs["release_sanitizers"] = {
            platform: _RecordingSanitizer(sanitizer, trace)
            for platform, sanitizer in kwargs["release_sanitizers"].items()
        }
        primary = settings.get("primary_platform", config.platform_ids[0])
        capa = policies[primary] == "rl-capa"
        if capa:
            parcels = {
                parcel.parcel_id: parcel
                for dataset in prepared.task_partition.datasets.values()
                for parcel in dataset.pickup_parcels
            }
            kwargs["cross_bidders"] = {
                platform: CAPABidder(platform, primary, parcels, trace["tokens"],
                                     prepared.road_network, prepared.station_index,
                                     config.auction.sharing_rate)
                for platform in config.platform_ids
            }
            kwargs["auctioneer"] = CAPAAuctioneer(config.auction.sharing_rate, config.platform_ids)
        kwargs["cross_bidders"] = {
            platform: _RecordingBidder(bidder, trace)
            for platform, bidder in kwargs["cross_bidders"].items()
        }
        kwargs["auctioneer"] = _RecordingAuctioneer(kwargs["auctioneer"], trace)
        environment = Environment.from_prepared(config=config, prepared=prepared, **kwargs)
        observations = environment.reset(seed)
        path_cache = {}
        frame_total = ceil((config.simulation.end_time_s - config.simulation.start_time_s) / config.simulation.step_size_s)
        steps: list[dict[str, Any]] = []
        batches: list[dict[str, Any]] = []
        batch = 0
        while not environment.done:
            batch += 1
            before = _world_snapshot(environment, prepared.road_network, path_cache)
            decision_time = environment.current_time_s
            batch_parcels = [pid for pid, state in before["parcels"].items()
                             if state["status"] in {"waiting", "cross_pool", "public_this_step"}]
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
            thresholds = {}
            for platform, policy in policies.items():
                if policy == "rl-capa":
                    algorithm = sessions[policy].policies[platform]._algorithm
                    trace["local_options"].extend(algorithm.last_candidate_pairs)
                    thresholds[platform] = (algorithm.last_threshold
                                            if isfinite(algorithm.last_threshold) else None)
            result = environment.step(actions)
            after = _world_snapshot(environment, prepared.road_network, path_cache)
            metrics = environment.metrics
            pickup_progress = environment.pickup_progress_snapshot
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
            breakdowns = {p: value.to_dict() for p, value in metrics.platform_profit_breakdowns.items()}
            platform_archive = {}
            for platform in config.platform_ids:
                own = [state for pid, state in after["parcels"].items()
                       if catalog[pid]["origin"] == platform]
                matched = [state for state in own if state["serving_platform"]]
                ledger = breakdowns[platform]
                platform_archive[platform] = {
                    "pending": sum(state["status"] == "waiting" for state in own),
                    "local_processed": sum(value == "LOCAL" for pid, value in decisions.items()
                                           if catalog[pid]["origin"] == platform),
                    "cross_processed": sum(value == "RELEASE" for pid, value in decisions.items()
                                           if catalog[pid]["origin"] == platform),
                    "matched": len(matched),
                    "local_matched": sum(state["serving_platform"] == platform for state in matched),
                    "cross_matched": sum(state["serving_platform"] != platform for state in matched),
                    "profit": totals[platform],
                    "local_profit": ledger["local_utility_amount"],
                    "cross_profit": ledger["origin_cross_utility_amount"] + ledger["serving_cross_utility_amount"],
                    "dropoff_profit": ledger["dropoff_operational_utility_amount"],
                }
            record = {
                "batch": batch,
                "decision_time_s": decision_time,
                "time_s": environment.current_time_s,
                "waiting": pickup_progress.waiting,
                "assigned": pickup_progress.assigned,
                "expired": pickup_progress.expired,
                "total": pickup_progress.total,
                "collected": metrics.pickup_collected_count,
                "unloaded": metrics.pickup_unloaded_count,
                "local_count": metrics.local_assignment_count,
                "cross_count": metrics.cross_assignment_count,
                "profit": fsum(totals.values()),
                "profit_by_platform": totals,
                "platform_archive": platform_archive,
                "ledger_breakdown_by_platform": breakdowns,
            }
            batches.append(record)
            for stage in STAGES:
                steps.append({
                    "index": len(steps), "batch": batch, "stage": stage,
                    "decision_time_s": decision_time, "time_s": record["time_s"],
                    "state": after if stage == "settlement" else before,
                    "batch_parcels": batch_parcels,
                    "thresholds": thresholds,
                    "decisions": decisions,
                    "details": details,
                    "metrics": record if stage == "settlement" else (batches[-2] if len(batches) > 1 else {
                        **record, "assigned": 0, "expired": 0, "collected": 0,
                        "unloaded": 0, "local_count": 0, "cross_count": 0,
                        "profit": 0.0, "profit_by_platform": {p: 0.0 for p in config.platform_ids},
                            "platform_archive": {p: {
                                "local_profit": 0.0, "cross_profit": 0.0, "dropoff_profit": 0.0,
                            } for p in config.platform_ids},
                    }),
                })
            observations = result.next_platform_observations
            if progress:
                progress(60 + 35 * min(batch, frame_total) / frame_total,
                         f"Simulating frame {batch} / {frame_total}")
        analysis_batches = [item for item in batches if item["decision_time_s"] < config.dataset.arrival_window_end_s]
        final = analysis_batches[-1]
        analysis_step = next(step for step in reversed(steps)
                             if step["stage"] == "settlement" and step["batch"] == final["batch"])
        if progress:
            progress(98, "Preparing replay")
        return {
            "meta": {
                "dataset": settings["dataset"], "split": split.value, "seed": seed,
                "analysis_end_s": config.dataset.arrival_window_end_s,
                "platforms": list(config.platform_ids), "policies": policies,
                "matcher": settings["matcher"],
                "mechanism": "dapa" if capa else settings["mechanism"],
                "primary_platform": primary,
                "settings": settings, "source": "computed",
            },
            "catalog": catalog, "geography": geography, "steps": steps, "batches": batches,
            "summary": {
                **final,
                "assignment_rate": final["assigned"] / final["total"] if final["total"] else 0.0,
                "ledger_breakdown": final["ledger_breakdown_by_platform"],
                "flow_step_index": analysis_step["index"],
            },
        }
    finally:
        if environment is not None:
            environment.close()
        prepared.road_network.close()
