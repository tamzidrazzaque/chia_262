# Saturn/Rocket iterative-MulDiv replay fix

The accepted Rocket source derives `ctrl_killm` from vector replay signals but
derives `div.io.kill` from the narrower `killm_common`. Consequently, an
iterative scalar MulDiv request accepted in EX can survive a Saturn vector-side
replay and later write back after the scalar instruction is replayed.

`rocketcore_muldiv_replay_kill.patch` adds the missing vector/FPU replay terms
to the MulDiv cancellation condition. The existing `Multiplier.scala` already
returns to `s_ready` when `io.kill` is asserted, so no MulDiv datapath change is
needed.

Validation required before claiming a hardware fix:

1. Apply this patch to the exact pinned Rocket source in a separate development
   worktree; do not modify the accepted platform checkout.
2. Run Rocket/Chisel RTL tests and a directed replay test covering an accepted
   scalar multiply followed by vector memory replay.
3. Build a new Saturn/FireSim FPGA image and matching driver from that source.
4. Repeat the RVV gate, the original replay controls, and the MCF/NAB pilot.
5. Keep the old AGFI/driver and all role-2 evidence frozen for comparison.
