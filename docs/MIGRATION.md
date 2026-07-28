# Migration guide

## Legacy-family mapping

| Legacy family | New category | Starting config |
|---|---|---|
| Simulation 1 and 9, nozzle-only | `nozzle` | `configs/nozzle.example.json` |
| Simulation 3–7, straight hose, particles, humidity, Thompson valve/hose | `hose` | `configs/hose.example.json` |
| Simulation 2 and 10, nozzle plus external fluid domain | `nozzle_environment` | `configs/nozzle_environment.example.json` |
| Simulation 11, nozzle/target environment | `nozzle_impinging` | `configs/nozzle_impinging.example.json` |

The Simulation 8 Thompson-valve series also maps to `hose`, but its humidity, real-gas-property, DPM,
resume, volume-report, and profile-driven boundary setup needs additional operations beyond the basic
hose template. Migrate that series only after the simple hose baseline passes on Fawkes.

## One-time repository and geometry setup

1. Keep `CallumsPhDworkpackage.code`, `Geometry`, and `Results` as siblings.
2. On Windows, open/import each current `.dsco` in Fluent Meshing and enable **Save PMDB**. Transfer
   the resulting `.pmdb` to `Geometry`; do not rename zones without updating config.
3. Create a clean virtual environment. Do not copy `configs/.venv` from the legacy tree.
4. Install with `python -m pip install -e ".[all]"`.
5. On Fawkes, verify the Ansys module and license setup with UniSQ eResearch Services.

## Migrating one simulation revision

1. Copy the closest example config and assign a stable simulation ID plus explicit mesh, solver, and
   post versions.
2. Point `geometry` at a `.pmdb` relative to `Geometry`.
3. Move every active meshing value from the legacy script into `meshing`: labels, local sizing,
   surface settings, region object, boundary layers, and volume controls. Do not copy commented-out
   alternatives.
4. Translate active solver statements in execution order into `solver.operations`. The supported
   actions are `set`, `patch`, `set_item`, `create`, `delete`, and `call`.
5. Move lines, planes, field lists, and plot definitions into `export` and `plotting`.
6. Run `callums-sim plan CONFIG` and inspect every path before `validate`.
7. Run only `mesh`. Inspect zone names, cell count, minimum orthogonal quality, skewness, boundary
   layers, and dimensional scale.
8. Run only `solve`. Confirm boundary reports before accepting the final case/data.
9. Run `export plot` and inspect field ranges for constants, NaNs, unit mistakes, and empty surfaces.
10. Compare against the legacy case using conserved mass/energy, pressure/velocity profiles, report
    histories, and DPM statistics. Increment a version whenever a scientific setting changes.

## Fluent operation examples

Set a scalar setting:

```json
{
  "action": "set",
  "path": "settings/setup/general/operating_conditions/operating_pressure",
  "value": 0.0
}
```

Select a named Fluent child with `@name`:

```json
{
  "action": "set",
  "path": "settings/setup/boundary_conditions/pressure_inlet/@pressure-inlet/momentum/gauge_total_pressure",
  "value": 783459.0
}
```

Create a material in a named-object collection:

```json
{
  "action": "set_item",
  "path": "settings/setup/materials/solid",
  "name": "Silicon-nitride_custom",
  "value": {
    "density": {"option": "constant", "value": 3194.8}
  }
}
```

Run a command:

```json
{
  "action": "call",
  "path": "settings/solution/run_calculation/iterate",
  "kwargs": {"iter_count": 500, "report": true}
}
```

Use `patch` for DPM injections or other nested states when a partial update must preserve existing
keys. Avoid the legacy pattern of assigning several incomplete dictionaries to the same setting.

## Resume and staged execution

Artifacts have deterministic names, so rerunning a later stage does not need a `specific_itteration`
path in JSON:

```bash
callums-sim run configs/hose.json --stages solve
callums-sim run configs/hose.json --stages export plot
```

For checkpoint-specific resume support, add a new solver version/config whose input case and data are
promoted into that run's canonical `Case_and_data` paths. This keeps the input immutable and records
the new provenance instead of silently pointing a config at a different simulation revision.

## Fawkes submission

Fawkes uses PBS Pro. Submit from the repository root:

```bash
qsub -v CONFIG=configs/hose.json hpc/fawkes.pbs
qstat
```

PyFluent supports scheduler allocation discovery for PBS, so leave `processor_count` as `null` unless
you intentionally want Fluent to use fewer cores than requested. Keep module names, memory, walltime,
and license directives site-specific in `hpc/fawkes.pbs`, not in simulation JSON.

