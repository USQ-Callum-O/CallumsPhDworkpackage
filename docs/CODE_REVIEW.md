# Legacy simulation code review

## Scope and method

The audit covered the complete first-party tree under `Nozzle_simulation_code`: 264 Python files
(120,424 lines) and 112 JSON files. The embedded `configs/.venv` was excluded as third-party code;
it contains another 5,738 Python files. `tools/audit_legacy.py` parsed every first-party Python AST,
loaded every JSON file, checked configured input paths, counted lifecycle/error-handling patterns,
and identified exact duplicate content. Representative scripts from every meshing, solver, export,
and plotting family were then reviewed semantically.

The generated `legacy-audit.json` is deliberately ignored by Git because it contains absolute local
paths. Re-run the audit whenever legacy files change.

## Highest-priority findings

### 1. The current configuration is not portable or reproducible

All 109 active simulation configs contain absolute `C:/Users/U1173289/...` paths. They encode script
locations and output locations rather than simulation parameters, while the scientifically important
mesh sizes, models, material properties, boundary values, time steps, and iteration counts remain
hard-coded in Python. Moving a config to Linux therefore neither locates its inputs nor fully explains
the simulation it represents.

The active configs contain 86 missing input references; including archived configs, the full audit
finds 87. Active-tree examples include 9 missing geometry scripts, 2 missing meshing scripts, 3
missing solver scripts, 36 missing result/export/plot scripts, 16 missing resume scripts, and 18
missing resume data files. A config can be syntactically valid but impossible to execute.

Resolution in the new package: JSON stores parameters, not Python paths; roots are config-relative or
environment-overridden; inputs are validated before allocating Fluent; and each run receives a
hash-bearing manifest.

### 2. Linux meshing cannot consume the current `.dsco` geometry directly

Every active geometry input exists, but it is a Discovery `.dsco` file. Ansys explicitly documents
`.dsco` as Windows-only in Fluent Meshing and recommends generating an intermediary `.pmdb` on
Windows for Linux workflows. This is a hard Fawkes migration blocker, not just a path-format issue.

Resolution: the package rejects `.dsco` for Linux meshing with an actionable error. The geometry
must be exported/transferred as `.pmdb` (or another verified Linux-supported format) first.

### 3. Modules execute full simulations when imported

204 of 264 Python files contain executable top-level statements; 195 read `sys.argv`. This prevents
safe imports, unit tests, introspection, notebook reuse, and composition. It is also why nine almost
identical `run_simulationX.py` files are needed.

Resolution: all new modules are import-safe. `runner.run()` owns sequencing, while reusable stage
functions accept a validated config and artifact paths.

### 4. Fluent sessions and licenses are not reliably released

Of 180 files that launch Fluent, 54 contain no session `.exit()` call. None of the legacy launch
patterns consistently wraps the session in `try/finally`. Any exception between launch and the final
line can strand a process/license. `Nozzle-impinging_Sim-11-03.1-solver.py` launches two solver
sessions consecutively and only retains the second reference.

Resolution: one context-managed session is launched per stage and closed in `finally`, including
after errors. A unit test enforces this behavior.

### 5. Errors are widely suppressed

The audit found 535 `except Exception` handlers across 106 files plus 23 bare `except` handlers.
Many silently `pass` while creating report definitions, assigning wall properties, or exporting data.
This can turn a failed setup into a completed-looking run with missing physics or output.

Resolution: the operation engine is fail-fast and reports the operation index, action, and Fluent
settings path. Optional meshing tasks are the only explicitly skippable workflow items.

## Concrete correctness and maintainability defects

- `configs/run_simulation8.py` loads one default config name but passes a different config path to
  child scripts. The runner files also contain manually commented stage selections, so source edits
  are required to choose a workflow.
- `PyFluent/Impinging_Sim-1_code/Nozzle-impinging_Sim-11-03.1-solver.py` launches Fluent twice,
  potentially consuming an extra process/license and leaking the first session.
- `PyFluent/Meshing/waste_code.py` has a real Python syntax error caused by an unescaped Windows
  `\U...` path.
- The DPM scripts assign `dpm_state.interaction` twice with different partial dictionaries. Depending
  on PyFluent state semantics, the second assignment can replace rather than augment the first. One
  merged state update is safer and auditable.
- Several configs cross-reference a different simulation revision. For example, the 9-03.3 config
  names a 9-03.2 mesh/output and a 9-02 specific iteration. This makes provenance ambiguous even if
  the paths happen to exist.
- `specific_itteration` and `Poastprocessing` are pervasive misspellings now embedded in APIs/paths.
  Renaming these in place would break existing files, so the new schema replaces them with canonical
  artifact paths rather than perpetuating aliases.
- Solver scripts call `os.chdir()` to DPM sample directories. That changes process-global state and
  makes every later relative path context-dependent.
- Multiple scripts use both `solver_session.setup...` and `solver_session.settings.setup...` in the
  same file. Coupled with no dependency pin, upgrades can fail halfway through setup.
- `processor_count=4` is hard-coded throughout meshing and solving. On Fawkes this can underuse an
  allocation or disagree with scheduler resources. The new default omits the argument so PyFluent can
  inspect PBS allocation data.
- Some exporters explicitly continue when no `.dat` file is found even though exported fields may
  then be constant or invalid. The new exporter requires both case and data.
- Most runs terminate after a fixed number of iterations/time steps. Reports are often created, but
  there is no shared programmatic convergence acceptance criterion before writing final artifacts.
- The plotting family contains generated copies up to 3,606 lines. Seven current plotting files are
  exact 1,339-line copies. Plot definitions and input paths should be data, not copied modules.
- 26 exact duplicate groups exist even before considering near-duplicates. Examples include identical
  meshing files under different simulation names and four identical nozzle-fluid result scripts.
- The embedded `.venv` is under `configs/`. It adds thousands of machine-specific third-party files
  and must not be committed or transferred as the package environment.

## Scientific validation risks retained for user review

The refactor can preserve values and execution order, but it cannot certify the physical model. The
four example configs are therefore marked `scientific_review_required`. Before accepting a migrated
result, verify at least:

- gauge versus absolute pressure conventions with `operating_pressure = 0`;
- inlet/outlet orientation and zone names after Linux `.pmdb` import;
- the use of the same high gauge pressure at both hose inlet and outlet in the straight-hose family;
- material units, especially molecular weight in kg/kmol;
- wall material/thermal assignments and roughness units;
- turbulence model and near-wall treatment against achieved y+;
- DPM material, size distribution, mass flow, injection timing, coupling interval, and sampling;
- mesh independence, conservation, residual/report convergence, and time-step independence;
- whether every exported field is available and nonconstant after loading the data file.

## Why the new structure is smaller than the proposed folder tree

Separate `MeshingX.py`, `solverX-0.1.py`, and exporter copies inside every domain would recreate the
current duplication. The package instead has one implementation per stage and domain-specific public
entry points. Version identifiers belong in config and artifact metadata, not Python filenames (where
hyphens also prevent normal imports). This keeps the four-domain organization while making each
simulation a reviewable data record.

