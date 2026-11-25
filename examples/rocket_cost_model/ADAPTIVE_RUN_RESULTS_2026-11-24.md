# Adaptive MCF and NAB run results

Checkpoint updated 2026-11-25 08:27 PST. This is the sanitized, version-controlled summary. Licensed SPEC payloads, executables, UART, raw manager logs, credentials, worker addresses, and private host details remain outside Git.

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
- Recovery candidate `3.3059` never ran. Its role-2 control produced a verified early kernel panic before the guest-job marker. The panic UART hash and all sample identity fields matched, but the configured `platform_sha256` was stale (`326ab8…`) while the refreshed platform lock and staged evidence used `76f8e2…`; this was the only identity mismatch, so the retry evidence was rejected and the controller stopped. No MCF cycles were collected for this candidate.
- The MCF watchdog was raised to 2,952 seconds, 500 seconds beyond the observed ~2,452-second successful runtime. The separate failure above is a boot panic and identity-binding mismatch, not another timeout. The blocked output was preserved rather than resumed in place.

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
| 3.5459 | `{"align_load":13,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |
| 3.5461 | `{"align_load":11,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |
| 3.5462 | `{"align_load":10,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 37,003,952,372 | +1.756% |
| 3.5465 | `{"align_load":16,"align_store":2,"int_stmt":2,"scalar_int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 37,731,682,067 | -0.176% |
| 3.5469 | `{"align_load":19,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |
| 3.5470 | `{"align_load":16,"align_store":2,"int_stmt":2,"scalar_fp_stmt":2,"scalar_store":2}` | 37,665,524,822 | 37,312,686,182 | +0.937% |
| 3.5473 | `{"align_load":20,"align_store":2,"int_stmt":2,"scalar_store":2}` | 37,665,524,822 | 36,959,847,542 | +1.874% |

No NAB winner is confirmed; the best paired reductions are about 1.874%, below the 2% confirmation threshold. Across the 20 completed pairs, the role-2 control was 37,665,524,822 cycles each time. With `align_store=2`, `int_stmt=2`, and `scalar_store=2`, `align_load` values 11 through 20 repeatedly produced 36,959,847,542 cycles; moving to 10 produced 37,003,952,372. This is a measured plateau in the current search, not evidence of additional benefit from those nearby profiles. `scalar_store=3` and `scalar_int_stmt=2` regressed; `scalar_fp_stmt=2` retained only a 0.937% reduction. The best result misses the 2% screen by 47,633,217 cycles.

The loop skipped 35 duplicate executables. Candidate `3.5475` did not run: its role-2 control hit the same classified early Linux interrupt panic on three fresh boots, with no guest-job exit marker. The controller correctly stopped after exhausting its configured retry budget. No cycle data from `3.5475` is valid.

## Current controller and worker status

Both controllers are stopped in blocked states: MCF on the retry-identity mismatch above, NAB on three role-2 early-boot panics. Read-only preflight then passed on both assigned workers: the instances were idle and still had the accepted Saturn AGFI, shell, SDK and driver. These checks show the workers are available; they do not resolve the intermittent guest boot panic.

## Persistence and evidence boundaries

- Full local controller states, configurations, and JSON receipts are retained under the private `/scratch/trazzaque/spec-loop/` run directories.
- A permission-restricted checkpoint snapshot with SHA-256 manifest was saved outside the repository under checkpoint ID `20261125-082704-PST`.
- This document is the Git-pushed sanitized record. It contains no licensed SPEC files, executable binaries, raw UART, raw manager logs, credentials, private worker addresses, or manager hostnames.
- Live run directories continue to update. Future measurements are not included until the controller records them; this checkpoint does not imply that future results have already been pushed.
