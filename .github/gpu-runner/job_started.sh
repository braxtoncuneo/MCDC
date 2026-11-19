#!/usr/bin/env bash
# The runner's job-started hook (ACTIONS_RUNNER_HOOK_JOB_STARTED in its .env).
#
# During quiet hours a runner can still pick up a job in the seconds after its
# previous one finishes, before the quiet-hours timer stops it. Refuse that
# job, and stop this runner so that it does not take the rest of the queue.
# If the quiet-hours config cannot be read, refuse jobs too, rather than risk
# running during quiet hours. Installed by install_runners.sh.

reason=$("$HOME/bin/gpu-runner-quiet" check 2>&1) && exit 0
if [ $? -eq 1 ]; then
    echo "::error::This GPU runner is in its quiet hours ($reason). Re-run this job once they end."
else
    echo "::error::This GPU runner cannot read its quiet-hours settings, so it takes no jobs: $reason"
fi
systemctl --user stop --no-block "github-runner@${GPU_RUNNER_INSTANCE:?}"
exit 1
