"""Optional policies for running a baseline on a shared, SSH-only lab host."""

import re


def disable_optional_ec2_debug_servers(deploy_module) -> None:
    """Keep FireSim's optional debug hooks from starting or killing host services.

    Args:
        deploy_module: The pinned FireSim run_farm_deploy_managers module.

    This affects only this manager process. FPGA programming, simulation, and
    assertions remain enabled; batch workloads do not require interactive JTAG.
    """
    manager = getattr(deploy_module, "EC2InstanceDeployManager", None)
    if manager is None or not all(callable(getattr(manager, method, None))
                                  for method in ("start_ila_server", "kill_ila_server")):
        raise RuntimeError("FireSim debug hooks changed; review the pinned runtime before startup")

    def skip_debug(self):
        self.instance_logger("Lab baseline: optional JTAG/debug service startup and cleanup skipped")

    manager.start_ila_server = skip_debug
    manager.kill_ila_server = skip_debug


def use_prepared_ec2_sdk(deploy_module, revision: str, run) -> None:
    """Verify staged SDK and refuse conflicting modules without changing services.

    Args:
        deploy_module: The pinned FireSim run_farm_deploy_managers module.
        revision: Exact Git commit of the SDK already installed on the host.
        run: Host command runner that raises when a command fails.

    This process-local policy replaces automatic SDK downloads and XRT package
    removal on an offline-prepared host. FPGA loading remains
    enabled. A conflicting module is an explicit failure, never auto-unloaded.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected an exact staged SDK Git revision")
    manager = getattr(deploy_module, "EC2InstanceDeployManager", None)
    if manager is None or not all(callable(getattr(manager, name, None)) for name in
            ("get_and_install_aws_fpga_sdk", "unload_xrt_and_xocl",
             "copy_sim_slot_infrastructure")):
        raise RuntimeError("FireSim SDK hooks changed; review the pinned runtime before startup")

    active_guard = ("if pgrep -x FireSim-f2 >/dev/null; then "
                    "echo 'Active FPGA simulation; refusing to clear or load the slot' >&2; "
                    "exit 1; fi; ")
    copy_slot = manager.copy_sim_slot_infrastructure

    def copy_idle_slot(self, *args, **kwargs):
        # Infrastructure copying precedes clear/flash and can replace live files.
        # Refuse before copying, as well as immediately before programming.
        run(active_guard)
        return copy_slot(self, *args, **kwargs)

    def verify_sdk(self):
        actual = str(run("git -C /home/ubuntu/aws-fpga rev-parse HEAD")).strip()
        if actual != revision:
            raise RuntimeError("Staged FPGA SDK does not match the configured revision")
        run("command -v fpga-load-local-image >/dev/null && command -v fpga-describe-local-image >/dev/null")
        self.instance_logger("Lab baseline: verified staged SDK; no download or installation")

    def verify_no_conflict(self):
        run(active_guard + "for module in xocl xclmgmt; do test ! -d /sys/module/$module || "
            "{ echo 'Conflicting FPGA module loaded; services were not changed' >&2; exit 1; }; done")
        self.instance_logger("Lab baseline: no conflicting FPGA modules; services unchanged")

    manager.get_and_install_aws_fpga_sdk = verify_sdk
    manager.unload_xrt_and_xocl = verify_no_conflict
    manager.copy_sim_slot_infrastructure = copy_idle_slot
