"""Build a SPEC CPU FireSim workload: compile SPEC and a FireMarshal base in
parallel, then compose SPEC into the base rootfs, one image per job.

    build_program (SPEC via speckle) ─┐
    build_base    (br-base)          ─┴─> compose(overlay=SPEC, base=br-base,
                                              jobs=one per run)
                                          └─> workload (FireMarshalArtifact)

``spec`` is ``spec06-int-<size>``, or ``spec17-``/``spec26-`` with ``intspeed-<size>``
or ``intrate-<size>``; the size is ``test``, ``train`` or ``ref``. collateral/spec<year>
holds the build scripts and the job list (marshal-configs) of each SPEC version.

The SPEC files go from the build to the compose through Ray's memory, so they must
fit in it: a SPEC 2026 ref build is 39 GB.

The cluster (cluster_sw.yaml): a ``riscv_build`` worker that mounts each SPEC install
and sets SPEC_DIR_2006/2017/2026, and a ``firemarshal`` worker (with ``aws_creds``
for an upload).

Run (after `chia up cluster_sw.yaml -y`):
    chia job submit --working-dir . -- python spec_sw_build_loop.py spec06-int-test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import sys
from pathlib import Path

import ray
from ray import cloudpickle

from chia.base.ChiaFunction import ChiaFunction, get
from chia.chipyard.firemarshal_node import FireMarshalNode
from chia.chipyard.riscv_build_node import RiscvBuildNode
from chia.chipyard.state_def import FireMarshalArtifact, ProgramBuildArtifact
from chia.cluster.loopback import driver_options

# Workers cannot import this example module, so its functions travel by value.
cloudpickle.register_pickle_by_value(sys.modules[__name__])

COLLATERAL = Path(__file__).resolve().parent / "collateral"
_FIREMARSHAL = {"resources": {"firemarshal": 1}}


def start_workload(spec: str, cores: int = 1, spec_flags: str = "", small_images: bool = False,
                   upload_to: str = "", compiler_id: str = "",
                   benchmarks: list[str] | None = None,
                   compiler_prefix: str = "", compiler_node_id: str = "") -> ray.ObjectRef:
    """Start the SPEC build, the FireMarshal base and the compose of ``spec``; return
    the ref of the workload (a FireMarshalArtifact).

    Args:
        spec: e.g. ``"spec17-intspeed-test"``.
        cores: Threads of a speed run, copies of a rate run.
        spec_flags: Flags added to each RISC-V compile and link, e.g. ``"-march=rv64gc_zba"``.
        small_images: Each job's image holds only its own benchmark.
        upload_to: ``s3://bucket/prefix``: upload the workload and return its
            ``archive_uri``, not its bytes.
        compiler_id: Compiler revision, patch hash, or pinned compiler image digest.
            Change this when the compiler changes, even if its flags stay the same.
        benchmarks: Optional SPEC2017 benchmark subset for functional validation.
            None builds the full suite. A subset is not a full-suite baseline.
        compiler_prefix: Absolute toolchain prefix inside the compiler worker.
            Selects its bin directory and RISCV; compiler_id alone does not.
        compiler_node_id: Pin compilation to this Ray node when selecting a
            worker-local compiler prefix. Required with compiler_prefix.
    """
    year, suite, size = _parse(spec)
    if compiler_prefix and (year != "2017" or not Path(compiler_prefix).is_absolute()
                            or any(c in compiler_prefix for c in "\n\r\0")):
        raise ValueError("compiler_prefix requires SPEC2017 and an absolute worker path")
    if compiler_prefix and not compiler_id:
        raise ValueError("an explicit compiler_prefix requires a compiler_id")
    if compiler_prefix and not compiler_node_id:
        raise ValueError("an explicit compiler_prefix requires compiler_node_id")
    files = {p.name: p.read_bytes() for p in (COLLATERAL / f"spec{year}").iterdir() if p.is_file()}
    files["reftimes.py"] = (COLLATERAL / "reftimes.py").read_bytes()
    workload_jobs = jobs(spec, cores)
    if benchmarks is not None:
        if year != "2017" or not benchmarks or set(benchmarks) - {_benchmark(j) for j in workload_jobs}:
            raise ValueError("benchmarks must select existing SPEC2017 suite benchmarks")
        workload_jobs = [job for job in workload_jobs if _benchmark(job) in benchmarks]
    # FireMarshalNode reuses a stored image by name, so the name changes with the inputs.
    digest = hashlib.sha256(json.dumps([spec, cores, spec_flags, small_images, workload_jobs]).encode())
    if compiler_id:
        digest.update(b"\0compiler\0" + compiler_id.encode())
    if compiler_prefix:
        digest.update(b"\0prefix\0" + compiler_prefix.encode())
    for f in sorted(files):
        digest.update(f.encode() + files[f])
    name = f"{spec}-{digest.hexdigest()[:8]}"

    refsize = f"ref{suite[3:]}" if year != "2006" and size == "ref" else size   # refspeed/refrate
    overlay = f"speckle/build/overlay/{suite}/{size}"
    # SPEC2017 runsetup folders contain comparison commands and references.
    cleanup = '' if year == "2017" else (
        'rm -rf "$SPEC_DIR"/benchspec/CPU*/*/build "$SPEC_DIR"/benchspec/CPU*/*/run '
        '"$SPEC_DIR"/benchspec/CPU*/*/exe && ')
    command = (f'export SPEC_DIR="$SPEC_DIR_{year}" THREADS={cores} SPEC_FLAGS={shlex.quote(spec_flags)} && '
               f'export SPEC_BENCHMARKS={shlex.quote(" ".join(sorted(set(benchmarks or []))))} && '
               # SPEC builds in its install: one build at a time, then remove its build folders.
               f'exec 9<"$SPEC_DIR" && flock 9 && '
               f'bash {"build-cint.sh" if year == "2006" else f"build-{suite}.sh"} {size} && '
               f'python3 reftimes.py "$SPEC_DIR" {refsize} '
               f'{" ".join(sorted({_benchmark(job) for job in workload_jobs}))} > {overlay}/reftimes.json && '
               f'{cleanup}'
               f'mkdir root && mv speckle/build/overlay root/spec')     # the files at their rootfs paths
    if compiler_prefix:
        command = (f'export RISCV={shlex.quote(compiler_prefix)} && '
                   'export PATH="$RISCV/bin:$PATH" && ' + command)
    outputs = ["root"]
    if year == "2017":
        # Collect diagnostics even when runcpu fails. The original command exit
        # code survives the EXIT trap; a missing/failed collection is an error.
        command = ('mkdir -p build-logs; trap \'rc=$?; '
                   'if [ "$rc" = 0 ]; then '
                   'cp -a speckle/build/*.log speckle/*.cfg compiler-provenance.json build-logs/ || rc=$?; '
                   'else cp -a speckle/build/*.log speckle/*.cfg compiler-provenance.json build-logs/ '
                   '2>/dev/null || :; fi; exit "$rc"\' EXIT; ' + command)
        outputs.append("build-logs")
    rv = RiscvBuildNode(timeout_seconds=8 * 60 * 60)
    build_program = rv.build_program
    if compiler_node_id:
        from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy
        build_program = build_program.options(scheduling_strategy=NodeAffinitySchedulingStrategy(compiler_node_id, soft=False))
    spec_ref = build_program.chia_remote(rv, input_files=files, command=["bash", "-c", command],
                                            work_dir="/tmp/spec_build", outputs=outputs,
                                            cleanup_task_dir=year != "2017")
    fm = FireMarshalNode(timeout_seconds=4 * 60 * 60)
    base_ref = fm.build_base.options(**_FIREMARSHAL).chia_remote(fm, name="br-base")
    # aws_creds: the compose uploads the workload.
    compose = _compose.options(resources={"firemarshal": 1, "aws_creds": 1}) if upload_to else _compose
    return compose.chia_remote(name, spec_ref, base_ref, workload_jobs, small_images, upload_to)


def jobs(spec: str, cores: int = 1) -> list[dict]:
    """The FireMarshal jobs of ``spec``, with ``cores`` threads or copies. Each job
    also copies the reference times to /output."""
    year, suite, size = _parse(spec)
    config = COLLATERAL / f"spec{year}" / "marshal-configs" / f"{spec.rsplit('-', 1)[0]}.json"
    root = f"/root/spec/{suite}/{size}"
    entries = json.loads(config.read_text())["jobs"]
    if year == "2017" and suite == "intspeed" and size == "test":
        # The pinned 657.xz_s.test.cmd contains 12 cases, versus two ref cases.
        entries = [job for job in entries if _benchmark(job) != "657.xz_s"] + [
            {"name": f"657.xz_s-test-{i}", "command": f"./intspeed.sh 657.xz_s --workload {i} --threads 1"}
            for i in range(12)]
    result = [{"name": job["name"], "outputs": ["/output"],
             "command": f"mkdir -p /output && cp {root}/reftimes.json /output/ && cd {root} && "
                        + re.sub(r"--(threads|copies) \d+", rf"--\1 {cores}", job["command"])}
            for job in entries]
    if year == "2017":
        for job in result:
            # Reference runs also need outputs for correctness checks. Capture
            # happens after the timed command and is not part of its CSV time.
            job["command"] = ('(export CHIA_CAPTURE_OUTPUTS=1; ' + job["command"] +
                              '; rc=$?; echo "$rc" > /output/job.status; exit "$rc")')
    return result


@ChiaFunction(**_FIREMARSHAL)
def _compose(name: str, spec: ProgramBuildArtifact, base, jobs: list[dict], small_images: bool,
             upload_to: str) -> FireMarshalArtifact:
    """Compose the SPEC files onto br-base, one image per job, and upload the workload
    for ``upload_to``. With ``small_images``, a job's image holds only its benchmark's
    folder and the files of no benchmark."""
    if name.startswith("spec17-"):
        # The generated lab config persists /images on the host. Keep the
        # compiler diagnostics even if compose returns a failed artifact.
        diagnostics = Path("/images") / f"{name}-build-logs"
        diagnostics.mkdir(parents=True, exist_ok=True)
        (diagnostics / "compiler.stdout").write_text(spec.stdout)
        (diagnostics / "compiler.stderr").write_text(spec.stderr)
        (diagnostics / "compiler-status.json").write_text(json.dumps({
            "success": spec.success, "returncode": spec.returncode}) + "\n")
        for path, content in spec.files.items():
            if path.startswith("build-logs/"):
                relative = Path(path).relative_to("build-logs")
                if ".." in relative.parts:
                    raise ValueError("invalid build diagnostic path")
                dest = diagnostics / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
    for step, artifact in (("SPEC build", spec), ("FireMarshal base", base)):
        if not artifact.success:
            return FireMarshalArtifact(success=False, json_name=name + ".json",
                                       stderr=f"{step} failed:\n{artifact.stderr[-4000:]}")
    # Build logs are retained in the compiler artifact, not installed in /.
    files = {path: content for path, content in spec.files.items() if path.startswith("root/")}
    if not files or not any(path.endswith("/reftimes.json") for path in files):
        return FireMarshalArtifact(success=False, json_name=name + ".json",
                                   stderr="SPEC result collection omitted the workload or reference times")
    if small_images:
        benchmarks = {_benchmark(job) for job in jobs}

        def owner(path: str) -> str | None:      # root/spec/<suite>/<size>/<benchmark>/...
            parts = path.split("/")
            return parts[4] if len(parts) > 5 and parts[4] in benchmarks else None

        jobs = [{**job, "files": [p for p in files if owner(p) in (None, _benchmark(job))]}
                for job in jobs]
    largest = max(sum(len(files[p]) for p in job.get("files", files)) for job in jobs)
    workload = FireMarshalNode(timeout_seconds=4 * 60 * 60).compose(
        base_name="br-base", name=name, overlay_files=files, overlay_modes=spec.modes,
        config={"jobs": jobs}, rootfs_size_mib=1024 * (math.ceil(2 * largest / 2**30) + 1))
    if upload_to and workload.success:
        workload = workload.publish(*upload_to.removeprefix("s3://").split("/", 1))
    return workload


def _benchmark(job: dict) -> str:
    """The benchmark that a job runs: the argument of its run script."""
    return re.search(r"\.sh (\S+)", job["command"])[1]


def _parse(spec: str) -> tuple[str, str, str]:
    """``"spec17-intspeed-test"`` -> ``("2017", "intspeed", "test")``; 2006's suite is
    ``cint2006``, speckle's name for it."""
    m = re.fullmatch(r"spec(06|17|26)-(int|intspeed|intrate)-(test|train|ref)", spec)
    if not m or (m[1] == "06") != (m[2] == "int"):
        raise ValueError(f"not a SPEC name: {spec!r}")
    year = f"20{m[1]}"
    return year, "cint2006" if year == "2006" else m[2], m[3]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", help="SPEC suite and input size, e.g. spec06-int-test or "
                                     "spec17-intspeed-train")
    parser.add_argument("--compiler-id", default="", help="Pinned compiler image/revision for the cache and record")
    parser.add_argument("--compiler-prefix", default="", help="Absolute toolchain prefix in the compiler worker")
    parser.add_argument("--compiler-node-id", default="", help="Pin compilation to this Ray node")
    parser.add_argument("--spec-flags", default="")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, help="Persist workload archive, build logs and metadata")
    parser.add_argument("--benchmarks", nargs="+", help="SPEC2017 subset for a functional check")
    parser.add_argument("--small-images", action="store_true", help="Include only each job's benchmark in its image")
    args = parser.parse_args()
    if args.cores < 1:
        parser.error("--cores must be positive")

    ray.init(**driver_options(os.environ.get("RAY_ADDRESS", "auto")))
    wl = get(start_workload(args.spec, cores=args.cores, spec_flags=args.spec_flags,
                            compiler_id=args.compiler_id, benchmarks=args.benchmarks,
                            compiler_prefix=args.compiler_prefix,
                            compiler_node_id=args.compiler_node_id,
                            small_images=args.small_images))
    workload_jobs = jobs(args.spec, args.cores)
    if args.benchmarks:
        workload_jobs = [job for job in workload_jobs if _benchmark(job) in args.benchmarks]
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "build.stdout").write_text(wl.stdout)
        (args.output_dir / "build.stderr").write_text(wl.stderr)
        (args.output_dir / "build.json").write_text(json.dumps({
            "spec": args.spec, "cores": args.cores, "spec_flags": args.spec_flags,
            "compiler_id": args.compiler_id, "success": wl.success,
            "small_images": args.small_images,
            "compiler_prefix": args.compiler_prefix,
            "returncode": wl.returncode, "descriptor": wl.json_name,
            "jobs": workload_jobs, "benchmarks": args.benchmarks, "command": sys.argv,
            "QEMU_validated": False, "FPGA_executed": False,
        }, indent=2) + "\n")
        if wl.success:
            (args.output_dir / "workload.tar.gz").write_bytes(wl.archive)
    if not wl.success:
        print("workload failed\n" + wl.stderr[-2000:]); return 1
    print(f"OK: workload {len(wl.archive)} bytes, descriptor {wl.json_name}, {len(workload_jobs)} jobs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
