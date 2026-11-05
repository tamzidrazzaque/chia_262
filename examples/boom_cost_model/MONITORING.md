# Continuous-loop host monitoring

The optional `watchdog` module supports a deterministic host monitor. It does
not create a scheduled LLM session or send scheduled messages into a chat.

Run it from the same guarded environment as the controller, using a private
JSON config containing `root`, `initial_run`, `python`, `environment`,
`tmux_session` and optional `audit_seconds` (default1800). Invoke once per minute
with an existing user scheduler; `--audit` forces a full audit. Keep actual site
configuration and monitoring outputs outside the repository. Do not replace
other cron entries or change machine-wide services.

Each minute it checks exact owned supervisor/controller processes. Owned
reference and diagnostic children are preserved even when their output
directories are outside the watched root.
Every30
minutes it also checks both remote driver processes through strict SSH and asks
the AWS CLI to verify the intended IAM identity. It records current trial times
and worker stages without copying generated rationales, benchmark outputs or
credentials. An expired identity raises an alert; it is never worked around.

An absent supervisor qualifies for recovery only after the previous controller
has completed, no controller remains, both drivers are verified idle, and AWS
identity matches. Existing finality/review and dispatch checks must pass. The
normal supervisor repeats full hardware/network/correctness checks on launch.
The watchdog preserves the old state and starts the supervisor in a new window
of the owner's tmux. It permits at most one restart per completed result and
supervisor source revision. Repeated failure requires investigation.

Incomplete/failed benchmarks are never blindly retried. Active drivers are never
signaled. Existing root/external STOP controls, an intentional stopped state and
`root/monitor/STOP` prevent recovery. The last file disables monitoring activity
without stopping the experiment; remove the scheduler entry as well to uninstall.
Create that monitor STOP file before a manual coordinator handoff and remove it
after the replacement is healthy, so recovery does not race the planned change.

Private outputs are `monitor/status.json`, `monitor/audits.jsonl`, optional
`monitor/attention.json`, preserved state snapshots and a recovery ledger.
Attention is also displayed in the owner's tmux; this does not guarantee an
off-host notification. Audit records are separate from benchmark measurements
and do not establish successful execution or a new independent timing sample.

Monitoring reduces unattended downtime. Browser authentication, failed
correctness/hardware gates, host outages and normal preparation/round barriers
can still leave hardware idle; a30-minute audit is not a zero-downtime guarantee.
