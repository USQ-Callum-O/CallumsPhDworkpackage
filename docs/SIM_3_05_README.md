# sim-3-05 migration and split-stage run guide

Config: `configs/sim-3-05.test.json`  
Deterministic run name: `sim-3-04-03-05`

## Provenance and compatibility

This case is a direct migration of `sim-3-05_config.json` using:

- `streight_hose-meshing-3-04.py`;
- `streight_hose-solver-3-03.py`;
- `streight_hose_Sim-3-05-results.py` as the authoritative results script.

The legacy config names `streight_hose_Sim-3-07-results.py`, but that script writes profile files with `3-06` names. A separate 3-05 results script exists, and its line CSVs, plane CSVs, plots, three populated profiles, and case/data files all match the 3-05 run. The migrated config therefore corrects the pointer rather than reproducing the inconsistent reference.

The current structured mesh and solver stages support the active workflow. The export stage was extended with a per-surface `profile` definition so this source case writes its three reusable Fluent profiles to `Data_export/Profile_data`. Those files are the inputs used by the migrated Simulation 4 and Simulation 8 cases.

## Preserved settings and review items

The migration preserves the active legacy values: a 5 m straight hose, poly-hexcore mesh, ten smooth-transition boundary layers, steady pressure-based real-gas air, realizable k-epsilon, energy, gravity, 0.1136 kg/s inlet mass flow, 689476 Pa outlet gauge pressure, hybrid initialization, and 250 iterations.

Review these items before treating the run as scientifically accepted:

- The outlet mesh type is corrected from the invalid legacy type string `outlet` to `pressure-outlet`; the zone name remains `outlet`.
- `line4-360mm` was actually sampled at 0.036 m (36 mm), which is confirmed by its legacy CSV. The config preserves 0.036 m and keeps the old name for traceability.
- The solver's diagnostic `hose_outlet_plane` is at 0.49 m, while the hose is 5 m and the actual downstream profile plane is at 4.9 m. The config preserves 0.49 m for the diagnostic report only.
- The NIST real-gas lookup range in the legacy solver is 13200-20000 Pa while the boundary gauge-pressure value is 689476 Pa. Confirm that range and units against the intended Fluent material setup.
- Optional Improve Surface Mesh and Remesh Surface workflow tasks are not forced by the generic structured mesher.
- The legacy mass-flow summary CSV is not generated. The recorded 3-05 result was inlet `0.1136000000`, outlet `-0.1134890728`, and net `0.0001109272` kg/s.
- The generic plotting stage creates one multi-series image per line instead of four separate subplots.

Do not use `configs/streight_hose-3-05_exit_plane_4900mm.prof` from the legacy tree as an inlet. It is only a 176-byte, zero-point template. The populated profile in `PyFluent/Case_and_data_files/Simulation3` contains 1001 points.

## Required layout

```text
Simulations/
|-- CallumsPhDworkpackage.code/
|-- Geometry/Blast hose/5000mm_streight_hose.dsco
|-- Inputs/Profiles/
`-- Results/
```

The sim-3-05 solve has no auxiliary input profile. `Inputs/Profiles` is the destination for the profiles produced for dependent cases.

## Generate the mesh on Windows

Discovery `.dsco` geometry must be imported on Windows. In a Windows clone of the repository:

```powershell
Set-Location C:\Simulations\CallumsPhDworkpackage.code
.\.venv\Scripts\Activate.ps1

$env:CALLUMS_GEOMETRY_ROOT = "C:\Users\U1173289\OneDrive - UniSQ\Documents\Nozzle simulations"
$env:CALLUMS_RESULTS_ROOT = "C:\Simulations\Results"

callums-sim plan configs\sim-3-05.test.json --stages mesh
callums-sim validate configs\sim-3-05.test.json --stages mesh
callums-sim run configs\sim-3-05.test.json --stages mesh
```

Before transfer, inspect the Fluent mesh check and confirm:

- boundary zones `mass-flow-inlet`, `outlet`, and `wall`;
- fluid region `hose-hose`;
- the inlet/outlet face sizing, wall sizing, and `boi1-boi1` control;
- ten smooth-transition layers;
- scale, cell count, minimum orthogonal quality, and absence of negative volumes.

## Transfer the mesh to WSL

```powershell
$runName = "sim-3-04-03-05"
$windowsRun = "C:\Simulations\Results\Hose_simulations\$runName"
$wslBase = "\\wsl.localhost\Ubuntu\home\u173289\Simulations"
$wslRun = "$wslBase\Results\Hose_simulations\$runName"
$wslCase = "$wslRun\Case_and_data"

