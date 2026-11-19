#!/usr/bin/env bash
# Install MC/DC's self-hosted GPU runners for the account that runs this, one
# runner per GPU, as systemd user services with quiet hours (README.md).
#
# Usage: install_runners.sh --url <repository URL> --token <registration token>
#                           [--gpus 0,1] [--labels gpu,sm_80] [--cuda 13.3]
#
#   --url     the repository to serve, e.g. https://github.com/mcdc-project/mcdc
#   --token   from the repository's Settings -> Actions -> Runners -> New
#             self-hosted runner; valid for an hour, and for every runner
#   --gpus    GPU indices (nvidia-smi), one runner each. Default: every GPU
#   --labels  extra runner labels. Default: gpu,sm_<arch of the first GPU>
#   --cuda    CUDA version for the toolchain; must equal CUDA_VERSION in
#             regression_test-gpu.yml. Default: 13.3
#
# Run it as the runner account, logged in over SSH or with
# `machinectl shell <account>@` (not `sudo -u` or `su`, which leave no session
# for systemd user services). It is safe to run again: it skips what is
# already done, and refreshes the scripts and units. To move the runners to
# another repository, unregister each one first
# (`cd ~/runner-gpu0 && ./config.sh remove --token <removal token>`).

set -euo pipefail

RUNNER_VERSION=2.338.2
RUNNER_SHA256=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
url='' token='' gpus='' labels='' cuda=13.3
while [ $# -gt 0 ]; do
    case $1 in
        --url) url=$2; shift 2 ;;
        --token) token=$2; shift 2 ;;
        --gpus) gpus=$2; shift 2 ;;
        --labels) labels=$2; shift 2 ;;
        --cuda) cuda=$2; shift 2 ;;
        -h|--help) sed -n '2,/^$/s/^# \{0,1\}//p' "$0"; exit 0 ;;
        *) echo "Unknown option $1 (see --help)" >&2; exit 2 ;;
    esac
done
die() { echo "install_runners.sh: $*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "do not run this as root"
systemctl --user show-environment >/dev/null 2>&1 \
    || die "systemctl --user does not work here; log in over SSH or with 'machinectl shell $(id -un)@'"
if [ -z "$gpus" ]; then
    gpus=$(nvidia-smi --query-gpu=index --format=csv,noheader | paste -sd,)
fi
if [ -z "$labels" ]; then
    first=${gpus%%,*}
    arch=$(nvidia-smi -i "$first" --query-gpu=compute_cap --format=csv,noheader | tr -d .)
    labels=gpu,sm_$arch
fi

echo "== Toolchain (CUDA $cuda)"
toolchain=$HOME/mcdc-gpu-toolchain
if [ -x "$toolchain/bin/nvcc" ]; then
    echo "$toolchain exists; to rebuild it, delete it and run this again"
else
    CONDA_EXE=${CONDA_EXE:-$(command -v conda || echo /usr/bin/conda)} \
        "$here/setup_toolchain.sh" "$toolchain" "$cuda"
fi

echo "== Runner $RUNNER_VERSION"
package=$HOME/.cache/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz
if [ ! -f "$package" ]; then
    mkdir -p "$(dirname "$package")"
    curl -fsSL -o "$package.part" \
        "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-x64-$RUNNER_VERSION.tar.gz"
    mv "$package.part" "$package"
fi
echo "$RUNNER_SHA256  $package" | sha256sum --check --quiet \
    || { rm -f "$package"; die "the runner download does not match its published checksum"; }

echo "== Quiet hours"
mkdir -p "$HOME/bin" "$HOME/.local/share/gpu-runner" "$HOME/.config/systemd/user"
install -m 755 "$here/gpu_runner_quiet.py" "$HOME/bin/gpu-runner-quiet"
install -m 755 "$here/job_started.sh" "$HOME/.local/share/gpu-runner/job_started.sh"
install -m 644 "$here"/systemd/* "$HOME/.config/systemd/user/"
"$HOME/bin/gpu-runner-quiet" status >/dev/null  # writes the default config, mode off

# Set KEY=VALUE in a runner's .env, keeping the other lines config.sh wrote
set_env() {
    local file=$1 key=$2 value=$3
    touch "$file"
    grep -v "^$key=" "$file" > "$file.new" || true
    echo "$key=$value" >> "$file.new"
    mv "$file.new" "$file"
}

units=()
for gpu in ${gpus//,/ }; do
    name=gpu$gpu dir=$HOME/runner-gpu$gpu
    echo "== Runner $name (GPU $gpu) in $dir"
    if [ ! -x "$dir/config.sh" ]; then
        mkdir -p "$dir"
        tar xzf "$package" -C "$dir"
    fi
    if [ -f "$dir/.runner" ]; then
        echo "Already registered; skipping registration"
    else
        [ -n "$url" ] && [ -n "$token" ] || die "--url and --token are needed to register $name"
        (cd "$dir" && ./config.sh --unattended --url "$url" --token "$token" \
            --name "$(hostname -s)-$name" --labels "$labels" --work _work --replace)
    fi
    set_env "$dir/.env" CUDA_VISIBLE_DEVICES "$gpu"
    set_env "$dir/.env" MCDC_GPU_TOOLCHAIN "$toolchain"
    set_env "$dir/.env" GPU_RUNNER_INSTANCE "$name"
    set_env "$dir/.env" ACTIONS_RUNNER_HOOK_JOB_STARTED "$HOME/.local/share/gpu-runner/job_started.sh"
    units+=("github-runner@$name")
done

echo "== Services"
systemctl --user daemon-reload
systemctl --user enable "${units[@]}" gpu-runner-quiet.timer
# Restart running runners so they read a changed .env; idle ones restart
# cleanly. Then start the timer, which stops them again during quiet hours.
for unit in "${units[@]}"; do
    if "$HOME/bin/gpu-runner-quiet" busy "${unit#github-runner@}"; then
        echo "$unit is running a job; restart it later to apply changes"
    else
        systemctl --user restart "$unit"
    fi
done
systemctl --user start gpu-runner-quiet.timer

if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != yes ]; then
    loginctl enable-linger \
        || echo "WARNING: could not enable linger; the runners stop at logout. Ask an administrator to run 'loginctl enable-linger $(id -un)' (README.md)." >&2
fi

echo
"$HOME/bin/gpu-runner-quiet" status
echo
echo "Done. Check that the runners show as Idle under the repository's Settings -> Actions -> Runners."
