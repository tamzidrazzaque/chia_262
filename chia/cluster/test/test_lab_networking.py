"""Lab setup keeps SSH verification and loopback-only transport intact."""

from unittest.mock import Mock

from chia.cluster.config import build_config, SSHAuthConfig, TunnelConfig
from chia.cluster.ssh import SSHClient
from chia.cluster.tunnel import TunnelManager
from chia.cluster import node_setup, tunnel


def test_trusted_ssh_and_rsync_do_not_override_known_hosts():
    client = SSHClient("127.200.0.1", "user", strict_host_key_checking=True,
                       forward_agent=False)
    ssh = client._ssh_base_args()
    rsync = client._rsync_base_args()[-1]
    assert "StrictHostKeyChecking=yes" in ssh and "BatchMode=yes" in ssh
    assert "-a" in ssh and "-A" not in ssh
    assert "StrictHostKeyChecking=yes" in rsync and "BatchMode=yes" in rsync
    assert " /dev/null" not in rsync and "=/dev/null" not in rsync
    assert "UserKnownHostsFile=/dev/null" not in ssh


def test_gcs_reverse_forward_targets_the_bound_head_address(tmp_path, monkeypatch):
    proc = Mock(pid=12345)
    spawn = Mock(return_value=proc)
    monkeypatch.setattr(tunnel.subprocess, "Popen", spawn)
    monkeypatch.setattr(tunnel, "_PID_DIR", str(tmp_path))
    tc = TunnelConfig(tunnel_ip="127.0.0.2", kill_orphaned_tunnels=False,
                      ray_worker_port_min=23500, ray_worker_port_max=23500,
                      tool_port_min=23600, tool_port_max=23600)
    auth = SSHAuthConfig("ubuntu", strict_host_key_checking=True, forward_agent=False)
    TunnelManager().start_tunnel(tc.tunnel_ip, "192.0.2.1", auth, tc,
                                head_gcs_port=22379, head_ip="127.200.0.1")
    cmd = spawn.call_args.args[0]
    assert "127.0.0.2:16379:127.200.0.1:22379" in cmd
    assert "StrictHostKeyChecking=yes" in cmd and "ForwardAgent=no" in cmd
    assert "BatchMode=yes" in cmd and "UserKnownHostsFile=/dev/null" not in cmd


def test_loopback_head_needs_no_host_nat_or_route_changes(monkeypatch):
    config = build_config({
        "cluster_name": "lab", "provider": {"head_ip": "127.200.0.1"},
        "auth": {"ssh_user": "user", "strict_host_key_checking": True,
                 "forward_agent": False,
                 "overrides": {"192.0.2.1": {"ssh_user": "ubuntu",
                     "tunnel": {"pre_tunnel_commands": [], "kill_orphaned_tunnels": False}}}},
        "available_node_types": {"firesim": {"num_workers": 1,
            "compatible_ips": ["192.0.2.1"], "resources": {"firesim_fpga": 1}}},
    })
    ssh = Mock()
    monkeypatch.setattr(node_setup, "setup_head_node", Mock())
    monkeypatch.setattr(node_setup, "setup_worker_node", Mock())
    monkeypatch.setattr(node_setup, "_make_ssh", Mock(return_value=ssh))
    monkeypatch.setattr(node_setup, "TunnelManager", Mock())
    node_setup.bring_up_cluster(config)
    ssh.run_commands.assert_not_called()
    auth = config.get_ssh_auth("192.0.2.1")
    assert auth.strict_host_key_checking and not auth.forward_agent
    assert config.get_ssh_auth(config.head_ip).strict_host_key_checking


def test_incremental_loopback_worker_needs_no_host_nat_or_route_changes(monkeypatch):
    config = build_config({
        "cluster_name": "lab", "provider": {"head_ip": "127.200.0.1"},
        "auth": {"ssh_user": "user", "strict_host_key_checking": True,
                 "forward_agent": False,
                 "overrides": {"192.0.2.1": {"ssh_user": "ubuntu",
                     "tunnel": {"pre_tunnel_commands": [], "kill_orphaned_tunnels": False}}}},
        "available_node_types": {"firesim": {"num_workers": 1,
            "compatible_ips": ["192.0.2.1"], "resources": {"firesim_fpga": 1}}},
    })
    ssh = Mock()
    monkeypatch.setattr(node_setup, "setup_worker_node", Mock())
    monkeypatch.setattr(node_setup, "_make_ssh", Mock(return_value=ssh))
    monkeypatch.setattr(node_setup, "TunnelManager", Mock())
    node_setup.add_nodes_to_cluster(config, node_setup.assign_nodes(config))
    ssh.run_commands.assert_not_called()
