# Target-platform algorithms in the MAPS demo

Status: Accepted

## Context

MPCS advances all platforms on one physical clock. MAPS compares parcel-assignment methods for one selected origin platform while cooperating platforms retain their own work and offer spare courier capacity.

## Decision

The selected target platform alone runs the selected algorithm and may release its parcels. Every partner submits `LOCAL` for its own waiting pickups. The environment commits all local assignments before collecting cross-platform bids. The target platform never bids for a partner parcel. Each comparison run reconstructs the same workload and initial courier fleet from the same dataset selection and seed.

RL-CAPA uses its CAMA local policy and DAPA auction. ImpGTA, MRA and LocalSum use their existing MPCS pool policies, own local matchers and baseline cross components. Greedy uses the existing MPCS profit-aware decision policy and Greedy local matcher. RamCOM uses a sampled value threshold, random feasible local insertion, reservation-based expected-revenue payment and sampled partner acceptance. The MPCS auction accepts one bid per partner platform; RamCOM therefore sends its shortest-detour feasible courier as that platform's candidate.

RL-CAPA processes threshold-eligible parcels in descending local revenue score order. It uses each parcel's preferred courier when feasible and searches the remaining couriers after a batch conflict. A parcel with no feasible local courier after batch allocation waits for nine consecutive checks and releases on the tenth; a parcel below the dynamic threshold releases immediately, even when a local courier is feasible.

Only target-origin parcels enter the batch trace, map parcel layer, assignment counts and cooperation flow. OP is the target ledger total at the arrival-window cutoff. AR is target assignments divided by target pickups. BPT averages target policy, local matching and auction time across nonempty target batches; physical movement is excluded. Partner courier positions and routes remain visible as resources.

## Consequences

The demo preserves one MPCS environment per algorithm run and its settlement ledger. Comparison replays share one saved parcel catalog and road layer. Fixed city presets record complete batches in compressed chunks, so Inspection can load the selected interval without loading every algorithm's world state. The RL-CAPA option demonstrates the current rule-based CAMA and DAPA decisions; it does not execute the reference actor-critic model.
