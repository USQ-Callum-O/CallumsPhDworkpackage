# sim-8-01-11-09: steel-sphere baseline and parameter changes

`configs/sim-8-01-11-09.config` contains JSON despite its requested `.config` extension.
The package accepts it directly. The baseline follows the active old
`Thomsonvalve_Sim-8-01-solver.py`, using the current 08.1-09 DPM sampling, export,
plotting and graphics workflow. Existing droplet configurations are untouched.

| Setting | Baseline |
| --- | --- |
| Carrier | NIST real-gas AIR; no species transport/evaporation |
| Turbulence | Realizable k-epsilon, standard wall functions, compressibility correction |
| Operating pressure / outlet | 0 Pa / 689476 Pa; outlet value is absolute in this convention |
| Particle | Inert `Steel-shot`, density 7800 kg/m3, Cp 500 J/(kg K) |
| Injection | Surface `wall.1.3`, total 0.06944 kg/s (249.984 kg/h) |
| Injection interval | 0.025 to 0.25 s |
| Initial particle velocity | Zero; particles accelerate under carrier-flow forces |
| Size distribution | Rosin-Rammler: min 0.25 mm, mean 0.45 mm, max 0.60 mm, spread 3.5, 10 classes |
| Drag | `spherical` on `steel_shot_inlet` |
| Wall DPM interaction | `reflect`, constant normal/tangential restitution = 1.0 / 1.0 |
| Inlet/outlet DPM interaction | `escape` |
| Calculation | 125 x 0.0025 s = 0.3125 s; up to 250 iterations per step |

## Review findings and differences from the legacy source

The old material density is 7800, while the old plotting default was 7850. This config uses
7800 consistently. Its mean diameter is 0.45 mm; the old nearby comment incorrectly said
0.55 mm. The final injection surface is `wall.1.3`, which replaced the earlier z=0.01 m
location. Check that this zone is still the intended steel injection boundary in your mesh.

The original NIST lookup pressure range was 13200-20000 Pa, outside the 689476 Pa outlet
condition. The new lookup maximum is 1000000 Pa; the minimum and temperature settings are
retained. This corrects the table range and means this is not a bit-identical reproduction.
If a later run exceeds that range, expand the table before interpreting its material properties.

The original used `mass_flow_rate.flow_rate`; this config uses `total_flow_rate` and
`scale_by_area=true` to express the intended 250 kg/h total surface injection. Confirm Fluent's
reported injection total, rather than assuming that a per-stream setting is a total rate.

The legacy compressibility and viscous-heating toggles used dictionary states; the installed
Fluent 2025 R1 API requires booleans, so both are set to `true` in this config.

The old fresh solve used 125 steps. The 400-step case in its `specific_itteration` setting
was a separate resume checkpoint. Unsteady tracking is explicitly enabled here to use the
current transient Sample recorder; the old script left that flag implicit.

The baseline explicitly disables Saffman lift, rotation, turbulent dispersion and DEM collisions.
The old steel script did not enable these features. Wall restitution is made explicit instead
of depending on whichever Fluent defaults accompany a mesh/case.

## Change the drag model

Find the operation whose path is:

```text
settings/setup/models/discrete_phase/injections/@steel_shot_inlet/physical_models/particle_drag/option
```

Its baseline value is `spherical`. For Fluent's built-in shape-factor model, change that value
to `nonspherical`, then insert this operation immediately afterward:

```json
{
  "action": "set",
  "path": "settings/setup/models/discrete_phase/injections/@steel_shot_inlet/physical_models/particle_drag/shape_factor",
  "value": 0.8
}
```

