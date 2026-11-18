#!/usr/bin/env bash
# Create (or recreate) the conda environment that MC/DC's self-hosted GPU runners
# build each job's virtual environment from. It holds only what pip cannot
# provide well: Python, nvcc, and an MPI library for mpi4py.
#
# Usage: setup_toolchain.sh [prefix] [cuda-version]
#   prefix        default: $HOME/mcdc-gpu-toolchain
#   cuda-version  default: 13.3; no newer than the driver (`nvidia-smi`), and
#                 the same value as CUDA_VERSION in regression_test-gpu.yml
#
# Point the runner at the result by adding MCDC_GPU_TOOLCHAIN=<prefix> to the
# runner's .env file.

set -euo pipefail

PREFIX="${1:-$HOME/mcdc-gpu-toolchain}"
CUDA_VERSION="${2:-13.3}"
CONDA="${CONDA_EXE:-conda}"

"$CONDA" create --yes --prefix "$PREFIX" --override-channels -c conda-forge \
    "python=3.11" pip mpich \
    "cuda-nvcc=${CUDA_VERSION}" "cuda-version=${CUDA_VERSION}"

"$PREFIX/bin/nvcc" --version | tail -n 1
echo "Toolchain ready: add MCDC_GPU_TOOLCHAIN=$PREFIX to the runner's .env file."
