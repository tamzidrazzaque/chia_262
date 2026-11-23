# Review repair status

Implemented after the second review:

* Stage directory creation belongs to the staging CLI.
* Collection uses its directory/result.json contract and a separately delimited
  receipt transfer, tolerating manager SSH-agent startup banners.
* Image/result discovery is constrained to the staged workload name.
* Installed descriptors point at hash-verified admitted boot/rootfs bytes.
* Each manager task receives a fresh preflight.
* Preparation, receipt bundle and ELF identities are compared before scoring.
* State is persisted before expensive work; interrupted dispatch cannot silently
  rerun, recovered receipts can complete it, and infrastructure errors stop work.
* An exclusive controller lock prevents concurrent state mutation. Chia task
  alert timeouts drain the original remote task before disconnecting.
* Measured-feedback proposals use CHIA's existing CodexLLM wrapper, bounded
  numeric history, schema validation and duplicate-profile rejection.
  A durable source reservation and proposer lock prevent duplicate publication
  after a crash. The Codex sandbox and prompt constrain tool access; builtin
  tools are not claimed to be disabled by passing an empty MCP tool list.
* CHIA bridge tasks return data, check shared mounts/configuration, require
  advertised resources and pin their workers. MCF screening is benchmark-aware.

Additional implementation and deployment:

* The existing manager Ray environment now hosts a singleton Saturn resource.
  A real Chia task successfully transported and reconstructed the private SPEC
  bundle and verified its hashes (`saturn_artifact_pilot.py`).
* `SaturnBundle` transfers workload bytes between workers without shared mounts.
  FireMarshal image construction remains on the admitted manager.
* `saturn_paired_campaign.py` supplies a bounded producer/consumer policy with
  fresh AB/BA controls, thresholds, confirmation repeats, optional ref validation,
  measurement keys, and persisted evidence. The live CLI packages existing
  bundles; compiler rebuilding can be connected via its preparation callback.
* The Chia hardware pilot passed exact correctness and collection at
  104,748,971,252 whole-boot cycles. The fresh pair also passed: role 2 measured
  103,315,564,277 cycles and the int_stmt=8 candidate measured 104,572,551,932.
  The candidate regressed about 1.22% and was not selected. This is test-input
  screening, not a repeatability or generalization claim.
* Pilot receipts publish atomically, failures publish a terminal record, and
  the gate checks failures and a bounded deadline. Paired progress now has a
  hash-verified feedback schema bridge, excluding held-out reference samples.

Still pending, and not claimed as validated:

* Connect the compiler preparation callback to an admitted compiler worker.
  A user-owned existing Docker image was verified to contain Python 3.10.19
  and Ray 2.54.0; the other user's visible workers are not used.
* Confirm improving candidates with fresh repetitions; the first candidate
  regressed and correctly did not enter confirmation.
* Expand validated bundles to train/ref inputs before train/ref optimization.
* Validate cache reuse; current measurements deliberately use fresh controls.
* Validate an authenticated Codex proposal call and end-to-end CHIA/F2 pilot.

The original role-3.2 receipt was located on the manager and copied privately.
Its cycles, proposal, receipt hash, and source identity were restored to the
private controller history from that receipt and the compiler manifest. A historical
single measurement cannot replace fresh paired confirmation.

The old watcher/proposer remain stopped. The replacement paired controller is
completed its first bounded paired campaign. Further compiler/model-driven
iterations need the compiler and authenticated proposal-worker deployment.