0.8 is an illustrative test input, not a calibrated value for your particles. The shape factor
is the equal-volume sphere's surface area divided by the actual particle surface area; it is 1
for a sphere and smaller for non-spherical particles. Set the drag option before the shape
factor, since that parameter is inactive for the spherical model. This represents shape through
an averaged drag correlation; it does not resolve particle geometry/orientation or add rotation.
See [Fluent non-spherical drag theory](https://ansyshelp.ansys.com/public/views/secured/corp/v252/en/flu_th/x1-62300016.7.2.html).

There is no later global drag command in this config to overwrite the injection-specific option.

## Change wall restitution

For each of `wall.1.1`, `wall.1.2` and `wall.1.3`, find the operation ending in
`/discrete_phase/reflection_coefficients`. The baseline sets:

```json
{
  "normal": {"option": "constant", "value": 1.0},
  "tangential": {"option": "constant", "value": 1.0}
}
```

For a damped test, change those numeric values, for example to normal=0.8 and tangential=0.9.
Keep `bc_type=reflect`; damping is a coefficient change within reflection, not the `trap`
boundary type. Use coefficients measured for the particle/wall material pair and relevant
impact velocities/angles for a physical model. With e_n=0.8, the normal translational kinetic
energy component retained is e_n squared = 0.64, not 0.8. See
[Fluent DPM boundary conditions](https://ansyshelp.ansys.com/public/Views/Secured/corp/v252/en/flu_ug/flu_ug_sec_discrete_bc.html).

Keep rotation disabled for this simple normal/tangential model. Fluent's rotating-particle
collision model changes the wall interaction treatment; the tangential restitution input is
not used in the same way when rotation is enabled. This baseline adds neither an erosion model
nor a discrete-element particle-particle collision model.

Give every experiment a new solver version/run name to keep its samples and outputs separate.

## Mesh and run

The geometry/meshing settings are inherited from the current hose case. You can generate the
mesh on Windows:

```powershell
callums-sim run configs/sim-8-01-11-09.config --stages mesh
```

Or reuse the current hose mesh by copying it to:

```text
Results/Hose_simulations/sim-8-01-11-09/Case_and_data/sim-8-01-11-09.msh.h5
```

The inlet profile remains the current portable sim-3-04-03-05 profile path. Local input
validation currently finds that the profile is only in the downloaded nested Fawkes folder:

```text
Results/Hose_simulations/sim-3-04-03-05/fawkes/sim-3-04-03-05/Data_export/Profile_data/streight_hose-3-05_test_plane_1300mm.prof
```

Before running locally, copy that file to the non-nested path configured in `inputs.inlet_profile`
(or change that config path to the nested copy). On Fawkes, keep the portable non-nested path
and ensure that the file is present there. Also generate or copy the mesh to the new run path
above: a successful run planner is not an input-existence check.

On Fawkes, with the updated repository and inputs in place:

```bash
source .venv/bin/activate
callums-sim plan configs/sim-8-01-11-09.config --stages solve export plot
callums-sim validate configs/sim-8-01-11-09.config --stages solve export plot
qsub hpc/sim-8-01-11-09-fawkes.pbs
```

The config retains a Windows mesh stage, so select `solve export plot` on Linux. The supplied
PBS template does this already. It retains the current site's modules and resource request.

## Sampling, graphics and interpretation

Sample recording selects `steel_shot_inlet`, the current seven station planes and `wall.1.3`
as in the legacy boundary-sampling request. `.dpm` files go into `Data_export/DPM_samples`.
Wall samples have no matching cross-section carrier CSV, so they receive particle-only plots;
they are not used to infer cross-section Reynolds/Stokes/drag values.

Graphics retain the current locally edited 08.1-09 arrangement; only the particle injection
and object names change to steel. This avoids reverting your partially working graphics fixes.
The current carrier and combined steel-particle-diameter CXA sequences are under Animation/Frames.

Post-processing uses the steel density and flow rate, but the migrated Cd/Fd routines still
apply a spherical Morsi-Alexander diagnostic to final-snapshot carrier fields with constant
viscosity 1.8e-5 Pa s. Those are approximate diagnostic plots for real-gas air. A non-spherical
solver experiment does not automatically change these Python correlations: keep that distinction
explicit or extend the analysis before treating its Cd/Fd plots as the new solver drag law.
To omit the entire derived DPM analysis temporarily, remove `plotting.dpm_analysis`; `.dpm`
sampling and normal configured surface/line plots will still run.
