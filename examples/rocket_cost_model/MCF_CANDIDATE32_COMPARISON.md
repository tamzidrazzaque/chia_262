# MCF role 2 / role 3.2 pilot comparison

The layout-matched role-3.2 pilot completed correctly on the same Saturn
platform as the accepted role-2 controls. All runs used VLEN 256, the same
AGFI/driver, the same platform digest, and input ID `605-mcf-test`.

| run | role | guest seconds | whole-boot cycles | output |
| --- | --- | ---: | ---: | --- |
| B1 | generic auto-vectorized role 2 | 98.65 | 102,720,149,072 | exact |
| B2 | generic auto-vectorized role 2 | 98.83 | 102,896,568,392 | exact |
| 3.2 pilot | Saturn-aware role 3 | 98.09 | 102,146,786,282 | exact |

Relative to B1, the pilot is 573,362,790 cycles (0.558%) lower; relative to
B2 it is 749,782,110 cycles (0.729%) lower. The two role-2 controls differ by
176,419,320 cycles (0.172%), so this is encouraging but not yet a conclusive
speedup. The next step is an order-balanced fresh repetition block with the
same image/layout contract, followed by candidate retention only if the
paired statistics remain better.

The original role-3 boot failure was caused by a non-equivalent MCF guest
layout (`inp.in`/`mcf.out` versus the accepted `input.in`/`stdout.txt`). The
layout normalization is implemented by `produce_spec_workload_bundle.py`.

## Confirmation pair

A fresh order-balanced confirmation pair also passed exact-output validation:

| run | role | guest seconds | whole-boot cycles |
| --- | --- | ---: | ---: |
| confirmation-1 | role 2 | 98.85 | 102,918,620,807 |
| confirmation-1 | role 3.2 | 90.00 | 94,075,602,392 |

The candidate is 8,843,018,415 cycles (8.592%) below this fresh role-2
control. This is a strong confirmation result, but additional order-balanced
repetitions are still required before treating 3.2 as the retained winner.
