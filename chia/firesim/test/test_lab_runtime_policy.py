"""Lab baseline skips optional debug hooks without touching FPGA operations."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from chia.firesim.runtime_policy import disable_optional_ec2_debug_servers, use_prepared_ec2_sdk


def test_debug_policy_does_not_start_or_kill_host_services():
    class Manager:
        start_ila_server = Mock(side_effect=AssertionError("must not launch debug listeners"))
        kill_ila_server = Mock(side_effect=AssertionError("must not kill others' services"))
        flash_fpgas = Mock()
        infrasetup_instance = Mock()
        instance_logger = Mock()

    flash, setup = Manager.flash_fpgas, Manager.infrasetup_instance
    disable_optional_ec2_debug_servers(SimpleNamespace(EC2InstanceDeployManager=Manager))
    instance = Manager()
    instance.start_ila_server()
    instance.kill_ila_server()
    assert Manager.instance_logger.call_count == 2
    assert Manager.flash_fpgas is flash and Manager.infrasetup_instance is setup


@pytest.mark.parametrize("module", [SimpleNamespace(),
    SimpleNamespace(EC2InstanceDeployManager=SimpleNamespace(start_ila_server=Mock()))])
def test_changed_debug_hooks_refuse_startup(module):
    with pytest.raises(RuntimeError, match="review the pinned runtime"):
        disable_optional_ec2_debug_servers(module)


def test_prepared_sdk_is_verified_without_installing_or_stopping_services():
    class Manager:
        get_and_install_aws_fpga_sdk = Mock()
        unload_xrt_and_xocl = Mock()
        copy_sim_slot_infrastructure = Mock()
        flash_fpgas = Mock()
        instance_logger = Mock()

    revision = "4" * 40
    run = Mock(side_effect=[revision + "\n", "", ""])
    flash = Manager.flash_fpgas
    use_prepared_ec2_sdk(SimpleNamespace(EC2InstanceDeployManager=Manager), revision, run)
    instance = Manager()
    instance.get_and_install_aws_fpga_sdk()
    instance.unload_xrt_and_xocl()
    commands = [call.args[0] for call in run.call_args_list]
    assert not any(word in command for command in commands for word in
                   ("git clone", "checkout", "sdk_setup", "systemctl", "yum", "apt", "rmmod"))
    assert "/sys/module/$module" in commands[-1]
    assert "pgrep -x FireSim-f2" in commands[-1]
    assert "refusing to clear or load the slot" in commands[-1]
    assert Manager.flash_fpgas is flash


def test_wrong_prepared_sdk_revision_refuses_before_runtime_changes():
    manager = SimpleNamespace(get_and_install_aws_fpga_sdk=Mock(),
                              unload_xrt_and_xocl=Mock(), copy_sim_slot_infrastructure=Mock(),
                              instance_logger=Mock())
    run = Mock(return_value="5" * 40)
    use_prepared_ec2_sdk(SimpleNamespace(EC2InstanceDeployManager=manager), "4" * 40, run)
    with pytest.raises(RuntimeError, match="does not match"):
        manager.get_and_install_aws_fpga_sdk(manager)
    assert run.call_count == 1


def test_conflicting_module_failure_is_propagated_without_unloading():
    manager = SimpleNamespace(get_and_install_aws_fpga_sdk=Mock(),
                              unload_xrt_and_xocl=Mock(), copy_sim_slot_infrastructure=Mock(),
                              instance_logger=Mock())
    run = Mock(side_effect=RuntimeError("conflicting module"))
    use_prepared_ec2_sdk(SimpleNamespace(EC2InstanceDeployManager=manager), "4" * 40, run)
    with pytest.raises(RuntimeError, match="conflicting module"):
        manager.unload_xrt_and_xocl(manager)
    assert "rmmod" not in run.call_args.args[0]


def test_active_simulation_is_refused_before_copying_live_slot_files():
    class Manager:
        get_and_install_aws_fpga_sdk = Mock()
        unload_xrt_and_xocl = Mock()
        copy_sim_slot_infrastructure = Mock()
        instance_logger = Mock()

    original = Manager.copy_sim_slot_infrastructure
    run = Mock(side_effect=RuntimeError("active FPGA simulation"))
    use_prepared_ec2_sdk(SimpleNamespace(EC2InstanceDeployManager=Manager), "4" * 40, run)
    with pytest.raises(RuntimeError, match="active FPGA simulation"):
        Manager().copy_sim_slot_infrastructure(0, "/owned/uri")
    original.assert_not_called()
    assert "pgrep -x FireSim-f2" in run.call_args.args[0]


def test_idle_slot_copy_preserves_the_original_arguments():
    class Manager:
        get_and_install_aws_fpga_sdk = Mock()
        unload_xrt_and_xocl = Mock()
        copy_sim_slot_infrastructure = Mock(return_value="copied")
        instance_logger = Mock()

    original = Manager.copy_sim_slot_infrastructure
    run = Mock()
    use_prepared_ec2_sdk(SimpleNamespace(EC2InstanceDeployManager=Manager), "4" * 40, run)
    instance = Manager()
    assert instance.copy_sim_slot_infrastructure(0, "/owned/uri") == "copied"
    original.assert_called_once_with(instance, 0, "/owned/uri")


def test_prepared_sdk_rejects_invalid_pin_and_changed_hooks():
    with pytest.raises(ValueError):
        use_prepared_ec2_sdk(SimpleNamespace(), "main", Mock())
    with pytest.raises(RuntimeError, match="review the pinned runtime"):
        use_prepared_ec2_sdk(SimpleNamespace(), "4" * 40, Mock())
