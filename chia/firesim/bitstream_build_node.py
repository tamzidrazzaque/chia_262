"""Build an f2 bitstream with FireSim's own build code."""

from __future__ import annotations

import logging
import os
import subprocess
import threading

import yaml

from chia.base.ChiaFunction import ChiaFunction
from chia.firesim.fs_bitstream import DRIVER_TAR_NAME, FSBitstream
from chia.firesim.specs import BUILD_DIR, ECAD_RESOURCE
from chia.firesim.state_def import BuildRecipe, EcadBuildResult

CHIPYARD = "/home/ray/chipyard"
FIRESIM = f"{CHIPYARD}/sims/firesim"
DEPLOY = f"{FIRESIM}/deploy"

_BUILD = r"""
import argparse, os, shlex, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.getcwd())
import lddwrap
from fabric.api import local, settings
from fabric.operations import _prefix_commands, _prefix_env_vars
import buildtools.bitbuilder as bitbuilder
from buildtools.buildconfigfile import BuildConfigFile

driver, bundle = sys.argv[1:]


def rsync_local(remote_dir, local_dir=None, upload=True, exclude=(), extra_opts="", capture=False, **kw):
    src, dst = (local_dir, remote_dir) if upload else (remote_dir, local_dir)
    excludes = " ".join(f"--exclude={e}" for e in ([exclude] if isinstance(exclude, str) else exclude))
    return local(f"rsync -a {excludes} {extra_opts} {src} {dst}", capture=capture, shell="/bin/bash")


def run_on_host(cmd, **kw):
    # Fabric's run() with the instance as the build host: its cd/env prefixes
    # go inside the host command, run as fabric's remote shell would.
    cmd = _prefix_env_vars(_prefix_commands(cmd, "remote"))
    with settings(command_prefixes=[]):
        return local("sudo nsenter -t 1 -a -- sudo -u ubuntu /bin/bash -l -c "
                     + shlex.quote(cmd), shell="/bin/bash")


def bundle_driver():
    # The driver and the libraries it loads from this conda env, which the run
    # host lacks. Not FireSim's get_local_shared_libraries: in this image it also
    # takes glibc, which crashes on the host.
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(driver, d)
        for dso in lddwrap.list_dependencies(Path(driver)):
            if dso.path and str(dso.path).startswith(os.environ["CONDA_PREFIX"]):
                shutil.copy(os.path.realpath(dso.path), os.path.join(d, dso.soname))
        local(f"tar -czf {bundle} -C {d} {' '.join(os.listdir(d))}")


bitbuilder.rsync_project = rsync_local

config = BuildConfigFile(argparse.Namespace(
    launchtime=None, forceterminate=True, buildconfigfile="config_build.yaml",
    buildrecipesconfigfile="config_build_recipes.yaml",
    hwdbconfigfile="config_hwdb.yaml"))
config.request_build_hosts()
config.wait_on_build_host_initializations()
for build in config.builds_list:
    bitbuilder.run = lambda cmd, **kw: local(cmd, shell="/bin/bash")
    print("[build] replace_rtl", flush=True)
    build.bitbuilder.replace_rtl()
    print("[build] build_driver", flush=True)
    build.bitbuilder.build_driver()
    print("[build] driver_bundle", flush=True)
    bundle_driver()
    bitbuilder.run = run_on_host
    print("[build] build_bitstream", flush=True)
    if not build.bitbuilder.build_bitstream():
        sys.exit(1)
"""


