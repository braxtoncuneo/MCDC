# Self-hosted GPU runners

`.github/workflows/regression_test-gpu.yml` runs on self-hosted runners with the
labels `self-hosted`, `gpu`, and `sm_80`. Each runner drives one GPU, so a machine
with two GPUs runs two runners and tests both storage modes at once.

## One-time setup (per machine)

1. **Dedicated account.** Run the runners as a non-root account with no sudo, no
   SSH keys or credentials, and no access to other users' files.
2. **Log in as that account** over SSH or with `machinectl shell <account>@`.
   `sudo -u` and `su` do not set up a session for systemd user services, and
   `systemctl --user` then fails with "Failed to connect to bus".
3. **Install.** Clone this repository (the account cannot read other users'
   files), get a registration token from the repository's Settings -> Actions
   -> Runners -> New self-hosted runner, and run:
   ```sh
   .github/gpu-runner/install_runners.sh \
       --url https://github.com/mcdc-project/mcdc --token <token>
   ```
   For each GPU, this registers a runner (labels `gpu` and `sm_<arch>`) in
   `~/runner-gpu<N>` and runs it as the systemd user service
   `github-runner@gpu<N>` with that GPU (`CUDA_VISIBLE_DEVICES`). It also builds
   the toolchain with `setup_toolchain.sh`, installs quiet hours (below), off
   by default, and enables linger so the services run without a login and
   start at boot. Run it again after changing these files; it skips what is
   already done. `--help` lists its options (GPUs, labels, CUDA version).

   Keep `CUDA_VERSION` in the workflow equal to the toolchain's (default 13.3),
   and no newer than the driver supports (`nvidia-smi`). Optionally set
   `GPU_REGRESSION_WORKERS` in a runner's `.env` (default 6 concurrent cases
   per GPU; each uses one CPU core to compile, and GPU memory while running).
4. **Check** that the runners show as Idle under Settings -> Actions ->
   Runners. Logs are in each runner's `_diag/` directory.

If polkit does not let the account enable linger for itself, the installer
says so; ask an administrator to run `loginctl enable-linger <account>` once.
Where that is not possible either, each runner's `run.sh` can be started from
the account's crontab instead (`@reboot`, plus a check every few minutes that
starts it if it is not running), without the services or quiet hours; the
installer does not set this up.
Avoid running the runners in `tmux` or `screen`: they do not survive a reboot.

## Quiet hours

On a shared machine, the runners can stay off the GPUs at set times. During
quiet hours a runner takes no new jobs; one running a job stops when the job
finishes, never in the middle (stopping a runner cancels its job). Jobs queued
meanwhile start when quiet hours end; GitHub keeps them queued for up to 24
hours. As the runner account:

```sh
gpu-runner-quiet status   # the mode, the windows, and each runner
gpu-runner-quiet on       # follow the quiet windows
gpu-runner-quiet off      # ignore them (the default)
gpu-runner-quiet pause    # be quiet now, until `on` or `off`
```

The windows are in `~/.config/gpu-runner-quiet.conf`, one per line:

```
window = Mon-Fri 09:00-17:00
window = daily 22:00-06:00
```

A timer applies the settings every minute. A runner can still pick up a job
in the seconds after finishing one; during quiet hours its job-started hook
fails that job with an explanation and stops the runner, so at most one job
per runner needs a re-run. A config file that cannot be read fails jobs the
same way.

## Repository settings (administrator)

- Settings -> Actions -> General -> *Approval for running fork pull request
  workflows from contributors*: **Require approval for all external
  contributors**.
- The workflow itself never runs fork pull requests on these runners; see its
  header. Never add a `pull_request_target` trigger to a workflow that uses
  them.
- The workflow needs no secrets; do not give it any.
