# Saturn autonomous search loop

The integrated entry point is `saturn_adaptive_loop.py`. A private config
supplies the pinned compiler/SPEC paths, seed profiles, measured prior feedback,
manager transport and paired policy. The deployment is explicitly official
SPEC test-input screening; train/ref claims are outside this run.

Set `continuous: true` and `queue_directory` to drain all distinct queued cost
profiles, then generate further proposals from measured feedback. This mode
has no candidate-count cutoff. Previously attempted effective profiles and ELF
hashes must be imported through `prior_profiles` and `seen_executables`; queued
aliases remain on disk but do not trigger duplicate builds. New queue files are
picked up when the pending batch drains. Repeated invalid/non-novel proposals
receive three corrective attempts, then a cooldown before retrying. Provider,
compiler, correctness, and manager failures still stop the loop for diagnosis.

The earlier four-candidate run was a bounded bring-up batch. It did not consume
the larger queue. Persistent queue mode replaces that deployment; bounded mode
remains available when `continuous` is absent.

The loop schedules compiler and Codex proposal tasks through CHIA resource
labels, validates real worker/model admission before building, transfers
hash-bound bundles to the admitted Saturn manager, and runs fresh paired
controls with alternating order and confirmation thresholds. The next seed
build overlaps the current FPGA measurement. After seeds, new validated cost
profiles come from measured feedback. Duplicate ELFs bypass hardware; failed
infrastructure halts the run with private logs. Active work drains on signals.
AB/BA ordering follows actual measured candidates, independently of skipped
profiles. After validated collection, image maintenance reclaims zero blocks
while checking unchanged hashes and preserving all evidence bytes.

`saturn_adaptive_measure.py` connects the transferable bundle to the manager's
CHIA/F2 campaign. The local compiler environment reuses Python/Ray from the
owner's existing image and a shared locked GCC build root with immutable
frontend snapshots. It does not replace the installed baseline toolchain.

The following describes the earlier standalone components, retained for
diagnostics and manual campaigns:

The Saturn lane uses two private processes:

* `saturn_search_loop.py` consumes proposal JSON files, builds and validates
  immutable candidates, rejects duplicate ELFs, and dispatches only admitted
  bundles to the manager/F2 measurement hook.
* `saturn_feedback_proposer.py` watches the controller state and adds one
  deterministic, previously untested MCF-relevant cost profile after a valid
  measured candidate, but only while fewer than four proposals are pending.

The proposer writes only to the private proposal directory and to its own
memory file. It never edits controller state, compiler sources, SPEC files, or
manager configuration. A future authenticated proposal engine can replace its
profile table without changing the correctness, identity, or F2 gates.

Example private proposer invocation:

```bash
python3 -m examples.rocket_cost_model.saturn_feedback_proposer \
  --queue /private/proposals \
  --state /private/controller-state.json \
  --memory /private/feedback-memory.json \
  --max-pending 4 --watch
```

The proposal budget remains bounded by the queue and by the manager/F2 worker
capacity. A positive cycle result is only a candidate improvement; it still
requires paired fresh repetitions and final correctness/reference validation.
