# Self-hosted GPU runners

`.github/workflows/regression_test-gpu.yml` runs on self-hosted runners with the
labels `self-hosted`, `gpu`, and `sm_80`. Each runner drives one GPU, so a machine
with two GPUs runs two runners and tests both storage modes at once.

## One-time setup (per machine)

1. **Dedicated account.** Run the runners as a non-root account with no sudo, no
   SSH keys or credentials, and no access to other users' files.
2. **Toolchain.** As that account (conda can be called as `/usr/bin/conda` or via
   `CONDA_EXE`):
   ```sh
   .github/gpu-runner/setup_toolchain.sh ~/mcdc-gpu-toolchain 13.3
   ```
   Use a CUDA version no newer than the driver supports (`nvidia-smi`), and keep
   `CUDA_VERSION` in the workflow equal to it.
3. **Runners.** For each GPU, download the runner into its own directory (e.g.
   `~/runner-gpu0`, `~/runner-gpu1`) and register it with the **repository**
   (Settings -> Actions -> Runners -> New self-hosted runner), not an organization
   runner group:
   ```sh
   ./config.sh --url https://github.com/mcdc-project/mcdc --token <token> \
       --name "$(hostname)-gpu0" --labels gpu,sm_80 --unattended
   ```
   Then give each runner its GPU and the toolchain in its `.env` file:
   ```
   CUDA_VISIBLE_DEVICES=0
   MCDC_GPU_TOOLCHAIN=/home/<account>/mcdc-gpu-toolchain
   ```
   Optionally set `GPU_REGRESSION_WORKERS` (default 6 concurrent cases per GPU;
   each uses one CPU core to compile, and GPU memory while running).
4. **Service.** Run each runner as a systemd *user* service of the runner
   account; this needs no sudo. Log in as the account over SSH or with
   `machinectl shell <account>@` (`sudo -u` and `su` do not set up
   `XDG_RUNTIME_DIR`, and `systemctl --user` then fails with "Failed to connect
   to bus"). Then:
   ```sh
   loginctl enable-linger   # keep the services running after logout and start them at boot
   mkdir -p ~/.config/systemd/user
   cat > ~/.config/systemd/user/github-runner@.service <<'EOF'
   [Unit]
   Description=GitHub Actions runner (%i)
   After=network-online.target

   [Service]
   WorkingDirectory=%h/runner-%i
   ExecStart=%h/runner-%i/run.sh
   # Same stop behavior as svc.sh's unit: let a running job finish cleanly
   KillMode=process
   KillSignal=SIGTERM
   TimeoutStopSec=5min
   Restart=always
   RestartSec=30

   [Install]
   WantedBy=default.target
   EOF
   systemctl --user daemon-reload
   systemctl --user enable --now github-runner@gpu0 github-runner@gpu1
   ```
   `%i` is the name after `@`, so the runner directories must be
   `~/runner-gpu0`, `~/runner-gpu1`, and so on. Check that linger took with
   `loginctl show-user $USER -p Linger`; logs are in
   `journalctl --user -u github-runner@gpu0` or the runner's `_diag/` directory.

   If polkit does not let the account enable linger for itself, either:
   - ask an administrator to run `loginctl enable-linger <account>` once (no
     unit files, nothing to repeat), or
   - if users may have crontabs (see `/etc/cron.allow` and `/etc/cron.deny`),
     start each runner from cron. Save this as `~/runner-keepalive.sh` and make
     it executable:
     ```sh
     #!/bin/sh
     # Start the runner in directory $1 unless it is already running.
     cd "$1" || exit 1
     exec flock -n .keepalive.lock ./run.sh >> keepalive.log 2>&1
     ```
     and add to `crontab -e`, one pair of lines per runner:
     ```
     @reboot     $HOME/runner-keepalive.sh $HOME/runner-gpu0
     */5 * * * * $HOME/runner-keepalive.sh $HOME/runner-gpu0
     ```

   Avoid `tmux` or `screen`: they do not survive a reboot.

   `sudo ./svc.sh install <account> && sudo ./svc.sh start` (a system-wide
   service) also works where an administrator is available.

## Repository settings (administrator)

- Settings -> Actions -> General -> *Approval for running fork pull request
  workflows from contributors*: **Require approval for all external
  contributors**.
- The workflow itself never runs fork pull requests on these runners; see its
  header. Never add a `pull_request_target` trigger to a workflow that uses
  them.
- The workflow needs no secrets; do not give it any.
