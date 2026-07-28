# sim-1-12 split-stage test

This is the worked migration and smoke test for the legacy `sim-1-12` case. Its config is
`configs/sim-1-12.test.json`, and its deterministic run name is `sim-1-12-01-1`.

The migration preserves the active values from:

- mesh revision 1-12: `snakebite_6_nozzle_only-meshing-1-12.py`;
- solver revision 1-01: `snakebite_6_nozzle_only-solver-1-01.py`;
- post-processing revision 1-1: `snakebite_6_nozzle_only-results-1-1.py`.

The generic `configs/nozzle.example.json` is not a faithful sim-1-12 case. In particular, it
omits the third face-size control and uses an unsteady three-step solve, while the legacy case is a
steady, coupled, second-order, 250-iteration solve.

## What the test config preserves

The config includes all three local face sizes, the surface and poly-hexcore volume settings, ten
smooth-transition boundary layers, the boundary label map, ideal-gas/Sutherland air, Transition SST,
the legacy pressure and turbulence boundary values, second-order discretization, residual targets,
hybrid initialization, and 250 iterations.

It also exports all seven legacy line surfaces and the YZ mid-plane. The plotting stage creates
representative centreline and throat plots plus five mid-plane contours.

The following legacy behaviours are deliberately not treated as acceptance criteria:

- Wall roughness and wall thermal-material assignments were wrapped in a broad `try/except`, so the
  old script could silently skip them.
- The report called `NE_P_static_avg` actually requested `dynamic-pressure`, despite being labelled
  as static pressure later.
- The new generic exporter does not yet write the old mass-flow/convergence CSV or report-monitor
  images.
- The old script executed `Share Topology` only if Fluent happened to expose that task; the concise
  structured meshing workflow does not force it.

The legacy output records inlet mass flow (+0.1118656174 kg/s), outlet mass flow
(-0.1118655559 kg/s), and net imbalance (6.14557e-8 kg/s). Use those as regression evidence only
after confirming that the mesh statistics, Fluent release, convergence, and pressure convention also
match.

## Required directory layout

Use the same sibling layout on each machine:

```text
Simulations/
??? CallumsPhDworkpackage.code/
??? Geometry/
??? Results/
```

The test config's default roots expect this layout. Environment variables let Windows use the
existing OneDrive geometry while Linux uses its own results tree.

## 1. Generate the mesh on Windows

Run these commands in Windows PowerShell on a computer with Ansys Fluent and a working licence. The
commands use the existing Discovery file in the legacy tree and keep generated results out of
OneDrive.

```powershell
Set-Location C:\Simulations\CallumsPhDworkpackage.code

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[all]"

$env:CALLUMS_GEOMETRY_ROOT = "C:\Users\U1173289\OneDrive - UniSQ\Documents\Nozzle simulations"
$env:CALLUMS_RESULTS_ROOT = "C:\Simulations\Results"

Test-Path (Join-Path $env:CALLUMS_GEOMETRY_ROOT "Nozzle models\Discovery_files\Snakebite_No6_nozzle_only_sim-1.dsco")

callums-sim plan configs\sim-1-12.test.json --stages mesh
callums-sim validate configs\sim-1-12.test.json --stages mesh
callums-sim run configs\sim-1-12.test.json --stages mesh
```

The successful mesh is:

```text
C:\Simulations\Results\Nozzle_simulations\sim-1-12-01-1\Case_and_data\
    sim-1-12-01-1.msh.h5
C:\Simulations\Results\Nozzle_simulations\sim-1-12-01-1\
    run_manifest.json
```

Before transfer, inspect the Fluent mesh check, zone names, dimensional scale, cell count, minimum
orthogonal quality, and boundary-layer creation. Stop if the zones are not exactly
`pressure_inlet`, `outlet`, `wall.1` through `wall.6`, and `enclosure`.

If Windows Fluent cannot import the `.dsco` directly in this automated workflow, import it once in
Fluent Meshing with **Save PMDB** enabled, copy the PMDB under `Geometry`, and change only the
config's `geometry` value to that relative PMDB path.

## 2. Transfer the mesh into WSL

The Linux stages look for the deterministic filename above. Copy the mesh and manifest into the
same relative results paths; do not rename them. The manifest carries the Windows geometry hash and
completed mesh-stage record into the Linux continuation.

```powershell
$windowsRun = "C:\Simulations\Results\Nozzle_simulations\sim-1-12-01-1"
$windowsMesh = Join-Path $windowsRun "Case_and_data\sim-1-12-01-1.msh.h5"
$windowsManifest = Join-Path $windowsRun "run_manifest.json"
$wslRunDir = "\\wsl.localhost\Ubuntu\home\u173289\Simulations\Results\Nozzle_simulations\sim-1-12-01-1"
$wslCaseDir = "\\wsl.localhost\Ubuntu\home\u173289\Simulations\Results\Nozzle_simulations\sim-1-12-01-1\Case_and_data"

New-Item -ItemType Directory -Force -Path $wslCaseDir
Copy-Item -LiteralPath $windowsMesh -Destination $wslCaseDir
Copy-Item -LiteralPath $windowsManifest -Destination $wslRunDir
```

