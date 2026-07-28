# sim-11-01.1-0.15 migration and split-stage run guide

Config: `configs/sim-11-01.1-0.15.test.json`  
Requested alias: `sim_11_01.1_0.15`  
Deterministic run name: `sim-11-01.1-0.15-01.1-01.1`

## Provenance and compatibility

This is a direct migration of `sim-11-01.1-0.15_config.json` and its referenced mesh, solver, export, and plotting scripts.

The mesh structure is supported by the current Watertight Geometry stage: all face sizes, four BOI controls, the 0.4 mm impingement refinement, ten smooth-transition layers, and poly-hexcore limits are represented. Two questionable optional legacy operations are deliberately not forced:

- `Share Topology` ran only when Fluent exposed it;
- `Manage Zones` tried to merge `boi-1-solid` and `boi-2-solid`, while this exact geometry uses `boi-11` through `boi-15` for most BOI controls.

The solver structure is represented, including Transition SST, ideal-gas/Sutherland air, all five pressure outlets, explicit wall settings, nozzle-exit reports, second-order methods, residual criteria, and 500 iterations. The old broad wall `try/except` is removed so a bad wall path fails visibly.

The package now supports the three-point planes used by this case. The data-processing config also fixes two mismatches in the legacy pair:

- it creates the `mid_plane` required by the plotting script but absent from its exporter;
- it places `jet-10od_plane` at y=0.46029 m rather than duplicating the nozzle-exit plane at y=0.31819 m.

The report named `NE_P_static_avg` still samples `dynamic-pressure`, matching the executable legacy code. It must not be interpreted as static pressure. The current generic exporter does not yet combine mass-flow and report-file results into the legacy summary CSV.

## Required geometry and zone check

```text
Simulations/
|-- CallumsPhDworkpackage.code/
|-- Geometry/Nozzle models/Discovery_files/Basic_Snakebite_#7_300mm_offset_0.7.dsco
`-- Results/
```

Before solving, verify the single region `enclosure-solid`, inlet `pressure-inlet`, outlets `outlet.1` through `outlet.5`, walls `wall.1` through `wall.11`, and the expected interior zone. Also confirm each BOI sizing control actually selected faces and that BOI faces did not become unintended solver boundaries.

## Generate the mesh on Windows

```powershell
Set-Location C:\Simulations\CallumsPhDworkpackage.code
.\.venv\Scripts\Activate.ps1

$env:CALLUMS_GEOMETRY_ROOT = "C:\Users\U1173289\OneDrive - UniSQ\Documents\Nozzle simulations"
$env:CALLUMS_RESULTS_ROOT = "C:\Simulations\Results"

callums-sim plan configs\sim-11-01.1-0.15.test.json --stages mesh
callums-sim validate configs\sim-11-01.1-0.15.test.json --stages mesh
callums-sim run configs\sim-11-01.1-0.15.test.json --stages mesh
```

Inspect dimensional scale, surface/volume cell counts, minimum orthogonal quality, boundary-layer creation, BOI selection, and zone names before transfer.

## Transfer mesh and manifest to WSL

```powershell
$runName = "sim-11-01.1-0.15-01.1-01.1"
$windowsRun = "C:\Simulations\Results\Nozzle_impinging_simulations\$runName"
$wslBase = "\\wsl.localhost\Ubuntu\home\u173289\Simulations"
$wslRun = "$wslBase\Results\Nozzle_impinging_simulations\$runName"
$wslCase = "$wslRun\Case_and_data"

New-Item -ItemType Directory -Force -Path $wslCase
Copy-Item -LiteralPath "$windowsRun\Case_and_data\$runName.msh.h5" -Destination $wslCase
Copy-Item -LiteralPath "$windowsRun\run_manifest.json" -Destination $wslRun
```

Compare the Windows and WSL mesh SHA-256 hashes.

## Solve, export, and plot on Linux

```bash
cd /home/u173289/Simulations/CallumsPhDworkpackage.code
source .venv/bin/activate

export CALLUMS_RESULTS_ROOT=/home/u173289/Simulations/Results

callums-sim plan configs/sim-11-01.1-0.15.test.json --stages solve export plot
callums-sim validate configs/sim-11-01.1-0.15.test.json --stages solve export plot
callums-sim run configs/sim-11-01.1-0.15.test.json --stages solve export plot
```

WSL must have native Linux Fluent and a licence. Otherwise use Windows for the full laptop run or copy the mesh and manifest to matching Fawkes paths and submit:

```bash
qsub -v CONFIG=configs/sim-11-01.1-0.15.test.json,STAGES=solve+export+plot hpc/fawkes.pbs
```

## Acceptance checks

Review the run manifest and Fluent transcript, then verify mesh statistics, all five outlet pressures, nozzle-exit mass flow, residual/report histories, mass conservation, centreline profiles, 10-diameter jet profiles, target-wall dynamic pressure, and the corrected plane locations. Keep the corrected post-processing geometry distinct from any comparison made against legacy CSVs produced at the duplicated plane location.
