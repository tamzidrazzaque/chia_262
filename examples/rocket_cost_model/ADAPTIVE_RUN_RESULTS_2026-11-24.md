# Adaptive MCF and NAB run results

Checkpoint recorded 2026-11-24 21:22 PST. This is the sanitized, version-controlled summary. Licensed SPEC payloads, executables, UART, raw manager logs, credentials, worker addresses, and private host details remain outside Git.

## MCF

Historical valid paired screening results carried into the current adaptive loop (positive reduction means fewer target cycles):

| Candidate | Cost profile | Role-2 control cycles | Candidate cycles | Reduction |
|---|---|---:|---:|---:|
| 3.10 | `{"int_stmt":8}` | 103,315,564,277 | 104,572,551,932 | -1.217% |
| 3.2001 | `{"scalar_to_vec":4}` | 102,742,201,487 | 102,146,786,282 | +0.580% |
| 3.3009 | `{"int_stmt":2,"scalar_to_vec":4}` | 102,742,201,487 | 102,565,782,167 | +0.172% |
| 3.3016 | `{"int_stmt":2,"scalar_to_vec":4,"vec_to_scalar":3}` | 102,852,463,562 | 104,682,814,007 | -1.780% |
| 3.3017 | `{"int_stmt":2,"scalar_to_vec":4,"vec_to_scalar":2}` | 102,742,201,487 | 104,682,814,007 | -1.889% |
| 3.3019 | `{"scalar_load":2,"scalar_to_vec":4}` | 102,742,201,487 | 102,742,201,487 | +0.000% |
| 3.3020 | `{"scalar_store":2,"scalar_to_vec":4}` | 102,808,358,732 | 102,631,939,412 | +0.172% |
| 3.3023 | `{"scalar_store":4,"scalar_to_vec":4}` | 102,918,620,807 | 101,793,947,642 | +1.093% |
| 3.3042 | `{"int_stmt":2,"scalar_store":4,"scalar_to_vec":4}` | 103,337,616,692 | 105,145,914,722 | -1.750% |
| 3.3045 | `{"scalar_int_stmt":2,"scalar_store":4,"scalar_to_vec":4}` | 103,514,036,012 | 104,903,338,157 | -1.342% |

No MCF candidate is a confirmed winner. The best listed screening pair is `3.3023` at 1.093% lower cycles; the configured confirmation threshold is 2%. The profiles that produced signal-11 guest failures remain excluded: `scalar_to_vec=4, scalar_store=5` and `scalar_to_vec=4, scalar_store=7`.

### Current MCF recovery status

- The prior `3.3057` attempt did not reach its candidate measurement. The fresh role-2 control hit an 1,800-second watchdog; previously successful MCF controls took about 2,452 seconds. This is a timeout, not a workload correctness result.
- Recovery attempt `3.3058` did not dispatch to F2: manager preflight used a stale worker address and strict SSH rejected it. AWS confirmed the assigned instance ID was still the same worker; the replacement address had the same ED25519 key as the previously pinned key. The private platform endpoint and known-hosts record were refreshed, then read-only preflight passed.
- The active recovery loop is `3.3059`, retrying the same unmeasured cost profile. Its per-guest limit is 2,952 seconds (500 seconds beyond the observed ~2,452-second successful runtime). At this checkpoint the fresh role-2 control is preparing for hardware execution; no new MCF cycles are claimed.

## NAB

Completed fresh paired screening measurements:

| Candidate | Cost profile | Role-2 control cycles | Candidate cycles | Reduction |
|---|---|---:|---:|---:|
| 3.5420 | `{"align_load":14,"align_store":2}` | 37,665,524,822 | 37,003,952,372 | +1.756% |
| 3.5423 | `{"align_load":19,"align_store":2}` | 37,665,524,822 | 36,981,899,957 | +1.815% |
| 3.5427 | `{"align_load":16,"align_store":2,"scalar_store":2}` | 37,665,524,822 | 36,981,899,957 | +1.815% |
| 3.5428 | `{"align_load":16,"align_store":2,"scalar_load":2}` | 37,665,524,822 | 36,981,899,957 | +1.815% |
| 3.5431 | `{"align_load":16,"align_store":2,"scalar_to_vec":2}` | 37,665,524,822 | 36,981,899,957 | +1.815% |
| 3.5432 | `{"align_load":20,"align_store":2}` | 37,665,524,822 | 36,981,899,957 | +1.815% |
| 3.5442 | `{"align_load":16,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |
| 3.5443 | `{"align_load":16,"align_store":2,"int_stmt":2,"scalar_store":3}` | 37,665,524,822 | 37,753,734,482 | -0.234% |
| 3.5446 | `{"align_load":15,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |
| 3.5447 | `{"align_load":17,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |
| 3.5451 | `{"align_load":16,"align_store":2,"int_stmt":2,"scalar_load":2,"scalar_store":2}` | 37,665,524,822 | 37,003,952,372 | +1.756% |
| 3.5456 | `{"align_load":16,"align_store":2,"int_stmt":2,"scalar_store":2,"scalar_to_vec":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |
| 3.5458 | `{"align_load":14,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |

No NAB winner is confirmed; the best paired reductions are about 1.874%, below the 2% confirmation threshold. The loop has 13 completed paired measurements and skipped 26 duplicate executables. For `3.5459`, one role-3 sample was collected at 36,959,847,542 cycles; its role-2 control is now active, so the pair is incomplete and this sample is not a standalone performance result. The live monitor showed an active driver and no fatal UART evidence.

## Persistence and evidence boundaries

- Full local controller states, configurations, and JSON receipts are retained under the private `/scratch/trazzaque/spec-loop/` run directories.
- A permission-restricted checkpoint snapshot with SHA-256 manifest was saved outside the repository under checkpoint ID `20261124-212245-PST`.
- This document is the Git-pushed sanitized record. It contains no licensed SPEC files, executable binaries, raw UART, raw manager logs, credentials, private worker addresses, or manager hostnames.
- Live run directories continue to update. Future measurements are not included until the controller records them; this checkpoint does not imply that future results have already been pushed.
