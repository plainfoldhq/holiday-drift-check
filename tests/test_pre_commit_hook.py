"""pre-commit wrapper: same results as the Action entry point, highest exit code wins."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "pre_commit_hook.py")
PASS = os.path.join(ROOT, "fixtures", "pass.yml")
FAIL = os.path.join(ROOT, "fixtures", "fail.yml")


def run(*args):
    return subprocess.run([sys.executable, HOOK, *args], capture_output=True, text=True)


class Hook(unittest.TestCase):
    def test_pass_file(self):
        r = run("--calendar", "us-federal", "--today", "2026-06-01", PASS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("problems=0", r.stdout)

    def test_fail_file(self):
        r = run("--calendar", "us-federal", "--years", "2026", "--today", "2026-06-01", FAIL)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_report_only(self):
        r = run("--calendar", "us-federal", "--years", "2026", "--fail-on", "none", "--today", "2026-06-01", FAIL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_several_files_highest_code_wins(self):
        r = run("--calendar", "us-federal", "--years", "2026", "--today", "2026-06-01", PASS, FAIL)
        self.assertEqual(r.returncode, 1)
        r = run("--calendar", "nope", PASS, FAIL)
        self.assertEqual(r.returncode, 2)

    def test_same_as_action_entry_point(self):
        env = dict(os.environ, PF_FILE=FAIL, PF_CALENDAR="us-federal", PF_YEARS="2026", PF_TODAY="2026-06-01",
                   GITHUB_OUTPUT="", GITHUB_STEP_SUMMARY="")
        a = subprocess.run([sys.executable, os.path.join(ROOT, "holiday_drift.py")], capture_output=True, text=True, env=env)
        b = run("--calendar", "us-federal", "--years", "2026", "--today", "2026-06-01", FAIL)
        self.assertEqual(a.returncode, b.returncode)
        pick = lambda out: [l for l in out.splitlines() if l.startswith(("problems=", "summary="))]
        self.assertEqual(pick(a.stdout), pick(b.stdout))
        self.assertEqual(len(a.stdout.splitlines()), len(b.stdout.splitlines()))

    def test_plain_output_outside_actions(self):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        r = subprocess.run([sys.executable, HOOK, "--calendar", "us-federal", "--years", "2026", "--today",
                            "2026-06-01", FAIL], capture_output=True, text=True, env=env)
        self.assertNotIn("::error", r.stdout)
        self.assertRegex(r.stdout, r"fail\.yml:\d+: error: weekend: ")

    def test_hooks_manifest(self):
        with open(os.path.join(ROOT, ".pre-commit-hooks.yaml")) as f:
            txt = f.read()
        self.assertIn("id: holiday-drift-check", txt)
        self.assertIn("entry: pre_commit_hook.py", txt)
        self.assertTrue(os.access(HOOK, os.X_OK))


if __name__ == "__main__":
    unittest.main()
