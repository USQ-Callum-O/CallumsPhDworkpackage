# sim-8-02 migration and split-stage run guide

Config: `configs/sim-8-02.test.json`  
Deterministic run name: `sim-8-01-02-06`

## Provenance and compatibility

This is a direct migration of `sim-8-02_config.json` using:

- `Thomsonvalve_Sim-8-01-meshing.py`;
- `Thomsonvalve_Sim-8-02-solver.py`;
- `Thomsonvalve_Sim-8-02-results-export6.py`;
- `Thomsonvalve_Sim-8-02-results-plotting2.1.py`.

The active solver is an unsteady, second-order, dry-air carrier-flow calculation: 150 steps at 0.0025 s with up to 250 iterations per step. Although the script contains DPM injection, particle animation, and trajectory-sampling code, those blocks are triple-quoted and do not execute. This config intentionally does not claim to be a DPM run.

The legacy config also names `thomsonvalve_Sim-8-02-resume.py`, but that file is absent. The new case therefore starts from the mesh. A checkpoint resume must be prepared separately as described below.

The mesh/solver structure is compatible with the current stages. The package now validates the required Simulation 3 inlet profile as a portable named input. The current export stage reproduces the nine line and ten plane field CSVs, with the accidentally diagonal legacy line 7/8 definitions corrected to transverse stations. It does not yet reproduce export6's plane audit, area-weighted-average tables, mass-flow summary, or the full legacy plotting suite.

## Required files and zone check

```text
Simulations/
|-- CallumsPhDworkpackage.code/
|-- Geometry/Blast hose/Thomsonvalve+2500mm_streight_hose-2.dsco
|-- Inputs/Profiles/streight_hose-3-05_test_plane_1300mm.prof
`-- Results/
```

After meshing, verify `mass-flow-inlet`, `outlet`, `wall.1.1`, `wall.1.2`, `wall.1.3`, and the `hose-solid` fluid region. The imported Fluent profile must be named `test_plane_1p3m`.

## Generate the mesh on Windows

```powershell
Set-Location C:\Simulations\CallumsPhDworkpackage.code
.\.venv\Scripts\Activate.ps1

$env:CALLUMS_GEOMETRY_ROOT = "C:\Users\U1173289\OneDrive - UniSQ\Documents\Nozzle simulations"
$env:CALLUMS_RESULTS_ROOT = "C:\Simulations\Results"

callums-sim plan configs\sim-8-02.test.json --stages mesh
callums-sim validate configs\sim-8-02.test.json --stages mesh
callums-sim run configs\sim-8-02.test.json --stages mesh
```

Inspect scale, cell count, orthogonal quality, 15 uniform layers, boundary labels, and region names before transfer.

## Transfer to WSL

```powershell
$runName = "sim-8-01-02-06"
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

Compare mesh and profile hashes after copying.

## Solve, export, and plot on Linux

```bash
cd /home/u173289/Simulations/CallumsPhDworkpackage.code
source .venv/bin/activate

export CALLUMS_RESULTS_ROOT=/home/u173289/Simulations/Results
export CALLUMS_INPUT_ROOT=/home/u173289/Simulations/Inputs

callums-sim plan configs/sim-8-02.test.json --stages solve export plot
callums-sim validate configs/sim-8-02.test.json --stages solve export plot
callums-sim run configs/sim-8-02.test.json --stages solve export plot
```

A native Linux Fluent installation and licence are required in WSL. Otherwise run the complete laptop test on Windows or submit the Linux stages to Fawkes:

```bash
qsub -v CONFIG=configs/sim-8-02.test.json,STAGES=solve+export+plot hpc/fawkes.pbs
```

Copy the mesh, manifest, and inlet profile to the same relative `Results` and `Inputs` paths on Fawkes before submission.

## Resume and acceptance notes

The current runner resumes only from its canonical case/data names. To resume the legacy 75-step checkpoint, copy both its case and data files to this run's `Case_and_data` directory as `sim-8-01-02-06.cas.h5` and `sim-8-01-02-06.dat.h5`, create a new versioned config with `solver.input` set to `case_data`, remove hybrid initialization, and set only the additional required step count. Do not overwrite this base config or reuse its run name with changed operations.

For acceptance, inspect the inlet profile, time-step history, autosaves, mass balance, and axial/transverse profiles. The absence of particles is expected for this base 8.02 migration.
