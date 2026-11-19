#!/usr/bin/env python3
"""Quiet hours for the self-hosted GPU runners.

During quiet hours the runners take no new jobs, leaving the GPUs to the
machine's other users. A running job is never interrupted: a busy runner stops
once its job finishes. Jobs queued meanwhile start when quiet hours end (GitHub
keeps a job queued for up to 24 hours).

    gpu-runner-quiet status   show the mode, the windows, and each runner
    gpu-runner-quiet on       follow the quiet windows in the config file
    gpu-runner-quiet off      ignore them: the runners take jobs at any time
    gpu-runner-quiet pause    be quiet now, until `on` or `off`

The config file (~/.config/gpu-runner-quiet.conf) holds the mode and the
windows. A systemd timer runs `gpu-runner-quiet apply` every minute, each
runner's job-started hook runs `gpu-runner-quiet check`, and install_runners.sh
runs `gpu-runner-quiet busy <runner>`. See README.md.
"""

import datetime
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
CONFIG = os.path.join(HOME, ".config", "gpu-runner-quiet.conf")
MODES = ("on", "off", "pause")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

DEFAULT_CONFIG = """\
# Quiet hours for the GPU runners; see `gpu-runner-quiet --help`.
#
# mode: on (follow the windows below), off (ignore them), or pause (quiet now).
# Change it with `gpu-runner-quiet on|off|pause`.
mode = off

# Quiet windows, one per line: days, then start-end in 24-hour local time.
# Days are a range (Mon-Fri), a list (Sat,Sun), or "daily". A window that ends
# before it starts runs past midnight (Mon-Fri 22:00-06:00 covers Monday night
# through Saturday morning).
window = Mon-Fri 09:00-17:00
"""


class ConfigError(Exception):
    pass


def parse_days(text):
    text = text.strip().lower()
    if text == "daily":
        return set(range(7))
    days = set()
    for part in text.split(","):
        if "-" in part:
            first, last = (DAYS.index(d.strip()[:3]) for d in part.split("-", 1))
            days.update((first + i) % 7 for i in range((last - first) % 7 + 1))
        else:
            days.add(DAYS.index(part.strip()[:3]))
    return days


def parse_time(text):
    hours, minutes = text.split(":")
    if not (0 <= int(hours) <= 24 and 0 <= int(minutes) < 60):
        raise ValueError(text)
    return int(hours) * 60 + int(minutes)


def parse_window(text):
    match = re.fullmatch(r"\s*(\S+)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*", text)
    if not match:
        raise ConfigError(f"window {text!r} is not like 'Mon-Fri 09:00-17:00'")
    try:
        return (
            parse_days(match.group(1)),
            parse_time(match.group(2)),
            parse_time(match.group(3)),
        )
    except ValueError:
        raise ConfigError(f"window {text!r} has an unknown day or time") from None


def read_config():
    if not os.path.exists(CONFIG):
        with open(CONFIG, "w") as file:
            file.write(DEFAULT_CONFIG)
    mode, windows = None, []
    with open(CONFIG) as file:
        for number, line in enumerate(file, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            key, _, value = (part.strip() for part in line.partition("="))
            if key == "mode" and value in MODES:
                mode = value
            elif key == "window":
                windows.append((value, parse_window(value)))
            else:
                raise ConfigError(f"{CONFIG}:{number}: cannot read {line!r}")
    if mode is None:
        raise ConfigError(f"{CONFIG} has no line 'mode = on|off|pause'")
    return mode, windows


def set_mode(mode):
    read_config()  # creates the file, and checks it before changing it
    with open(CONFIG) as file:
        text = file.read()
    text = re.sub(r"(?m)^mode\s*=.*$", f"mode = {mode}", text, count=1)
    with open(CONFIG, "w") as file:
        file.write(text)


def in_window(window, now):
    days, start, end = window
    minute = now.hour * 60 + now.minute
    today, yesterday = now.weekday(), (now.weekday() - 1) % 7
    if start <= end:
        return today in days and start <= minute < end
    # Past midnight: the part before midnight belongs to the day it starts on
    return (today in days and minute >= start) or (yesterday in days and minute < end)


def quiet_reason(mode, windows, now):
    """Why the runners are quiet now, or None if they may take jobs."""
    if mode == "pause":
        return "paused"
    if mode == "on":
        for text, window in windows:
            if in_window(window, now):
                return f"quiet window {text}"
    return None


def runners():
    """Runner instances (gpu0, ...) from the configured ~/runner-* directories."""
    names = []
    for entry in sorted(os.listdir(HOME)):
        path = os.path.join(HOME, entry)
        if entry.startswith("runner-") and os.path.exists(
            os.path.join(path, ".runner")
        ):
            names.append(entry[len("runner-") :])
    return names


def systemctl(*args):
    result = subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True
    )
    return result.stdout.strip()


def busy(name):
    """Whether runner `name` is running a job: its Runner.Worker process exists.

    Matched by executable rather than command line, which may be relative."""
    worker = os.path.realpath(
        os.path.join(HOME, f"runner-{name}", "bin", "Runner.Worker")
    )
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if os.readlink(f"/proc/{pid}/exe") == worker:
                    return True
            except OSError:  # gone, or another user's process
                pass
    return False


def runner_state(name):
    unit = f"github-runner@{name}"
    return {
        "unit": unit,
        "active": systemctl("is-active", unit) == "active",
        "enabled": systemctl("is-enabled", unit) == "enabled",
        "busy": busy(name),
    }


def apply(quiet):
    """Stop idle runners during quiet hours; start enabled ones otherwise."""
    for name in runners():
        state = runner_state(name)
        if quiet and state["active"] and not state["busy"]:
            print(f"{state['unit']}: quiet hours, stopping")
            systemctl("stop", state["unit"])
        elif not quiet and not state["active"] and state["enabled"]:
            print(f"{state['unit']}: starting")
            systemctl("start", state["unit"])


def status(mode, windows, reason):
    print(f"mode:    {mode}")
    for text, _ in windows:
        print(f"window:  {text}")
    print(f"now:     {'quiet (' + reason + ')' if reason else 'taking jobs'}")
    for name in runners():
        state = runner_state(name)
        running = "running" if state["active"] else "stopped"
        job = ", running a job" if state["busy"] else ""
        disabled = "" if state["enabled"] else ", disabled"
        print(f"{state['unit']}: {running}{job}{disabled}")


def main(argv):
    if len(argv) == 3 and argv[1] == "busy":  # for install_runners.sh
        return 0 if busy(argv[2]) else 1
    if len(argv) != 2 or argv[1] not in (
        "status",
        "on",
        "off",
        "pause",
        "apply",
        "check",
    ):
        print(__doc__.strip(), file=sys.stderr)
        return 0 if len(argv) == 2 and argv[1] in ("-h", "--help") else 2
    command = argv[1]
    try:
        if command in MODES:
            set_mode(command)
        mode, windows = read_config()
    except (ConfigError, OSError) as error:
        print(f"gpu-runner-quiet: {error}", file=sys.stderr)
        return 2
    reason = quiet_reason(mode, windows, datetime.datetime.now())
    if command == "check":
        if reason:
            print(reason)
        return 1 if reason else 0
    if command != "status":
        apply(reason is not None)
    if command != "apply":
        status(mode, windows, reason)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
