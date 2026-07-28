# sim-4-04 migration and split-stage run guide

Config: `configs/sim-4-04.test.json`  
Deterministic run name: `sim-4-04-02-01`

## Provenance and status

No legacy `sim-4-04_config.json`, 4-04 script, mesh, case, or data file exists in the reviewed tree. The available sequence ends at 4-03. The new config is therefore a controlled extrapolation:

- geometry: the 500 mm straight-hose Discovery model used by 4-01 through 4-03;
- mesh settings: the latest `Hose_section_Sim-4-03-meshing.py` settings;
- physics: `Hose_section_Sim-4-02-solver.py`, which the 4-03 config also reused;
- post-processing surfaces: `Hose_section_Sim-4-01-results.py`, shared by all three configs.

Do not treat 4-04 as a recovered historical result. Its mesh/solver/post versions are explicit so a later genuine 4-04 definition can be given a different version or run name.

## Compatibility findings

The structure is supported by the current mesh and solver stages after these deliberate corrections:

- The mesher used both `outlet` and `outflow`; the solver requires `outflow`. The new boundary map consistently creates `outflow` as a pressure outlet.
- The solver loaded two Simulation 3 profiles but used only `test_plane_1p3m`. Only that required profile is now a named, validated input.
- The legacy optional improve/remesh operations are not forced. Inspect the mesh check and add explicit workflow tasks only if the 4-04 geometry needs them.
- Core line and contour CSVs and plots are supported. The legacy mass-flow summary CSV is not yet reproduced by the generic exporter.

Before solving, confirm the zones are `mass-flow-inlet`, `outflow`, `wall`, and `hose-hose`, and confirm the profile name imported into Fluent is `test_plane_1p3m`.

## Required files

With the default sibling layout:

```text
Simulations/
|-- CallumsPhDworkpackage.code/
|-- Geometry/Blast hose/500mm_streight_hose.dsco
|-- Inputs/Profiles/streight_hose-3-05_test_plane_1300mm.prof
`-- Results/
```

The legacy profile source is:

```text
Nozzle_simulation_code/PyFluent/Case_and_data_files/Simulation3/
    streight_hose-3-05_test_plane_1300mm.prof
```

## Generate the mesh on Windows

In PowerShell on a Windows computer with Fluent and a licence:

```powershell
Set-Location C:\Simulations\CallumsPhDworkpackage.code
.\.venv\Scripts\Activate.ps1

$env:CALLUMS_GEOMETRY_ROOT = "C:\Users\U1173289\OneDrive - UniSQ\Documents\Nozzle simulations"
$env:CALLUMS_RESULTS_ROOT = "C:\Simulations\Results"

callums-sim plan configs\sim-4-04.test.json --stages mesh
callums-sim validate configs\sim-4-04.test.json --stages mesh
callums-sim run configs\sim-4-04.test.json --stages mesh
```

Inspect mesh scale, cell count, minimum orthogonal quality, 15-layer creation, named zones, and the single `hose-hose` fluid region before transfer.

## Transfer mesh, manifest, and profile to WSL

```powershell
$runName = "sim-4-04-02-01"
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

Compare Windows and WSL SHA-256 hashes for the mesh and profile.

## Solve, export, and plot on Linux

WSL needs a native Linux Fluent installation and licence. A normal Windows Fluent installation is not callable as Linux Fluent. If `command -v fluent` fails, perform the laptop solve on Windows or use Fawkes.

```bash
cd /home/u173289/Simulations/CallumsPhDworkpackage.code
source .venv/bin/activate

export CALLUMS_RESULTS_ROOT=/home/u173289/Simulations/Results
export CALLUMS_INPUT_ROOT=/home/u173289/Simulations/Inputs

callums-sim plan configs/sim-4-04.test.json --stages solve export plot
callums-sim validate configs/sim-4-04.test.json --stages solve export plot
callums-sim run configs/sim-4-04.test.json --stages solve export plot
```

For Fawkes, copy the same mesh, manifest, and profile into matching `Results` and `Inputs` paths, load the site Ansys module, set the two root variables in the job environment, then submit:

```bash
qsub -v CONFIG=configs/sim-4-04.test.json,STAGES=solve+export+plot hpc/fawkes.pbs
```

## Acceptance checks

A successful process exit is only a structural test. Compare mesh statistics with 4-03, inspect the imported profile, verify mass balance, and compare centreline and 490 mm profiles with the legacy 4-03 result before using 4-04 scientifically.
