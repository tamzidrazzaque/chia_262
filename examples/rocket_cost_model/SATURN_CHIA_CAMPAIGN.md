# Saturn campaign on CHIA

The repository already contains the reusable CHIA preparation graph in
[`roles_123_chia.py`](roles_123_chia.py). It uses `ChiaFunction`/Ray to run
immutable compiler construction, SPEC validation, QEMU correctness checks, and
RVV ELF audits. That graph is the preparation side of the Saturn experiment;
it should be reused rather than duplicated in shell hooks.

## Ownership boundary

CHIA should own:

* compiler-worker placement and content-addressed GCC snapshots;
* role-1/role-2/role-3 SPEC builds and independent output validation;
* QEMU correctness screening and RVV instruction audits;
* FireMarshal artifact creation and workload identity/fingerprinting;
* bounded proposal history, retries, resource locks, and resumable progress.

The only Saturn-specific adapter should be a CHIA task with the
`firesim_fpga` resource that accepts a validated `FireMarshalArtifact`, transfers
it to the already admitted Saturn manager, invokes its native manager wrapper,
and returns the sanitized cycle receipt. It must not rebuild the driver, image,
compiler, or SPEC source.

## Migration sequence

1. Run `roles_123_chia.py` inside the pinned CHIA/Ray environment and verify its
   private role artifacts for `605.mcf_s`.
2. Replace the current `saturn_prepare_hook.py` compiler/SPEC portion with that
   graph. Keep the existing manifest, ELF identity, and exact-output gates.
3. Implement the Saturn F2 task as the one CHIA resource boundary described
   above, reusing the existing manager-side `saturn_measure_hook.py` only as a
   temporary transport implementation.
4. Move the controller to the BOOM campaign pattern: one producer prepares the
   next candidate while one Saturn F2 consumer measures the current candidate.
5. Keep proposal generation separate. The existing deterministic proposer can
   be replaced by `ClaudeCodeLLM` (matching the BOOM branch) or an OpenAI
   Responses/Agents backend; neither proposal backend gets shell or manager
   access.

## Environment gate

This graph must run in the CHIA worker environment with Ray and the configured
resource labels. The repository shell Python currently lacks Ray, so running
the graph from the local research shell is intentionally rejected rather than
silently falling back to a second infrastructure implementation.

The current shell controller remains active only as a bounded transition path
while this CHIA campaign is validated. It must not be used concurrently with a
CHIA F2 controller on the same worker.

## Implemented scheduling adapter

`saturn_chia_tasks.py` exposes preparation on `riscv_build` and manager transport
on a singleton `saturn_manager` resource, with automatic retries disabled. It
connects to an existing Ray cluster only. Workers must share the private work
directory and have worker-local SATURN environment configuration. Substitute
these commands for the controller hooks after provisioning those resources:

```text
python -m examples.rocket_cost_model.saturn_chia_tasks prepare
python -m examples.rocket_cost_model.saturn_chia_tasks measure
```

This first adapter reuses the admitted preparation/transport implementations;
it does not yet provide BOOM's producer/consumer overlap or full artifact
transport. Do not describe the migration as complete until a real Chia task
has passed on the configured workers. `chia.models.codex.CodexLLM` is already
available for the eventual proposal stage; no new API integration is needed.
