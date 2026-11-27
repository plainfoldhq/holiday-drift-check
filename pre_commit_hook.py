#!/usr/bin/env python3
"""pre-commit entry point for holiday-drift-check: checks each staged holiday file.

    python3 pre_commit_hook.py --calendar us-federal [--years 2026-2027] [--fail-on missing,weekend]
                               [--ignore 2026-12-24] FILE [FILE ...]

Same checks and exit codes as the Action (0 ok, 1 a fail-on check found problems, 2 bad input);
with several files the highest code wins. Standard library only; no network.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import holiday_drift  # noqa: E402


def plain_annotation(level, path, line, check_name, message):
    """file:line: level: check: message (editor/terminal style) instead of GitHub's ::error syntax."""
    return "%s:%s %s: %s: %s" % (path, "%d:" % line if line else "", level, check_name, holiday_drift.clean(message))


def main(argv=None):
    if not os.environ.get("GITHUB_ACTIONS"):
        holiday_drift.annotation = plain_annotation
    p = argparse.ArgumentParser(prog="holiday-drift-check")
    p.add_argument("--calendar", required=True, help="us-federal, nyse, or a region id such as GB-ENG")
    p.add_argument("--years", default="", help="e.g. 2026-2027 (default: years in both the file and the data)")
    p.add_argument("--fail-on", default="", help="comma list of checks that fail (default missing,weekend; none = report only)")
    p.add_argument("--ignore", default="", help="comma list of dates the company deliberately differs on")
    p.add_argument("--today", default="", help=argparse.SUPPRESS)
    p.add_argument("files", nargs="+")
    a = p.parse_args(argv)
    worst = 0
    for f in a.files:
        code = holiday_drift.run({"PF_FILE": f, "PF_CALENDAR": a.calendar, "PF_YEARS": a.years,
                                  "PF_FAIL_ON": a.fail_on, "PF_IGNORE": a.ignore, "PF_TODAY": a.today})
        worst = max(worst, code)
    return worst


if __name__ == "__main__":
    sys.exit(main())
