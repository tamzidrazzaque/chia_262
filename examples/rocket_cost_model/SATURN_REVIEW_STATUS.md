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
* The hardware pilot is executing its admitted manager setup path. The paired
  controller waits for an exact candidate/worker/platform correctness receipt
  before dispatch. Deployment does not yet establish a passing hardware result.

Still pending, and not claimed as validated:

* Connect the compiler preparation callback to an admitted compiler worker.
  A user-owned existing Docker image was verified to contain Python 3.10.19
  and Ray 2.54.0; the other user's visible workers are not used.
* Complete the live end-to-end pilot and fresh paired confirmation.
* Expand validated bundles to train/ref inputs before train/ref optimization.
* Validate cache reuse; current measurements deliberately use fresh controls.
* Validate an authenticated Codex proposal call and end-to-end CHIA/F2 pilot.

The original role-3.2 receipt was located on the manager and copied privately.
Its cycles, proposal, receipt hash, and source identity were restored to the
private controller history from that receipt and the compiler manifest. A historical
single measurement cannot replace fresh paired confirmation.

The old watcher/proposer remain stopped. The replacement paired controller is
live behind its exact pilot receipt gate, and has no new performance result yet.
