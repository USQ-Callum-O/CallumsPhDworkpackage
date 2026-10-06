# sim-8-01-08.1-09: water particles, sampling, and analysis

The full name retains the simulation-8 prefix from the existing package. This is the requested
01 / 08.1 / 09 revision. It inherits the successful 8-01-08-08 water-droplet physics and mesh
settings. It migrates the Sample recorder and plotting methods used by the old Simulation8.1
code, rather than running that steel-shot solver.

## Why the earlier outputs were inadequate

The earlier scene contained both the carrier velocity contour and diameter-coloured particle
tracks. Both animations also used the automatically selected graphics window. This revision
uses three distinct windows and directories: carrier velocity (window 1), particle velocity
(window 2), and particle diameter (window 3). Each particle scene has exactly one particle
graphics object. Picture width/height are explicitly 2560 x 1440, with window resolution
disabled, and TIFF storage type 6 matches the successful previous CXA sequences. Preserve each
CXA file and its associated TIFF frames together when downloading and playing back in Fluent.

The earlier config requested DPM *surface fields*, which are not particle trajectory files.
This case calls `results.report.discrete_phase.sample_trajectories.start_file_write` before
the calculation and `stop_file_write` afterward, including when calculation raises an error.
Fluent's own working directory is set to `Data_export/DPM_samples`, since Sample has no output
filename argument in Fluent 2025 R1. A manifest records the files actually produced.

## Run on Windows and Fawkes

Use the updated source package and `configs/sim-8-01-08.1-09.fawkes.json` together. From the
repository root on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
callums-sim run configs/sim-8-01-08.1-09.fawkes.json --stages mesh
```

Copy the generated mesh to this path on Fawkes:

```text
~/Simulations/Results/Hose_simulations/sim-8-01-08.1-09/Case_and_data/sim-8-01-08.1-09.msh.h5
```

The existing 8-01-08-08 mesh has the same meshing settings and may instead be copied to the
new path and filename; generating a new mesh is optional. Mesh, solve and export stage functions
create the canonical result directories. The inlet profile remains at the existing portable
`Results/Hose_simulations/sim-3-04-03-05/Data_export/Profile_data/` path.

On Fawkes, from the package repository:

```bash
source .venv/bin/activate
python -m pip install -e '.[all]'
callums-sim plan configs/sim-8-01-08.1-09.fawkes.json --stages solve export plot
callums-sim validate configs/sim-8-01-08.1-09.fawkes.json --stages solve export plot
qsub hpc/sim-8-01-08.1-09-fawkes.pbs
```

The PBS template preserves the existing site modules and resources; it selects only
`solve export plot` and uses the correct `Hose_simulations` result paths. Running the config
without stage selection includes Windows meshing, so select stages explicitly on Linux.

## Outputs

```text
sim-8-01-08.1-09/
  Case_and_data/                 final case/data and separate timestep autosaves
  Animation/
    Frames/                     carrier-only animation
    Particle_velocity/          water_velocity_animation.cxa and TIFF frames
    Particle_diameter/          water_diameter_animation.cxa and TIFF frames
  Data_export/
    DPM_samples/                seven station .dpm files and sampling_manifest.json
    Contour_data/               carrier fields used for particle/flow comparisons
    Line_data/                  carrier and DPM line fields
    axial-averages.csv          exact Fluent area-weighted averages
  Results_plotting/
    Particle_analysis/          migrated plots and analysis tables
```

Sample stations are z = 1, 60, 250, 495, 1000, 2000 and 2495 mm. The recorder selects
`water_liquid_inlet`, uses sorted files, and records crossings throughout the transient run.
This is crossing data, not a particle-position snapshot for every timestep. A station may
contain just a header if no droplets reach it; the analysis reports that explicitly. Missing
station files and malformed particle rows raise an error instead of silently skipping analysis.
Existing `.dpm` files are protected: a rerun must use a fresh run directory or deliberately set
`solver.dpm_sampling.append_sample` to true. Appending combines runs and should be intentional.

## Migrated plotting methods

The analysis produces carrier and DPM line subplots, axial area-weighted-average plots and a
pressure gradient fit, carrier contours, particle speed/mass/diameter/area/volume heatmaps,
particle XY maps, kinetic energy distributions, Reynolds/Stokes diagnostics, Morsi-Alexander
drag coefficients and forces, diameter-binned statistics, per-plane summaries, and summaries
grouped by sampled flow time. Static carrier/particle overlays from the old workflow are in
their own output folder; they do not affect either particle animation. Plots are 300 DPI.

Water density (997 kg/m3), carrier viscosity (1.862341660112705e-5 Pa s), hose diameter
(0.032 m), and droplet mass flow (0.0008786124157336355 kg/s) are explicit config values.
The legacy steel defaults of 7850 kg/m3 and 0.06944 kg/s are not used for this case.

The 13 numeric sample columns and complete injection/particle identifiers are preserved in
parsed CSVs. Sample row counts are parcel crossings, not unique physical particles. The
Eulerian plane fields represent the final solution, while DPM samples span the run; relative
Re/St/Cd/drag diagnostics therefore use the final carrier snapshot. They are not exact transient
coupling measurements. The migrated `fp_drag` quantities are acceleration (m/s2), and the
legacy momentum-exchange formula is a diagnostic rather than Fluent's integrated momentum
source. The inherited Morsi-Alexander implementation extrapolates its last branch above Re=5000.

The unusual inherited droplet diameter range is unchanged from the successful base case.

To replot downloaded results without Fluent:

```bash
callums-sim run configs/sim-8-01-08.1-09.fawkes.json --stages plot
```

Replotting the old 08-08 result cannot recover `.dpm` crossings that were never recorded.