Verify the copy inside WSL:

```bash
sha256sum /home/u173289/Simulations/Results/Nozzle_simulations/sim-1-12-01-1/Case_and_data/sim-1-12-01-1.msh.h5
```

For a stricter check, run `Get-FileHash -Algorithm SHA256 $windowsMesh` before the copy and compare
the two hashes.

## 3. Run solve, export, and plot in WSL

A normal Windows Fluent installation is not a Linux Fluent installation. This package calls
`ansys.fluent.core.launch_fluent()` locally, so WSL must have access to a native Linux Fluent
installation and licence. Check that first:

```bash
command -v fluent
fluent -v
```

If `fluent` is not found, use Windows for a complete laptop smoke test and use Fawkes for the Linux
solver test. WSL can still run the package tests and the pure-Python plotting stage, but it cannot
perform `solve` or `export` without Fluent.

With Linux Fluent available:

```bash
cd /home/u173289/Simulations/CallumsPhDworkpackage.code

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[all]'

export CALLUMS_RESULTS_ROOT=/home/u173289/Simulations/Results

callums-sim plan configs/sim-1-12.test.json --stages solve export plot
callums-sim validate configs/sim-1-12.test.json --stages solve export plot
callums-sim run configs/sim-1-12.test.json --stages solve export plot
```

The stage-specific validation is important: it checks the transferred mesh and later artifacts
without trying to validate the Windows-only `.dsco` on Linux.

For a full laptop smoke test on Windows instead, leave the mesh in place and run:

```powershell
callums-sim validate configs\sim-1-12.test.json --stages solve export plot
callums-sim run configs\sim-1-12.test.json --stages solve export plot
```

## 4. Transfer and run on Fawkes

UniSQ currently documents Fawkes as RHEL 8.10 with PBS Pro. Transfer data through the login node
`hpc-login-prd-t1.usq.edu.au`; campus Ethernet is preferred, and off-campus access requires the
UniSQ VPN. See the
[UniSQ eResearch overview](https://www.unisq.edu.au/research/support/eresearch) and
[official data-transfer guide](https://www.unisq.edu.au/-/media/usq/current-students/academic/research/conducting-research/eresearch-services/hpc/usq-network-data-transfer-guide.ashx).

From WSL, replace `<username>` and adjust the remote base directory if needed:

```bash
ssh <username>@hpc-login-prd-t1.usq.edu.au \
  'mkdir -p ~/Simulations/Results/Nozzle_simulations/sim-1-12-01-1/Case_and_data'

scp /home/u173289/Simulations/Results/Nozzle_simulations/sim-1-12-01-1/run_manifest.json \
  <username>@hpc-login-prd-t1.usq.edu.au:~/Simulations/Results/Nozzle_simulations/sim-1-12-01-1/

scp /home/u173289/Simulations/Results/Nozzle_simulations/sim-1-12-01-1/Case_and_data/sim-1-12-01-1.msh.h5 \
  <username>@hpc-login-prd-t1.usq.edu.au:~/Simulations/Results/Nozzle_simulations/sim-1-12-01-1/Case_and_data/
```

On the Fawkes login node, clone/pull the repository and perform the one-time environment setup. The
exact Ansys module name and compatible Python/PyFluent combination are site-specific, so inspect the
available modules before submitting:

```bash
cd ~/Simulations/CallumsPhDworkpackage.code
module avail ansys
module load ansys

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[all]'
python -m unittest discover -s tests
```

Submit only the Linux stages. The `+` separators are intentional because PBS uses commas to
separate environment variables:

```bash
qsub -v CONFIG=configs/sim-1-12.test.json,STAGES=solve+export+plot hpc/fawkes.pbs
qstat
```

The supplied PBS file requests one node, 16 CPUs and 64 GB. The config leaves
`fluent.processor_count` as `null`, allowing PyFluent to use the scheduler allocation. Confirm the
current module, licence, memory and wall-time requirements with UniSQ eResearch before a production
run. UniSQ's official PBS/Ansys examples also use `module load ansys`, `$PBS_O_WORKDIR`, and
`qsub`: [PBS Pro and Ansys examples](https://www.unisq.edu.au/-/media/usq/current-students/academic/research/conducting-research/eresearch-services/hpc/pbs-ansys-examples.ashx).

## 5. Check the outputs

After `solve export plot`, expect:

```text
Results/Nozzle_simulations/sim-1-12-01-1/
|-- Case_and_data/
|   |-- sim-1-12-01-1.msh.h5
|   |-- sim-1-12-01-1.cas.h5
|   `-- sim-1-12-01-1.dat.h5
|-- Data_export/
|   |-- Line_data/*.csv
|   `-- Contour_data/mid-plane.csv
|-- Results_plotting/
|   |-- Line_plot/*.png
|   `-- Contour_plot/*.png
`-- run_manifest.json
```

Review the manifest and batch log first. Then compare mass conservation, mesh statistics, centreline
pressure/velocity, throat profiles, and contour ranges with the legacy case. Treat a clean process
exit as necessary but not sufficient scientific validation.

