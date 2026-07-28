# Callum's Simulation Package

This repository replaces simulation-specific runner, meshing, solver, export, and plotting scripts
with one installable, configuration-driven Python package. It supports four import-safe simulation
domains:

- `callums_simulation_package.nozzle`
- `callums_simulation_package.hose`
- `callums_simulation_package.nozzle_environment`
- `callums_simulation_package.nozzle_impinging`

The lowercase names and underscores are deliberate: spaces, `+`, and `-` are not valid in normal
Python import names. Shared stage functions live in `stages/`; the domain packages provide clear
public entry points without copying the implementation.

## Repository layout

```text
CallumsPhDworkpackage.code/
├── pyproject.toml
├── configs/
│   ├── nozzle.example.json
│   ├── hose.example.json
│   ├── nozzle_environment.example.json
│   └── nozzle_impinging.example.json
├── hpc/
│   └── fawkes.pbs
├── src/callums_simulation_package/
│   ├── nozzle/
│   ├── hose/
│   ├── nozzle_environment/
│   ├── nozzle_impinging/
│   ├── stages/
│   ├── config.py
│   ├── operations.py
│   └── runner.py
├── tests/
└── tools/audit_legacy.py
```

At deployment, keep geometry, auxiliary inputs, and results beside the repository:

```text
work/
├── CallumsPhDworkpackage.code/
├── Geometry/
└── Results/
```

`CALLUMS_GEOMETRY_ROOT`, `CALLUMS_INPUT_ROOT`, and `CALLUMS_RESULTS_ROOT` override the JSON paths,
so the same committed config can be used on a laptop and Fawkes. Named auxiliary inputs such as
Fluent profile files are resolved below a sibling `Inputs` directory and validated before solving.

## Install

The package targets the legacy environment's PyFluent version, `ansys-fluent-core
0.37.2`. The exact pin is intentional because Fluent settings paths can change between releases.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[all]"
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Prepare Linux geometry

Do not copy `.dsco` files directly into a Linux meshing job. Ansys documents Discovery `.dsco`
geometry as Windows-only for Fluent Meshing. Import it on Windows with **Save PMDB** enabled, then
copy the generated `.pmdb` file beside the `.dsco` and use the `.pmdb` path in the Fawkes config.
See the [Ansys topology-based meshing guidance](https://ansyshelp.ansys.com/public/Views/Secured/corp/v251/en/fluent_beta_doc/flu_mesh_workflow_topology.html).

## Configure and run

Copy the nearest example and review every value marked by its `metadata.scientific_review_required`
flag. The examples preserve representative values from the latest legacy script families; they are
migration templates, not scientifically revalidated cases.

```bash
callums-sim plan configs/nozzle.example.json
callums-sim validate configs/nozzle.example.json
callums-sim run configs/nozzle.example.json
```

Run only an ordered subset when iterating or resuming:

```bash
callums-sim run configs/nozzle.example.json --stages mesh
callums-sim run configs/nozzle.example.json --stages solve export plot
```

The same workflow is importable:

```python
from callums_simulation_package.nozzle import run

run("configs/nozzle.example.json", stages=["solve", "export", "plot"])
```

## Worked split-stage test

`configs/sim-1-12.test.json` is a direct migration of the legacy sim-1-12 mesh with its
solver-1-01 and results-1-1 stages. Follow
[`docs/SIM_1_12_TEST.md`](docs/SIM_1_12_TEST.md) to mesh the Discovery geometry on Windows,
transfer the deterministic `.msh.h5`, and run `solve export plot` in WSL or on Fawkes.


Additional direct migrations and per-case split-stage guides are:

- `configs/sim-3-05.test.json` / [`docs/SIM_3_05_README.md`](docs/SIM_3_05_README.md)
- `configs/sim-4-04.test.json` / [`docs/SIM_4_04_README.md`](docs/SIM_4_04_README.md)
- `configs/sim-8-02.test.json` / [`docs/SIM_8_02_README.md`](docs/SIM_8_02_README.md)
- `configs/sim-8-06.test.json` / [`docs/SIM_8_06_README.md`](docs/SIM_8_06_README.md)
- `configs/sim-11-01.1-0.15.test.json` /
  [`docs/SIM_11_01_1_0_15_README.md`](docs/SIM_11_01_1_0_15_README.md)

JSON contains geometry, meshing, physics, boundary-condition, iteration, export, and plotting
parameters. It never points at another Python script. `operations.py` applies versioned Fluent
settings operations and reports the exact operation number/path on failure.

## Results

Every run name is generated from the simulation ID and mesh/solver/post versions:

```text
Results/
└── Nozzle_simulations/
    └── Nozzle_simulation1.1-0.1-0.1-0.1/
        ├── Case_and_data/
        │   ├── Nozzle_simulation1.1-0.1-0.1-0.1.msh.h5
        │   ├── Nozzle_simulation1.1-0.1-0.1-0.1.cas.h5
        │   └── Nozzle_simulation1.1-0.1-0.1-0.1.dat.h5
        ├── Data_export/
        │   ├── Throat_data/
        │   ├── Contour_data/
        │   ├── Line_data/
        │   └── Profile_data/
        ├── Results_plotting/
        │   ├── Line_plot/
        │   └── Contour_plot/
        └── run_manifest.json
```

The manifest records the config and geometry hashes, timestamps, host/scheduler identity, stage
status, errors, and every expected artifact path. HDF5 Fluent extensions are used because the
legacy workflows and current PyFluent APIs already use CFF/HDF5 case, data, and mesh files.

## Fawkes (PBS Pro)

Fawkes currently runs RHEL 8.10 with PBS Pro, so use the supplied PBS script:

```bash
qsub -v CONFIG=configs/nozzle.example.json hpc/fawkes.pbs
qstat
```

Before the first production submission, confirm the current Ansys module name with `module avail
ansys` and update the resource request in `hpc/fawkes.pbs`. Leave `fluent.processor_count` as
`null`: inside a scheduler allocation, PyFluent can discover the allocated hosts/cores. Setting an
integer deliberately caps Fluent below the allocation.

## Quality checks

```bash
python -m unittest discover -s tests
python -m ruff check .
python tools/audit_legacy.py "/path/to/Nozzle_simulation_code" --output legacy-audit.json
```

The full legacy review is in [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md), and the per-family migration
sequence is in [docs/MIGRATION.md](docs/MIGRATION.md).