class BitstreamBuildNode:
    """Applies a chipyard diff and runs ``firesim buildbitstream``."""

    def __init__(self, timeout_seconds: int = 86400):
        """
        Args:
            timeout_seconds: Wall-clock limit for the whole build, AGFI included.
        """
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger("BitstreamBuildNode")

    @ChiaFunction(resources={ECAD_RESOURCE: 1})
    def build_bitstream(self, recipe: BuildRecipe,
                        diffs: "list[str] | None" = None) -> EcadBuildResult:
        log = []
        out = f"{FIRESIM}/sim/output/{recipe.platform}/{recipe.quintuplet()}"
        bundle = f"{out}/{DRIVER_TAR_NAME}"
        steps = [
            ("git reset", f"cd {CHIPYARD} && git reset --hard HEAD && git clean -fd"
                          if diffs else "true", ""),
            *((f"git apply {i}", f"cd {CHIPYARD} && git apply -", diff)
              for i, diff in enumerate(diffs or [], 1)),
            ("build dir", f"sudo chown $(id -u):$(id -g) {BUILD_DIR}", ""),
            ("build", f"source {CHIPYARD}/env.sh && cd {DEPLOY} && "
                      f"JAVA_HEAP_SIZE={recipe.java_heap_size} python - "
                      f"{out}/{recipe.design}-{recipe.platform} {bundle}", _BUILD),
        ]
        self._write_configs(recipe)
        for name, cmd, stdin in steps:
            print(f"[build] {name}", flush=True)
            rc, out = self._sh(cmd, stdin)
            log.append(f"=== {name} (rc={rc}) ===\n{out[-4000:]}")
            if rc != 0:
                return EcadBuildResult(recipe.name, success=False, log="\n".join(log))

        with open(f"{DEPLOY}/built-hwdb-entries/{recipe.name}") as f:
            agfi = yaml.safe_load(f)[recipe.name]["agfi"]
        with open(bundle, "rb") as f:
            driver = f.read()
        return EcadBuildResult(
            recipe.name, success=True, log="\n".join(log),
            bitstream=FSBitstream(recipe.quintuplet(), agfi=agfi, driver_bytes=driver))

    @staticmethod
    def _write_configs(recipe: BuildRecipe) -> None:
        """The files FireSim's build code reads; everything else is FireSim's."""
        stale = f"{DEPLOY}/built-hwdb-entries/{recipe.name}"
        if os.path.exists(stale):
            os.remove(stale)
        build = {
            "build_farm": {
                "base_recipe": "build-farm-recipes/externally_provisioned.yaml",
                "recipe_arg_overrides": {
                    "default_build_dir": BUILD_DIR,
                    # Only names the build; _BUILD runs every step locally.
                    "build_farm_hosts": ["localhost"],
                },
            },
            "builds_to_run": [recipe.name],
            "agfis_to_share": [],
            "share_with_accounts": {},
        }
        recipes = {recipe.name: {
            "PLATFORM": recipe.platform,
            "TARGET_PROJECT": recipe.target_project,
            "TARGET_PROJECT_MAKEFRAG":
                f"{CHIPYARD}/generators/firechip/chip/src/main/makefrag/firesim",
            "DESIGN": recipe.design,
            "TARGET_CONFIG": recipe.target_config,
            "PLATFORM_CONFIG": recipe.platform_config,
            "deploy_quintuplet": None,
            "platform_config_args": {"fpga_frequency": recipe.fpga_frequency,
                                     "build_strategy": recipe.build_strategy},
            "post_build_hook": None,
            "metasim_customruntimeconfig": None,
            "bit_builder_recipe": f"bit-builder-recipes/{recipe.platform}.yaml",
        }}
        # BuildConfigFile also opens the hwdb, and fails on an empty file.
        for name, config in (("config_build.yaml", build),
                             ("config_build_recipes.yaml", recipes),
                             ("config_hwdb.yaml", {})):
            with open(f"{DEPLOY}/{name}", "w") as f:
                yaml.safe_dump(config, f, sort_keys=False)

    def _sh(self, cmd: str, stdin: str = "") -> tuple[int, str]:
        """Run in this container and return its output; print only the
        ``[build]`` step lines as they come. Never raises."""
        self.logger.info(f"$ {cmd[:200]}")
        p = subprocess.Popen(["bash", "-lc", cmd], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        timer = threading.Timer(self.timeout_seconds, p.kill)
        timer.start()
        p.stdin.write(stdin)
        p.stdin.close()
        out = []
        for line in p.stdout:
            out.append(line)
            if line.startswith("[build] "):
                print(line, end="", flush=True)
        rc = p.wait()
        timer.cancel()
        return rc, "".join(out)
