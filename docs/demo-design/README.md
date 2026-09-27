# MAPS demo design

The current design and implementation contract is [07-MAPS系统演示设计.md](07-MAPS系统演示设计.md). MAPS runs as a local Dash application with three focused modules:

1. **Simulation** configures and runs an `mpcs` episode.
2. **Inspection** replays each pending batch through workload, parcel, local decision, auction and settlement on the processed road network.
3. **Analysis** plots the selected arrival window's assignment and ledger results.

Documents `01–06` and their static mockup describe an earlier two-tab CAPA concept. They remain research references. The current behavior follows the `mpcs` environment and the RL-CAPA CAMA/DAPA adaptation in `maps_demo/capa.py`.
