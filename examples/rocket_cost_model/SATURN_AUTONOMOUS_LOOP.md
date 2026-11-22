# Saturn autonomous search loop

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
