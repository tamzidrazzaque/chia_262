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
* Measured-feedback proposals use CHIA's existing CodexLLM wrapper, bounded
  numeric history, schema validation and duplicate-profile rejection.
* CHIA bridge tasks return data, check shared mounts/configuration, require
  advertised resources and pin their workers. MCF screening is benchmark-aware.

Still pending, and not claimed as implemented:

* Register and validate actual CHIA worker resources and mounts.
* Move the transitional shared-path hooks to transferable FireMarshal artifacts.
* Adopt BOOM's producer/consumer overlap and validated measurement caches.
* Run worker-specific paired fresh baselines, order-balanced repetitions,
  confirmation thresholds and train/ref holdout policy.
* Validate an authenticated Codex proposal call and end-to-end CHIA/F2 pilot.

The original role-3.2 receipt was located on the manager and copied privately;
historical import must preserve its source identity and evidence. A historical
single measurement cannot replace fresh paired confirmation.

The old watcher/proposer were stopped before these changes. No replacement
controller should be described as live until worker admission and the pilot pass.
