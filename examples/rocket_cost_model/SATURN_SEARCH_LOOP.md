# Saturn-aware role-3 search loop

This is the bounded loop for automatic vectorization. Role 1 is a one-time
scalar reference; role 2 is the frozen stock-GCC auto-vectorized control; role 3
is the only iterative family.

## Per-candidate contract

For each proposal, in order:

1. Validate the bounded vector-cost proposal with `vector_cost_model.proposal`.
2. Build an immutable, content-addressed GCC candidate.
3. Build the unchanged-SPEC MCF executable and validate exact output locally.
4. Audit the ELF for RVV and record compiler/ISA hashes.
5. Produce the private Saturn bundle. For `605.mcf_s`, the producer now fails
   closed unless the guest contract is exactly `input.in`, `./program input.in`,
   `stdout.txt`, and `605-mcf-test`.
6. Admit and construct a fresh 2-GiB FireMarshal image; verify the image and
   run fresh platform preflight.
7. Dispatch one fresh F2 role-3 run and collect exact output, clean shutdown,
   guest time, and whole-boot target cycles.
8. Dispatch a fresh role-2 control with the same platform, input, image size,
   and timing scope. Alternate order across pairs.
9. Reject on any correctness, RVV, boot, collection, or identity failure.
10. Retain a candidate only after the predeclared repetition block shows an
    improvement over role 2; otherwise record it and move to the next proposal.

## Current state

Candidate 3.2 passed the first layout-matched pilot. Its confirmation run is
currently in progress. The next action after completion is the fresh role-2
control, followed by paired acceptance accounting. No candidate 3.3 should be
generated until that pair is recorded.

The CHIA graph (`roles_123_chia.py`) handles candidate preparation and local
gates. The protected Saturn manager lane handles image admission and F2
execution; its receipts are the only source for performance claims.
