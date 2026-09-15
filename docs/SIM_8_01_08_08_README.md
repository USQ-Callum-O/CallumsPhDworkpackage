# sim-8-01-08-08: water-droplet hose case

`configs/sim-8-01-08-08.fawkes.json` is a split-stage case assembled from three reviewed
sources:

| Component | Source |
| --- | --- |
| Mesh | `sim-8-01-05-06` |
| Carrier species and turbulence models | `sim-8-01-07.2-07` |
| Discrete water-droplet setup | legacy `sim-8-07_config.json` and active 8-07 solver code |

The output run name is `sim-8-01-08-08`. The config retains all four stages so that Windows
can generate the mesh using the 05-06 meshing settings:

```powershell
callums-sim run configs/sim-8-01-08-08.fawkes.json --stages mesh
```

On Linux, explicitly select `solve export plot` to avoid reading Discovery geometry.

## What the case contains

- pressure-based, second-order transient carrier flow;
- humid-air species transport with dry air and water vapour;
- a water-vapour inlet mass fraction of `0.0072`;
- Transition SST with inlet `Intermittency, K and Omega`;
- evaporating `water-liquid` droplets injected from `dpm_injection_plane` at `z = 0.001 m`;
- two-way DPM coupling every three iterations, Saffman lift, spherical drag, and coupled heat/mass
  updates;
- a `0.0008786124157336355 kg/s` droplet flow rate, `300 K` injection temperature, and `1 m/s`
  face-normal injection velocity;
- one carrier-flow animation and one combined carrier-flow/particle animation, recorded every
  timestep; and
- the legacy DPM fields added to each line and plane CSV export.

The transient calculation uses 100 steps of `0.0025 s`, up to 250 iterations per step. The 5 s
droplet stop time therefore keeps injection active for the full 0.25 s run.

## Scientific values to review

This is a faithful code migration, not a new validation of the physical assumptions. In particular,
the inherited Rosin-Rammler distribution is:

| Parameter | Value |
| --- | ---: |
| Minimum diameter | `1.800511435229514e-7 m` (0.180 micrometres) |
| Maximum diameter | `7.202045740918058e-4 m` (720.205 micrometres) |
| Mean diameter | `8.002273045464508e-7 m` (0.800 micrometres) |
| Spread parameter | `3.5` |
| Diameter classes | `10` |

That range is unusually broad relative to the mean. Confirm these three diameters against the
intended experimental distribution before treating the run as production data. The old code did
not explicitly define particle-wall interaction behaviour, so this migration retains Fluent's
defaults. Review escape/trap/reflect behaviour if wall deposition matters.

## Required files

The config resolves both files outside the repository:

```text
Simulations/
├── CallumsPhDworkpackage.code/
└── Results/
    └── Hose_simulations/
        ├── sim-3-04-03-05/
        │   └── Data_export/Profile_data/
        │       └── streight_hose-3-05_test_plane_1300mm.prof
        └── sim-8-01-08-08/
            └── Case_and_data/
                └── sim-8-01-08-08.msh.h5
```

Keep those relative paths on the laptop and on Fawkes, or override the roots with
`CALLUMS_INPUT_ROOT` and `CALLUMS_RESULTS_ROOT`. Copy the Windows-generated mesh into this
run's `Case_and_data` directory on Fawkes. No named `source_mesh` input is required.

## Local preflight

From the repository root in WSL:

```bash
source .venv/bin/activate
python -m pip install -e .
callums-sim plan configs/sim-8-01-08-08.fawkes.json --stages solve export plot
callums-sim validate configs/sim-8-01-08-08.fawkes.json --stages solve export plot
```

`validate` checks that this run's uploaded mesh and inlet profile exist without launching Fluent.
The plan must show `solve -> export -> plot`; it must not include `mesh`.

For a short laptop smoke test, copy the config to a temporary untracked file and lower
`solver.operations` values for `time_step_count` and `max_iter_per_time_step`. Do not change
the committed production case merely to make a test faster.

## Fawkes run

Copy or synchronize the repository, the source mesh, and the inlet profile into the layout above.
From `CallumsPhDworkpackage.code`:

```bash
source .venv/bin/activate
callums-sim validate configs/sim-8-01-08-08.fawkes.json --stages solve export plot
qsub hpc/sim-8-01-08-08-fawkes.pbs
qstat
```

The case-specific PBS script selects `solve export plot`. Do not use the generic PBS script
unchanged with this all-stage config: that script would also request meshing. Review the resource
request against your allocation before submission.

Expected new output:

```text
Results/Hose_simulations/sim-8-01-08-08/
├── Case_and_data/
│   ├── sim-8-01-08-08.cas.h5
│   ├── sim-8-01-08-08.dat.h5
│   └── autosaved timestep data files
├── Animation/
│   └── Frames/
├── Data_export/
├── Results_plotting/
└── run_manifest.json
```

The final case/data filenames use only `sim-8-01-08-08`; autosaves retain their timestep suffixes,
so the final write does not overwrite them.

## Review the particle animation in Fluent

Download the complete `sim-8-01-08-08` result directory. Do not download only the final case and
data: the `.cxa` sequence and its associated frame files must remain together.

1. Find the sequence after download, for example with
   `find sim-8-01-08-08 -name 'water_droplet_animation*.cxa'`.
2. Start Fluent 2025 R1 and read `sim-8-01-08-08.cas.h5` and
   `sim-8-01-08-08.dat.h5`.
3. Open **Solution > Calculation Activities > Solution Animations** (or the Playback panel in the
   Fluent UI), read the `water_droplet_animation` `.cxa` sequence, and play its timestep frames.
4. Keep the frame files at their downloaded relative paths if Fluent prompts that a frame cannot be
   found.

The `water_droplet_scene` overlays `water_droplet_tracks`, coloured by particle diameter, on the
`flow_development_contour`. The separate `flow_development_animation` remains available for a
carrier-only comparison. Fluent's disk-backed solution-animation workflow is documented in the
[Fluent User's Guide](https://ansyshelp.ansys.com/public/Views/Secured/corp/v251/en/flu_ug/flu_ug_sec_solve_animate.html).

## Acceptance checklist

- `callums-sim validate --stages solve export plot` confirms the uploaded mesh and profile.
- The plan starts at `solve`, with no Discovery or meshing stage.
- The solver transcript reports species transport, Transition SST, and the
  `water_liquid_inlet` injection.
- Autosaved data files remain alongside the final base-named case/data pair.
- `water_droplet_animation.cxa` and timestep frames are present after the solve.
- The exported CSV headers contain `dpm-vel-mag`, `dpm-diam`, `dpm-concentration`, and
  `dpm-particles-in-cell`.

## Job 876838: inactive droplet-material container

The log shows that Fluent successfully read the 6,545,378-cell mesh and built the humid-air
mixture. It then stopped at operation 15 while accessing `setup/materials/droplet-particle`.
No calculation timestep had started.

The original migration created `water-liquid` too early. The corrected config follows the
legacy bootstrap sequence: enable DPM coupling, create the injection, atomically set a valid
surface droplet injection using `argon-liquid`, create `water-liquid` in the now-active
droplet container, and switch the injection to water before calculation. Argon is only a setup
placeholder; no timestep is calculated with it.

The memory-cache and operating-density messages in that log are warnings, not the fatal error.
