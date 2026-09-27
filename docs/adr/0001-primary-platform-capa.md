# Primary-platform CAPA in the MAPS demo

Status: Accepted

## Context

The MPCS environment lets every platform own parcels and submit actions in the same physical frame. The CAPA reference models one origin platform that releases parcels to cooperating platforms. The demo needs to show that origin's local threshold and full partner auction without changing the other MPCS policies.

## Decision

When the selected focus platform uses `rl-capa`, it is the sole primary platform for the run. Its local policy and matcher share the same CAMA plan. Every partner with a feasible EV submits a route-based FPSA offer for a released primary parcel. DAPA ranks valid platform bids and sets payment. The primary platform submits no cross bids. Partner-owned workload remains in the simulation and follows its selected local policy; Inspection's CAPA batch trace shows the primary platform's parcels.

The chosen primary platform is stored with the run. Changing the focus control after a run changes visual emphasis but does not change auction roles until the next run.

## Consequences

The demo keeps one physical MPCS environment and its existing settlement ledger. The CAPA bidder and auctioneer are local demo components, while the core RL-CAPA rule supplies the cumulative local revenue threshold. This mode demonstrates CAMA and DAPA decisions without loading the reference actor-critic model.
