# Resume the three interrupted Fluent jobs

The new `resume` command loads the autosaved case **and** its associated data,
checks the restored time step and flow time, and calculates only the remaining
steps. It does not replay initialization, species patches, injection creation,
or wall-film initialization. Export and plotting run after the solver reaches
the configured target and writes the canonical final case/data pair.

## Checkpoints found in the supplied results

| Run | Saved step | Saved time (s) | Target step | Target time (s) | Steps remaining |
| --- | ---: | ---: | ---: | ---: | ---: |
| sim-8-01-08.2.1-09 | 50 | 0.125 | 500 | 1.25 | 450 |
| sim-8-01-09.3.1-07 | 125 | 0.3125 | 200 | 0.5 | 75 |
| sim-8-01-11.0.2-09 | 50 | 0.125 | 125 | 0.3125 | 75 |

These targets come from `solver.operations`, not the descriptive notes. In
particular, the 08.2.1 config actually specifies 500 steps, despite its notes
mentioning longer durations. No physics config edits or copies are needed.
All three original local configs match the hashes in their run manifests.

## Upload and submit

Upload `HPC_resume_update_2026-11-09.zip` into your existing HPC package root,
then extract it there. It contains the updated CLI and runner, the new
`src/callums_simulation_package/stages/resume.py`, three PBS jobs, this guide,
and resume tests. It does not contain or replace simulation results or configs.

```bash
cd "$HOME/Simulations/CallumsPhDworkpackage"
unzip -o HPC_resume_update_2026-11-09.zip

qsub hpc/sim-8-01-08.2.1-09-resume-fawkes.pbs
qsub hpc/sim-8-01-09.3.1-07-resume-fawkes.pbs
qsub hpc/sim-8-01-11.0.2-09-resume-fawkes.pbs
```

Submit from the package root, where `src`, `configs`, and `.venv` reside.
Each job uses the existing Python/Ansys modules and virtual environment, and
sets `PYTHONPATH` to the uploaded `src`, so reinstalling the package is unnecessary.
The default results root is `$HOME/Simulations/Results`.

Keep each run's `Case_and_data/Autosave` directory, including the `.flprj`,
`.cas.h5`, and `.dat.h5` files, on the HPC. The `.flprj` records which case belongs
to each data file. The script searches it and all subsequent resume autosave
subdirectories, choosing the highest saved step available at submission time.
It checks file presence/size during preflight; Fluent must successfully load
the full checkpoint before calculation starts. A corrupt newest checkpoint
causes failure, not a silent rollback.

Jobs request 13 CPUs, 128 GB, and 72 hours using the existing queue/project.
The first two launch Fluent with 12 solver processes and the steel run uses 8.
For 09.3.1 this makes the original conflicting `processor_count=8` and `-t12`
settings consistently 12 at launch, without modifying the saved physics config.
`I_MPI_FABRICS=shm` and headless plotting are retained.

## If another walltime limit is reached

Resubmit the **same resume PBS file** after the previous job ends. Each attempt
autosaves every five time steps into its own directory and retains its latest
three data checkpoints there. Original autosaves and earlier attempt directories
remain intact. This limits per-attempt storage while reducing lost computation.
The jobs do not automatically submit further jobs; more than one allocation may
be needed, especially for the 450 remaining water-droplet steps.

A per-run `flock` prevents simultaneous use of these resume jobs. Do not run an
original solver job or another writer against the same results directory.

Optional submission overrides:

```bash
# Change the interval (in time steps), if checkpoint I/O is too expensive.
qsub -v AUTOSAVE_FREQUENCY=10 hpc/sim-8-01-08.2.1-09-resume-fawkes.pbs

# Explicit rollback if a later saved pair is damaged; use a step still on disk.
qsub -v CHECKPOINT_STEP=100 hpc/sim-8-01-09.3.1-07-resume-fawkes.pbs
```

The executable target remains unchanged: setting the remaining step count does
not add another full 500/200/125 steps. Restored and final time/step values are
checked, and premature solver termination is recorded as failure.

## Particle samples and animations

For the two runs with DPM sampling, each resumed calculation moves the existing
`Data_export/DPM_samples` directory, including parallel rank files, into
`Resume_history/<attempt>/DPM_samples` before starting new sample files.
Appending would duplicate crossings recorded after the checkpoint and can also
mix unflushed output from the killed job. No old samples are deleted.

**Particle sampling plots/statistics after resumption cover only the latest
resumed interval**, not the complete history from time zero. The active sample
folder contains `resume_interval.json` with its starting time and archive path.
Earlier samples remain available for a separate merge that accounts for restart
overlap and any incomplete rank files. This script deliberately does not claim
that a complete particle history can be recovered from a field checkpoint.
The carrier field and saved transient particle state continue from the loaded
checkpoint. Animation frames from each resumed attempt go to a separate
`Animation/Frames/<attempt>` folder.

## Preflight and post-processing

The PBS jobs run this read-only check before launching Fluent:

```bash
source .venv/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export CALLUMS_RESULTS_ROOT="$HOME/Simulations/Results"
python -m callums_simulation_package resume \
  configs/sim-8-01-08.2.1-09.fawkes.json --processors 12 --dry-run
```

If solving completes but export/plot fails or runs out of allocation, run only
those stages in an allocated job with the same modules/environment:

```bash
python -m callums_simulation_package run \
  configs/sim-8-01-08.2.1-09.fawkes.json --stages export plot
```

Substitute the appropriate config for either other run. The existing manifest
hash check is preserved; do not delete the manifest to bypass a config mismatch.
Use the exact original config that created the checkpoint.

Local verification covers the real project-file metadata/config hashes and
mocked Fluent behavior for checkpoint selection, remaining steps, initialization
avoidance, sample preservation, and failure handling. Actual checkpoint loading,
solver continuation, and cluster submission require Fluent on the HPC and have
not been executed locally.

The eight resume tests and Bash syntax checks for all three PBS files passed.
The broader local suite ran 36 tests with 31 passing and five unrelated issues:
an existing test imports a missing `_particle_fields` helper, two tests require
`matplotlib` absent from the available test interpreter, one expects a missing
animation `window_id`, and one expects 22 flow-summary configs where there are
now 30. Those existing tests/configs were not changed by this update.

Reference: [Ansys Fluent 2025 R1 case/data restart documentation](https://ansyshelp.ansys.com/public/Views/Secured/corp/v251/en/flu_ug/flu_ug_CaseDataFiles.html).
