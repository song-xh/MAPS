# MAPS system demo design

## Purpose

MAPS is a local interactive demonstration of the existing `mpcs` simulator for the PVLDB Demonstrations Track. A visitor selects a workload, platform order dates, a time window, fleet settings, a target platform and one or more target algorithms. Each episode replays the target platform's batch through **workload → parcel → local decision → auction → settlement**. Analysis ends at the selected arrival window even when the simulator continues through pickup deadlines.

## Simulation contract

- One selected real city supplies the processed operational road network. Each platform uses a distinct order date from that city. Counts displayed and sampled refer to parsed, deduplicated orders within the operational area.
- The simulator advances beyond the arrival window to the latest pickup deadline. Analysis uses the last frame inside the arrival window for assignment and ledger charts.
- The interface exposes dataset, train/validation/test split, platform dates, pickup and dropoff count or all eligible orders, time window, fleet size, service radius, deadline, frame interval, seed, target platform and algorithm selection. Single and comparison modes share these controls.
- Every algorithm runs only on the selected target platform. Other platforms submit `LOCAL` for all of their own waiting pickups and never release. Local settlement precedes cross-platform bidding, so partners offer feasible capacity after their own work. The target platform does not serve partner-origin parcels.
- Comparison runs reconstruct the same sampled orders and initial courier fleet with the same seed for each selected algorithm. RL-CAPA, ImpGTA, MRA, Greedy and RamCOM are selectable. Each algorithm handles the orders available at a batch boundary; Greedy tries local matches once in descending fare order and releases unmatched orders. The partner policy is fixed across comparisons.
- For `rl-capa`, the local matcher follows the current CAMA reference: feasible local pairs contribute `(1 − ζ) × fare` to a cumulative mean; the dynamic release threshold is `ω` times that mean. The reference defaults are `ζ = 0.2` and `ω = 0.7`.
- An RL-CAPA parcel below the dynamic threshold releases immediately. A threshold-eligible parcel without a feasible local courier waits for five checks and releases on the sixth. For each eligible parcel in descending revenue order, local matching chooses the feasible insertion with minimum additional route distance. Updated routes may accept further parcels in the same batch; settlement follows their route versions.
- For each released primary parcel, every partner with a route-feasible courier submits its lowest internal FPSA courier bid. The courier bid uses a 0.5 base payment. The platform adds its quality-adjusted `μ₂ × fare` markup; bids above `(μ₁ + μ₂) × fare` are invalid. Lowest valid platform bid wins. Payment is the smaller of `μ₂ × fare` and the second-lowest valid bid, or the sole valid bid when unopposed. The primary platform never bids for another platform's parcel. Here `μ₁ = 0.3`; the existing cooperation sharing control supplies both the FPSA platform sharing rate and `μ₂`.
- Unmatched cross-pool parcels enter the auction again at every batch boundary until they are assigned or expire.
- The `rl-capa` option is the MAPS baseline with CAMA and DAPA decisions. It does not load or infer the reference repository's actor-critic policy.
- RamCOM samples a value threshold, chooses a random feasible local insertion for qualifying parcels, and uses reservation-based expected-revenue payment with sampled partner acceptance for released parcels. MPCS permits one bid per partner platform per lot, so the platform offers its shortest-detour feasible courier as its candidate.
- Fixed city presets use P1, four distinct `Test` source dates, all valid pickup and dropoff orders, five algorithms, 20-second batches, and a 720-second pickup deadline. Chengdu uses 08:00–09:00 with 300 couriers per platform; Shanghai uses 09:00–10:00 with 100 couriers per platform. Preset settings are locked in the interface.

## Inspection contract

The algorithm selector and timeline control Inspection playback. The five-stage strip marks the current process stage. The batch table shows each target parcel's identifier, status, pool action, local match and cross match. A waiting RL-CAPA parcel shows its consecutive failed local checks. The local candidate table exposes actual feasible couriers, route insertion distance and ETA; RL-CAPA adds revenue score and dynamic threshold. The auction lists each new or repeated cross-pool attempt, partner intents, bids, result and payment. The settlement stage shows committed target origin utility and cross payment.

The map draws the full processed network scale and station nodes. It plots only target parcels that are still waiting or in the cross pool. All platforms' courier points remain visible and advance along shortest-path nodes according to the active leg's remaining distance; a solid line follows each current navigation path. Dashed connectors show target local or cross match relations. Platform colors and a target outline distinguish ownership. Scroll zoom, pan and reset remain available.

The target platform archive shows pending counts, this-frame local and release decisions, cumulative matches, target ledger profit and its local, cross and dropoff components. English labels and HH:MM timestamps are used throughout.

## Analysis and replay

Cumulative and one-minute target ledger profit use the same window cutoff, so minute deltas sum to the displayed OP. Both are line charts, with one series per algorithm in comparison mode. AR is target-origin assignments divided by target-origin pickups at the cutoff. BPT is the mean target decision time over nonempty target batches, including target policy, target local matching, partner bidding and auction settlement, excluding courier movement; the interface displays milliseconds. Analysis compares OP, AR and BPT in charts and a table. The target-origin-to-serving chart uses simulator assignments. Custom runs save a local JSON replay. Fixed presets save shared geography and catalog once, per-algorithm metrics, and compressed batch chunks for complete lazy playback.

## Implementation

`maps_demo/app.py` owns Dash controls and playback. `engine.py` records target batch decisions, world snapshots and receipts from `Environment`. `presets.py` generates fixed runs and reads their batch chunks. `capa.py` computes FPSA bids and DAPA awards; `ramcom.py` adapts the RamCOM threshold, local random choice and expected-revenue cooperation rule. `geography.py` exports the complete processed road network and stations. `figures.py` renders maps and analysis charts. The demo uses the local Python process, with no login or external service.