New-Item -ItemType Directory -Force -Path $wslCase
Copy-Item -LiteralPath "$windowsRun\Case_and_data\$runName.msh.h5" -Destination $wslCase
Copy-Item -LiteralPath "$windowsRun\run_manifest.json" -Destination $wslRun

Get-FileHash -Algorithm SHA256 "$windowsRun\Case_and_data\$runName.msh.h5"
Get-FileHash -Algorithm SHA256 "$wslCase\$runName.msh.h5"
```

The legacy mesh is about 504 MB, so verify both hashes rather than relying on file size alone.

## Solve, export, and plot on WSL

A native Linux Fluent installation and a reachable Ansys licence are required. The Python plotting stage itself is headless.

```bash
cd /home/u173289/Simulations/CallumsPhDworkpackage.code
source .venv/bin/activate

export CALLUMS_RESULTS_ROOT=/home/u173289/Simulations/Results
export CALLUMS_INPUT_ROOT=/home/u173289/Simulations/Inputs

callums-sim plan configs/sim-3-05.test.json --stages solve export plot
callums-sim validate configs/sim-3-05.test.json --stages solve export plot
callums-sim run configs/sim-3-05.test.json --stages solve export plot
```

Expected outputs include:

```text
Results/Hose_simulations/sim-3-04-03-05/
|-- Case_and_data/sim-3-04-03-05.cas.h5
|-- Case_and_data/sim-3-04-03-05.dat.h5
|-- Data_export/Line_data/*.csv
|-- Data_export/Contour_data/*.csv
|-- Data_export/Profile_data/streight_hose-3-05_exit_plane_4900mm.prof
|-- Data_export/Profile_data/streight_hose-3-05_test_plane_1300mm.prof
|-- Data_export/Profile_data/streight_hose-3-05_test_exit_plane_1700mm.prof
`-- Results_plotting/
```

Publish the generated profiles for the dependent cases:

```bash
mkdir -p /home/u173289/Simulations/Inputs/Profiles
profile_dir=/home/u173289/Simulations/Results/Hose_simulations/sim-3-04-03-05/Data_export/Profile_data
cp "$profile_dir/streight_hose-3-05_exit_plane_4900mm.prof" \
   "$profile_dir/streight_hose-3-05_test_plane_1300mm.prof" \
   "$profile_dir/streight_hose-3-05_test_exit_plane_1700mm.prof" \
   /home/u173289/Simulations/Inputs/Profiles/
```

Check that the profile headers report non-zero point counts. The legacy reference counts are 1001 at 4.9 m, 962 at 1.3 m, and 998 at 1.7 m; modest count differences can result from a changed mesh.

## Run on Fawkes

Copy the mesh and manifest to the identical relative result-tree location on Fawkes, then submit only the Linux-compatible stages:

```bash
cd /path/to/CallumsPhDworkpackage.code
qsub -v CONFIG=configs/sim-3-05.test.json,STAGES=solve+export+plot hpc/fawkes.pbs
```

Set the geometry, input, and result root variables in the PBS environment as documented in `hpc/fawkes.pbs`. Keep `fluent.processor_count` as `null` so the scheduler allocation controls the parallel resources.

## Acceptance checklist

1. Confirm mesh scale, zones, region name, quality, and cell count on Windows.
2. Confirm the Linux plan resolves the transferred canonical mesh path.
3. Review residuals and report convergence after 250 iterations; do not assume the fixed count guarantees convergence.
4. Compare inlet/outlet mass flow with the legacy values above.
5. Compare centreline and transverse profiles, remembering that `line4-360mm` is a 36 mm station.
6. Open each generated `.prof` file and confirm its surface name, field list, and non-zero point count before using it in simulations 4 or 8.
7. Record and justify any decision to correct the 0.49 m diagnostic plane or the NIST pressure-table range in a new versioned config rather than silently changing this migration baseline.
