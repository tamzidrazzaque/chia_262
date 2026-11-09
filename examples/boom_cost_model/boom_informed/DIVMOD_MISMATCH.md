# BOOM-informed divmod selection mismatch

Stock GCC 15.1 `-mtune=rocket` expands constant division to a `mulhu`
reciprocal sequence because `int_div` costs are `COSTS_N_INSNS(33/65)`.
`-mtune=generic-ooo` and `-mtune=xiangshan-nanhu` keep `div`/`rem` because
their `int_div` costs are `COSTS_N_INSNS(6/6)`. The
`use_divmod_expansion` flag is false for all three; profitability comes from
`expand_divmod` cost comparisons.

This matches the SPEC `505.mcf_r` `suspend_impl` opcode difference observed
earlier (rocket: `mulh`; OOO/Xiangshan: `div`+`rem`).

Anish’s experimental MegaBOOM `boom.md` schedules integer divide at 34/66
cycles but still seeds `int_div=[6,6]`, so selection and scheduling disagree.
See `/scratch/trazzaque/SLICE/cost-model-out/BOOM_COST_MODEL_RESEARCH_UPDATE.md`
for the full team landscape, estimates, and FireSim F2 next step.

```bash
./reproduce_divmod_decision.sh
```
