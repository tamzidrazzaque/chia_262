"""Run SPEC on a FireSim design with spec_eval.py, and print the SPEC ratios.

Run from examples/firesim_spec:
    RAY_ADDRESS=http://127.0.0.1:8265 chia job submit --working-dir . -- \\
        python spec_eval_loop.py spec06-int-test --cluster /path/to/cluster.yaml
"""

import argparse
import sys

import ray

from chia.aws.config import AWSConfig
from chia.aws.manager import Farm, start_aws_manager
from chia.base.ChiaFunction import get
from chia.cluster.config import load_config
from chia.cluster.loopback import driver_options
from chia.firesim.fs_bitstream import FSBitstream
from chia.firesim.state_def import BuildRecipe, RunConfig
from spec_eval import spec_eval


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", help="SPEC suite and input size, e.g. spec06-int-test or "
                                     "spec17-intspeed-train")
    parser.add_argument("--cluster", required=True, help="The cluster file of the running cluster")
    parser.add_argument("--recipe", default="megaboom_fcfs16",
                        help="A recipe of config_build_recipes.yaml")
    parser.add_argument("--agfi", help="Skip the bitstream build: an AGFI built from the recipe")
    parser.add_argument("--driver", help="The driver bundle (driver-bundle.tar.gz) of --agfi")
    parser.add_argument("--existing-f2", help="Public IP of one F2 already registered as a firesim_fpga worker")
    parser.add_argument("--max-fpgas", type=int, default=1, help="Maximum F2 count (default: 1)")
    parser.add_argument("--spec-flags", default="", help="Extra compiler flags, e.g. --spec-flags=-mtune=rocket")
    parser.add_argument("--compiler-id", default="", help="Compiler revision/patch hash or pinned compiler image digest")
    parser.add_argument("--cores", type=int, default=1, help="Threads/copies per benchmark (default: 1)")
    args = parser.parse_args()

    if bool(args.agfi) != bool(args.driver):
        parser.error("--agfi and --driver must be supplied together")
    if args.max_fpgas < 1 or args.cores < 1:
        parser.error("--max-fpgas and --cores must be positive")
    if args.existing_f2 and not args.agfi:
        parser.error("--existing-f2 requires --agfi and its matching --driver")
    cluster = load_config(args.cluster)
    compiler_id = args.compiler_id
    if not compiler_id:
        compiler = cluster.node_types.get("riscv_build")
        image = compiler.docker.image if compiler and compiler.docker else ""
        if "@sha256:" not in image and args.existing_f2:
            parser.error("provide --compiler-id or pin the riscv_build image to its digest")
        compiler_id = image if "@sha256:" in image else ""
    aws, farm = None, None
    if args.existing_f2:
        if not any(nt.resources.get("firesim_fpga", 0) >= 1
                   and args.existing_f2 in (nt.compatible_ips or [])
                   for nt in cluster.node_types.values()):
            parser.error("--existing-f2 must be a firesim_fpga worker in the cluster file")
        farm = Farm("firesim", "us-east-1", [args.existing_f2])
    else:
        if cluster.aws_config is None:
            parser.error("automatic provisioning requires the cluster's aws section")
    recipe = BuildRecipe.from_yaml("config_build_recipes.yaml", args.recipe)
    bitstream = None
    if args.agfi:
        with open(args.driver, "rb") as f:
            bitstream = FSBitstream(recipe.quintuplet(), agfi=args.agfi, driver_bytes=f.read())
    ray.init(**driver_options(cluster.head_ray_address))
    if not args.existing_f2:
        aws = start_aws_manager(cluster, AWSConfig(
            region=cluster.aws_config.region,
            key_name=cluster.aws_config.key_name,
            ssh_user=cluster.aws_config.ssh_user,
            ssh_private_key=cluster.aws_config.ssh_private_key))

    result = get(spec_eval.chia_remote(aws, args.spec, recipe,
                                       RunConfig.from_yaml("config_runtime.yaml"),
                                       bitstream=bitstream, existing_farm=farm,
                                       max_fpgas=args.max_fpgas, spec_flags=args.spec_flags,
                                       cores=args.cores, compiler_id=compiler_id))
    print(f"bitstream: {result.bitstream.agfi}")
    for benchmark, seconds in sorted(result.seconds.items()):
        print(f"{benchmark}: {seconds:.0f} s, ratio {result.ratios.get(benchmark)}")
    print(f"score: {result.score}")
    return 0 if result.score is not None else 1


if __name__ == "__main__":
    sys.exit(main())
