# MAPS system demo design

## Purpose

MAPS is a local interactive demonstration of the existing `mpcs` simulator for the PVLDB Demonstrations Track. A visitor selects a workload, platform order dates, a time window, fleet settings and decision policies, runs an episode, and replays each physical frame through **workload → parcel → local decision → auction → settlement**. Inspection explains the decisions for the whole pending batch. Analysis ends at the selected arrival window even when the simulator continues through pickup deadlines.

## Simulation contract

- One selected real city supplies the processed operational road network. Each platform uses a distinct order date from that city. Counts displayed and sampled refer to parsed, deduplicated orders within the operational area.
- The simulator advances beyond the arrival window to the latest pickup deadline. Analysis uses the last frame inside the arrival window for assignment and ledger charts.
- The interface exposes dataset, train/validation/test split, platform dates, pickup and dropoff count or all eligible orders, time window, fleet size, service radius, deadline, frame interval, seed, policies, local matcher and cross mechanism.
- When the focus platform uses `rl-capa`, it is the **sole primary platform** for that run. Its own local matcher follows the current CAMA reference: feasible local pairs contribute `(1 − ζ) × fare` to a cumulative mean; the dynamic release threshold is `ω` times that mean. The reference defaults are `ζ = 0.2` and `ω = 0.7`. Other platforms retain their own workload and local policy, and provide vehicles for the primary platform's auction.
- For each released primary parcel, every partner with a route-feasible EV submits one FPSA courier bid. The platform adds its quality-adjusted `μ₂ × fare` markup; bids above `(μ₁ + μ₂) × fare` are invalid. Lowest valid platform bid wins. Payment is the second-lowest valid bid, or the sole valid bid when unopposed. The primary platform never bids for another platform's parcel. Here `μ₁ = 0.3`; the existing cooperation sharing control supplies both the FPSA platform sharing rate and `μ₂`.
- The `rl-capa` option is the MAPS baseline with CAMA and DAPA decisions. It does not load or infer the reference repository's actor-critic policy.

## Inspection contract

The five-stage strip and timeline select a batch and process stage. The batch table shows each pending parcel's identifier, origin, status, pool action, local match and cross match. The local candidate table exposes actual feasible EVs, route insertion distance and ETA; RL-CAPA adds revenue score and dynamic threshold. The auction lists every eligible partner intent, courier and platform bids, invalid bids, winner and payment per released parcel. The settlement stage shows committed origin utility and cross payment. In RL-CAPA mode the batch table follows the primary platform's parcels while partner bids remain visible.

The map draws the full processed network scale and station nodes. It plots only parcels that are still waiting or in the cross pool. EV points advance along the shortest-path nodes according to the active leg's remaining distance, and a solid line follows each current navigation path. Dashed connectors show local or cross match relations. Platform colors and a focus outline distinguish ownership. Scroll zoom, pan and reset remain available.

The platform archive shows pending counts, this-frame local and release decisions, cumulative matches, total ledger profit and its local, cross and dropoff components. English labels and HH:MM timestamps are used throughout.

## Analysis and replay

Cumulative and one-minute ledger profit use the same window cutoff, so minute deltas sum to the displayed window total. The assignment, completion, platform profit and origin-to-serving charts come from the simulator's metrics and receipts. The run saves a local JSON replay; loading requires the current batch trace schema.

## Implementation

`maps_demo/app.py` owns Dash controls and playback. `engine.py` records batch decisions, world snapshots and receipts from `Environment`. `capa.py` computes exact-route FPSA bids and DAPA platform awards for the selected primary platform. `geography.py` exports the complete processed road network and stations. `figures.py` renders maps and analysis charts. The demo uses the local Python process, with no login or external service.

The earlier `01–06` documents in this directory describe a prior CAPA two-tab concept. This document describes the implemented MAPS demo.
