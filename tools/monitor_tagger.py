#!/usr/bin/env python3
"""
Hourly monitor for the facts tagger loop.
Run from cron every hour.
- If tagger is not running, restart it.
- If current time is 06:00-20:59 Cambodia time, print a status line suitable for Telegram.
- Otherwise stay silent (but still restart if needed).
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

FACTS_DIR = "/home/sarel/projects/facts"
LOGS_DIR = f"{FACTS_DIR}/logs"
DATA_DIR = f"{FACTS_DIR}/data"

CAMBODIA = ZoneInfo("Asia/Phnom_Penh")


def is_daytime() -> bool:
    now = datetime.now(CAMBODIA)
    return 6 <= now.hour < 21


def tagger_is_running() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-af", "tag_facts.py"],
            capture_output=True, text=True, timeout=5
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def restart_tagger() -> str:
    try:
        subprocess.run(
            ["nohup", "bash", f"{FACTS_DIR}/run_tag_loop.sh"],
            stdout=open(f"{LOGS_DIR}/tag_loop.log", "a"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=FACTS_DIR,
            start_new_session=True,
            check=False,
        )
        return "RESTARTED | "
    except Exception as e:
        return f"RESTART FAILED ({e}) | "


def get_status() -> str:
    try:
        manifest = json.load(open(f"{LOGS_DIR}/manifest.json"))
        total = len(manifest["months"])
        done = sum(1 for v in manifest["months"].values() if v.get("tags"))
        pct = round(100 * done / total, 1) if total else 0
    except Exception as e:
        return f"Cannot read manifest: {e}"

    restart_note = ""
    if not tagger_is_running():
        restart_note = restart_tagger()

    cur_file = ""
    cur_progress = ""
    try:
        c = open(f"{LOGS_DIR}/current_file.txt").read().strip()
        f = os.path.basename(c)
        data = json.load(open(c))
        total_facts = len(data["facts"])
        try:
            done_facts = sum(
                1 for line in open(f"{LOGS_DIR}/tagged_facts.log")
                if line.strip()
            )
        except FileNotFoundError:
            done_facts = 0
        remaining = total_facts - done_facts
        cur_file = f"{f}"
        cur_progress = f" {done_facts}/{total_facts} ({remaining} left)"
    except Exception:
        cur_file = "starting next file..."

    return f"{restart_note}Tagger: {cur_file}{cur_progress} | Overall: {done}/{total} months ({pct}% complete)"


if __name__ == "__main__":
    status = get_status()
    # Always log to a local file regardless of time
    with open(f"{LOGS_DIR}/hourly_monitor.log", "a") as fh:
        fh.write(f"{datetime.now(CAMBODIA).isoformat()} | {status}\n")

    # Only emit status during daytime so it can be piped to Telegram
    if is_daytime():
        print(status)
        sys.exit(0)
    else:
        sys.exit(0)
