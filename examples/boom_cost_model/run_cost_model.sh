#!/usr/bin/env bash
# Set up the SLICE tree (CHIA, GCC RISC-V backend, BOOM) and print the cost models.
#
# From anywhere:
#   bash /path/to/SLICE/chia/examples/boom_cost_model/run_cost_model.sh
#
# Optional:
#   SLICE_ROOT=/path/to/SLICE
#   RISCV_GCC=/path/to/riscv64-unknown-elf-gcc
#   CONDA_ENV=chia_env
#
# Writes SLICE/cost-model-out/REPORT.txt and cost_models.json.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHIA_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
SLICE_ROOT=${SLICE_ROOT:-$(dirname "$CHIA_ROOT")}
CONDA_ENV=${CONDA_ENV:-chia_env}
export SLICE_ROOT

log() { printf '\n== %s\n' "$*"; }

git_public() {
  git -c credential.helper= "$@"
}

link_existing() {
  local name=$1
  shift
  local dest="$SLICE_ROOT/$name"
  if [[ -e "$dest" ]]; then
    return 0
  fi
  local cand
  for cand in "$@"; do
    if [[ -d "$cand" ]]; then
      ln -sfn "$cand" "$dest"
      echo "linked $dest -> $cand"
      return 0
    fi
  done
  echo "no existing $name checkout to link"
}

activate_chia() {
  if python -c "import chia" >/dev/null 2>&1 && command -v chia >/dev/null 2>&1; then
    return 0
  fi
  local conda_sh=""
  local cand
  for cand in \
    /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh \
    "$HOME/miniforge3/etc/profile.d/conda.sh" \
    "$HOME/mambaforge/etc/profile.d/conda.sh" \
    "$HOME/miniconda3/etc/profile.d/conda.sh"
  do
    if [[ -f "$cand" ]]; then
      conda_sh=$cand
      break
    fi
  done
  if [[ -z "$conda_sh" ]]; then
    echo "chia is not importable and conda was not found." >&2
    echo "Create the env from the CHIA docs, then rerun this script:" >&2
    echo "  conda create -n ${CONDA_ENV} python=3.10.19" >&2
    echo "  conda activate ${CONDA_ENV}" >&2
    echo "  pip install -e ${CHIA_ROOT}" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  source "$conda_sh"
  conda activate "$CONDA_ENV"
}

log "SLICE root: $SLICE_ROOT"
mkdir -p "$SLICE_ROOT"

if [[ ! -f "$SLICE_ROOT/gcc/gcc/config/riscv/riscv.cc" ]]; then
  log "Cloning GCC RISC-V backend (sparse)"
  git_public clone --depth 1 --filter=blob:none --sparse \
    https://github.com/gcc-mirror/gcc.git "$SLICE_ROOT/gcc"
  git -C "$SLICE_ROOT/gcc" sparse-checkout set gcc/config/riscv
else
  echo "gcc backend already present"
fi

if [[ ! -d "$SLICE_ROOT/boom/.git" ]]; then
  log "Cloning riscv-boom"
  git_public clone --depth 1 https://github.com/riscv-boom/riscv-boom.git "$SLICE_ROOT/boom"
else
  echo "boom already present"
fi

link_existing chipyard \
  "$SLICE_ROOT/../chipyard-u250" \
  "$SLICE_ROOT/../chipyard-radiance" \
  "$SLICE_ROOT/../chipyard-graphics" \
  "$SLICE_ROOT/../chipyard"
link_existing firesim \
  "$SLICE_ROOT/../firesim"
# Rocket is the in-order baseline for the cost-model comparison. It already
# lives inside the linked Chipyard tree.
if [[ -d "$SLICE_ROOT/chipyard/generators/rocket-chip" ]]; then
  link_existing rocket-chip "$SLICE_ROOT/chipyard/generators/rocket-chip"
fi

log "Checking CHIA"
activate_chia
python - <<'PY'
import chia
import chia.cli.main
from importlib.metadata import version
print(f"chia {version('chialoops')} import ok ({getattr(chia, '__path__', [''])[0]})")
PY
command -v chia
chia --help >/dev/null
echo "chia CLI ok"

log "Extracting cost models and comparing codegen"
OUT=${COST_MODEL_OUT:-$SLICE_ROOT/cost-model-out}
python "$SCRIPT_DIR/compare_cost_models.py" \
  --gcc-src "$SLICE_ROOT/gcc/gcc/config/riscv" \
  --out "$OUT" \
  --kernels "$SCRIPT_DIR/kernels"

echo
echo "Cost-model report: $OUT/REPORT.txt"
echo "Machine-readable tables: $OUT/cost_models.json"
