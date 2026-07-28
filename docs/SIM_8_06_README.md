# sim-8-06 migration and split-stage run guide

Config: `configs/sim-8-06.test.json`  
Deterministic run name: `sim-8-01-06-06`

## Provenance and compatibility

This config migrates `sim-8-06_config.json` with the shared Simulation 8 mesh and export/plot scripts plus `Thomsonvalve_Sim-8-06-solver.py`.

The active difference from 8.02 is the humid carrier gas:

- species transport is enabled;
- `dry-air` and `water-vapor` ideal-gas species are created;
- `humid-air` is built from Fluent's mixture template;
- the fluid region uses `humid-air`;
- the inlet dry-air mass fraction is 0.9968, leaving 0.0032 water vapour by difference;
- operating pressure is 101325 Pa and outlet gauge pressure is 588150.7293168 Pa;
- the run uses 400 steps at 0.0025 s, up to 250 iterations per step, with data autosave every 25 steps.

This species setup remains a scientific/runtime review gate. The legacy code assigned inlet species key `air`, but the mixture actually contains `dry-air` and `water-vapor`; that assignment could not work as written. The migrated config corrects the name, but you must inspect the Fluent mixture species order and inlet mass fractions before a production run. The TUI mixture prompts can also vary between Fluent releases, which is why the package remains pinned to the reviewed PyFluent generation.

As in base 8.02, all DPM injection and sampling blocks are triple-quoted and inactive. The resume script named by the legacy config is missing, and the checkpoint data path uses a non-HDF `.dat` extension. This config starts from the mesh.

The current generic exporter writes core line and plane field CSVs and representative plots. It does not reproduce the legacy AWA, plane-audit, mass-flow summary, or full plotting suite. The `cs_z_2460mm` plane is corrected to 2.460 m; the legacy solver accidentally used 2.260 m.

## Required files

Use the same geometry, inlet profile, and mesh zone checks as 8.02:

```text
Simulations/
|-- CallumsPhDworkpackage.code/
|-- Geometry/Blast hose/Thomsonvalve+2500mm_streight_hose-2.dsco
|-- Inputs/Profiles/streight_hose-3-05_test_plane_1300mm.prof
`-- Results/
```

Expected zones are `mass-flow-inlet`, `outlet`, `wall.1.1`, `wall.1.2`, `wall.1.3`, and `hose-solid`.

## Generate the mesh on Windows

```powershell
Set-Location C:\Simulations\CallumsPhDworkpackage.code
.\.venv\Scripts\Activate.ps1

$env:CALLUMS_GEOMETRY_ROOT = "C:\Users\U1173289\OneDrive - UniSQ\Documents\Nozzle simulations"
$env:CALLUMS_RESULTS_ROOT = "C:\Simulations\Results"

callums-sim plan configs\sim-8-06.test.json --stages mesh
callums-sim validate configs\sim-8-06.test.json --stages mesh
callums-sim run configs\sim-8-06.test.json --stages mesh
```

## Transfer mesh, manifest, and inlet profile to WSL

```powershell
$runName = "sim-8-01-06-06"
$windowsRun = "C:\Simulations\Results\Hose_simulations\$runName"
$wslBase = "\\wsl.localhost\Ubuntu\home\u173289\Simulations"
$wslRun = "$wslBase\Results\Hose_simulations\$runName"
$wslCase = "$wslRun\Case_and_data"
$wslProfiles = "$wslBase\Inputs\Profiles"
$legacyProfile = "C:\Users\U1173289\OneDrive - UniSQ\Documents\Nozzle simulations\Nozzle_simulation_code\PyFluent\Case_and_data_files\Simulation3\streight_hose-3-05_test_plane_1300mm.prof"

New-Item -ItemType Directory -Force -Path $wslCase, $wslProfiles
Copy-Item -LiteralPath "$windowsRun\Case_and_data\$runName.msh.h5" -Destination $wslCase
Copy-Item -LiteralPath "$windowsRun\run_manifest.json" -Destination $wslRun
Copy-Item -LiteralPath $legacyProfile -Destination $wslProfiles
```

Compare SHA-256 hashes after transfer.

## Solve, export, and plot on Linux

```bash
cd /home/u173289/Simulations/CallumsPhDworkpackage.code
source .venv/bin/activate

export CALLUMS_RESULTS_ROOT=/home/u173289/Simulations/Results
export CALLUMS_INPUT_ROOT=/home/u173289/Simulations/Inputs

callums-sim plan configs/sim-8-06.test.json --stages solve export plot
callums-sim validate configs/sim-8-06.test.json --stages solve export plot
callums-sim run configs/sim-8-06.test.json --stages solve export plot
```

WSL needs native Linux Fluent and a licence. On Fawkes, copy the same three inputs to matching paths, load the Ansys module, and submit:

```bash
qsub -v CONFIG=configs/sim-8-06.test.json,STAGES=solve+export+plot hpc/fawkes.pbs
```

## Required pre-production checks

Before accepting results, confirm in Fluent that `humid-air` contains exactly `dry-air` and `water-vapor`, the inlet fractions sum to one, mixture properties use the intended mixing laws, absolute/gauge pressure conventions are correct, and the expected water-vapour mass fraction is physically consistent with the intended relative humidity and temperature. Also check time-step convergence, autosaves, mass balance, and the 2.460 m plane position.

If resuming a checkpoint, create a new versioned config and canonical HDF case/data pair as described in `SIM_8_02_README.md`; do not mutate this base config under the same run name.
