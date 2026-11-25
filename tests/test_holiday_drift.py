"""Unit tests for holiday_drift. Standard library only."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
import holiday_drift as h  # noqa: E402

CALS = h.load_calendars()

FED_2026 = ["2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19", "2026-07-03",
            "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25"]


def write(tmp, name, text):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def run_main(env):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = h.run(env)
    return rc, buf.getvalue()


def kinds(findings):
    return sorted(f["check"] for f in findings)


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = self._td.name
        self.addCleanup(self._td.cleanup)

    def env(self, path, cal, **kw):
        e = {"PF_FILE": path, "PF_CALENDAR": cal, "PF_TODAY": "2026-06-01"}
        e.update({"PF_" + k.upper(): v for k, v in kw.items()})
        out = os.path.join(self.tmp, "out.txt")
        e["GITHUB_OUTPUT"] = out
        return e

    def outputs(self):
        with open(os.path.join(self.tmp, "out.txt"), encoding="utf-8") as fh:
            return dict(line.rstrip("\n").split("=", 1) for line in fh)


class TestParsers(Base):
    def test_yaml_plain_list_with_comments_and_quotes(self):
        e = h.parse_yaml('---\n# c\n- 2026-01-01  # new year\n- "2026-12-25"\n- \'2026-12-28\'\n')
        self.assertEqual([(x[0], x[2]) for x in e],
                         [(date(2026, 1, 1), 3), (date(2026, 12, 25), 4), (date(2026, 12, 28), 5)])

    def test_yaml_mappings_name_before_or_after_date(self):
        e = h.parse_yaml("- date: 2026-01-01\n  name: New Year's Day\n- name: Xmas\n  date: 2026-12-25\n")
        self.assertEqual(e[0], (date(2026, 1, 1), "New Year's Day", 1))
        self.assertEqual(e[1], (date(2026, 12, 25), "Xmas", 4))

    def test_yaml_rejects_unsupported(self):
        for bad in ["holidays:\n  - 2026-01-01\n", "- {date: 2026-01-01}\n", "- 2026-13-01\n",
                    "- name: x\n", "", "just text\n", "- 2026-1-1\n"]:
            with self.assertRaises(h.InputError, msg=bad):
                h.parse_yaml(bad)

    def test_json_strings_and_objects_with_lines(self):
        e = h.parse_json('[\n "2026-01-01",\n {"date": "2026-12-25", "name": "Xmas"}\n]\n')
        self.assertEqual([(x[0], x[1], x[2]) for x in e],
                         [(date(2026, 1, 1), "", 2), (date(2026, 12, 25), "Xmas", 3)])

    def test_json_rejects(self):
        for bad in ['{"a": 1}', "[1, 2]", '[{"name": "x"}]', "[]", "[not json", '["2026-02-30"]']:
            with self.assertRaises(h.InputError, msg=bad):
                h.parse_json(bad)

    def test_csv_date_column_any_position_and_case(self):
        e = h.parse_csv("Name,Date\nNew Year,2026-01-01\n\nXmas,2026-12-25\n")
        self.assertEqual(e, [(date(2026, 1, 1), "New Year", 2), (date(2026, 12, 25), "Xmas", 4)])

    def test_csv_rejects(self):
        for bad in ["", "name\nx\n", "date\n", "date\nnot-a-date\n"]:
            with self.assertRaises(h.InputError, msg=bad):
                h.parse_csv(bad)

    def test_unsupported_extension(self):
        p = write(self.tmp, "x.txt", "2026-01-01\n")
        with self.assertRaises(h.InputError):
            h.read_entries(p)

    def test_years_parse(self):
        self.assertEqual(h.parse_years("2026-2027,2029"), [2026, 2027, 2029])
        self.assertIsNone(h.parse_years(""))
        for bad in ["26", "2027-2026", "abc"]:
            with self.assertRaises(h.InputError):
                h.parse_years(bad)


class TestChecks(Base):
    def entries(self, dates):
        return [(date.fromisoformat(d), "", i + 1) for i, d in enumerate(dates)]

    def test_clean_file_has_no_problems(self):
        self.assertEqual(h.check(self.entries(FED_2026), CALS["us-federal"], today=date(2026, 6, 1)), [])

    def test_july4_2026_weekend(self):
        dates = [d if d != "2026-07-03" else "2026-07-04" for d in FED_2026]
        f = h.check(self.entries(dates), CALS["us-federal"], today=date(2026, 6, 1))
        self.assertEqual(kinds(f), ["missing", "weekend"])
        wk = [x for x in f if x["check"] == "weekend"][0]
        self.assertEqual(wk["line"], 6)
        self.assertIn("2026-07-03", wk["message"])
        self.assertIn("Sat", wk["message"])
        ms = [x for x in f if x["check"] == "missing"][0]
        self.assertEqual(ms["date"], date(2026, 7, 3))

    def test_missing_only(self):
        dates = [d for d in FED_2026 if d != "2026-11-26"]
        f = h.check(self.entries(dates), CALS["us-federal"], today=date(2026, 6, 1))
        self.assertEqual([(x["check"], x["date"]) for x in f], [("missing", date(2026, 11, 26))])

    def test_extra_company_day(self):
        f = h.check(self.entries(FED_2026 + ["2026-12-24"]), CALS["us-federal"], today=date(2026, 6, 1))
        self.assertEqual(kinds(f), ["extra"])
        self.assertEqual(f[0]["line"], len(FED_2026) + 1)

    def test_gb_eng_observed_boxing_day(self):
        gb = CALS["GB-ENG"]
        good = ["2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25", "2026-08-31",
                "2026-12-25", "2026-12-28"]
        self.assertEqual(h.check(self.entries(good), gb, years=[2026], today=date(2026, 6, 1)), [])
        bad = good[:-1] + ["2026-12-26"]     # Boxing Day Saturday instead of Monday Dec 28
        f = h.check(self.entries(bad), gb, years=[2026], today=date(2026, 6, 1))
        self.assertEqual(kinds(f), ["missing", "weekend"])
        self.assertIn("2026-12-28", [x for x in f if x["check"] == "weekend"][0]["message"])

    def test_gb_eng_2027_christmas_pair(self):
        gb = CALS["GB-ENG"]
        f = h.check(self.entries(["2027-12-25", "2027-12-26"]), gb, years=[2027], ignore=[], today=date(2026, 6, 1))
        weekend = [x for x in f if x["check"] == "weekend"]
        self.assertEqual(len(weekend), 2)
        self.assertIn("2027-12-27", weekend[0]["message"])
        self.assertIn("2027-12-28", weekend[1]["message"])

    def test_weekend_without_substitute_is_not_extra_or_weekend(self):
        # DE: German Unity Day 2026-10-03 is a Saturday; the data has no weekday substitute.
        f = h.check(self.entries(["2026-10-03"]), CALS["DE"], years=[2026], today=date(2026, 6, 1))
        self.assertNotIn("weekend", kinds(f))
        self.assertNotIn("extra", kinds(f))

    def test_regions_weekend_days_are_read(self):
        wk = {c.id: c.weekend for c in CALS.values()}
        self.assertEqual(wk["GB-ENG"], {5, 6})
        self.assertEqual(len(CALS) - 2, 26)

    def test_unchecked_rows_are_not_required(self):
        # 2026-12-26 (Sat) for GB-ENG is checked=0: must not be reported missing.
        f = h.check(self.entries(["2026-01-01"]), CALS["GB-ENG"], years=[2026], today=date(2026, 6, 1))
        self.assertNotIn(date(2026, 12, 26), [x["date"] for x in f])
        self.assertEqual(sum(1 for x in f if x["check"] == "missing"), 7)

    def test_ignore_list(self):
        dates = [d for d in FED_2026 if d != "2026-11-26"]
        f = h.check(self.entries(dates), CALS["us-federal"], ignore=[date(2026, 11, 26)], today=date(2026, 6, 1))
        self.assertEqual(f, [])
        f = h.check(self.entries(FED_2026 + ["2026-12-24"]), CALS["us-federal"], ignore=[date(2026, 12, 24)],
                    today=date(2026, 6, 1))
        self.assertEqual(f, [])

    def test_next_year(self):
        e = self.entries(FED_2026)
        f = h.check(e, CALS["us-federal"], today=date(2026, 10, 1))
        self.assertEqual(kinds(f), ["next-year"])
        self.assertEqual(h.check(e, CALS["us-federal"], today=date(2026, 9, 30)), [])
        # data does not cover 2029: no next-year finding in late 2028
        e28 = self.entries(["2028-01-17"])
        f = h.check(e28, CALS["us-federal"], years=[2028], today=date(2028, 11, 1))
        self.assertNotIn("next-year", kinds(f))
        # file has next year dates: fine
        f = h.check(self.entries(FED_2026 + ["2027-01-01"]), CALS["us-federal"], years=[2026],
                    today=date(2026, 11, 1))
        self.assertEqual(f, [])

    def test_coverage_requested_years(self):
        f = h.check(self.entries(["2029-01-01"]), CALS["us-federal"], years=[2029], today=date(2026, 6, 1))
        self.assertEqual(kinds(f), ["coverage"])
        self.assertIn("2026-2028", f[0]["message"])
        self.assertIn("2000-2050", f[0]["message"])
        self.assertIn("https://plainfoldhq.github.io/", f[0]["message"])
        self.assertNotIn("polar", f[0]["message"].lower())

    def test_coverage_nyse_only_two_years(self):
        f = h.check(self.entries(["2028-01-03"]), CALS["nyse"], today=date(2026, 6, 1))
        self.assertEqual(kinds(f), ["coverage"])
        self.assertIn("2026-2027", f[0]["message"])

    def test_nyse_observed(self):
        ny = ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
              "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"]
        self.assertEqual(h.check(self.entries(ny), CALS["nyse"], years=[2026], today=date(2026, 6, 1)), [])
        bad = [d if d != "2026-07-03" else "2026-07-04" for d in ny]
        f = h.check(self.entries(bad), CALS["nyse"], years=[2026], today=date(2026, 6, 1))
        self.assertEqual(kinds(f), ["missing", "weekend"])
        # Sunday case: 2027-07-04 (Sun) observed Monday 2027-07-05
        f = h.check(self.entries(["2027-07-04"]), CALS["nyse"], years=[2027], today=date(2026, 6, 1))
        self.assertIn("weekend", kinds(f))

    def test_default_years_are_intersection(self):
        f = h.check(self.entries(FED_2026), CALS["us-federal"], today=date(2026, 6, 1))
        self.assertEqual(f, [])   # 2027/2028 holidays not required when file has no such year


class TestRun(Base):
    def test_pass_exit_0_and_outputs(self):
        p = write(self.tmp, "ok.yml", "".join("- %s\n" % d for d in FED_2026))
        rc, out = run_main(self.env(p, "us-federal"))
        self.assertEqual(rc, 0)
        o = self.outputs()
        self.assertEqual(o["problems"], "0")
        self.assertIn("0 problems", o["summary"])

    def test_fail_default_on_weekend_and_annotation_has_file_and_line(self):
        p = write(self.tmp, "bad.yml", "- date: 2026-07-04\n")
        rc, out = run_main(self.env(p, "us-federal", years="2026"))
        self.assertEqual(rc, 1)
        self.assertIn("::error file=%s,line=1,title=holiday-drift-check%%3A weekend::" % p, out)
        self.assertEqual(self.outputs()["problems"], str(out.count("::error") + out.count("::warning")
                                                         + out.count("::notice")))

    def test_fail_on_extra_only_changes_exit(self):
        p = write(self.tmp, "x.yml", "".join("- %s\n" % d for d in FED_2026) + "- 2026-12-24\n")
        rc, out = run_main(self.env(p, "us-federal"))
        self.assertEqual(rc, 0)
        self.assertIn("::notice file=", out)
        rc, out = run_main(self.env(p, "us-federal", fail_on="extra"))
        self.assertEqual(rc, 1)
        self.assertIn("::error file=", out)

    def test_yaml_strict_subset(self):
        bad = {
            "nested_date.yml": "- date: 2026-12-25\n  meta:\n    date: 2026-05-01\n",
            "unknown_key.yml": "- date: 2026-12-25\n  kind: paid\n",
            "dup_key.yml": "- date: 2026-12-25\n  date: 2026-12-24\n",
            "nested_list.yml": "- date: 2026-12-25\n  tags:\n    - 2026-01-01\n",
            "top_key.yml": "holidays:\n  - 2026-12-25\n",
        }
        for name, text in bad.items():
            p = write(self.tmp, name, text)
            rc, _ = run_main(self.env(p, "us-federal"))
            self.assertEqual(rc, 2, name)
        p = write(self.tmp, "ok.yml", '# company days\n- date: "2026-12-25"  # xmas\n  name: Christmas\n- 2026-01-01\n')
        rc, _ = run_main(self.env(p, "us-federal", fail_on="none"))
        self.assertEqual(rc, 0)

    def test_fail_on_none_reports_but_passes(self):
        p = write(self.tmp, "m.yml", "- 2026-01-01\n")
        rc, out = run_main(self.env(p, "us-federal", fail_on="none"))
        self.assertEqual(rc, 0)
        self.assertIn("::warning file=", out)
        rc, _ = run_main(self.env(p, "us-federal"))
        self.assertEqual(rc, 1)

    def test_fail_on_coverage_and_next_year(self):
        p = write(self.tmp, "c.yml", "- 2029-01-01\n")
        self.assertEqual(run_main(self.env(p, "us-federal"))[0], 2)   # nothing checked is never a pass
        p = write(self.tmp, "c2.yml", "".join("- %s\n" % d for d in FED_2026) + "- 2029-01-01\n")
        self.assertEqual(run_main(self.env(p, "us-federal"))[0], 0)
        self.assertEqual(run_main(self.env(p, "us-federal", fail_on="coverage"))[0], 1)
        p = write(self.tmp, "n.yml", "".join("- %s\n" % d for d in FED_2026))
        self.assertEqual(run_main(self.env(p, "us-federal", today="2026-11-25"))[0], 0)
        self.assertEqual(run_main(self.env(p, "us-federal", today="2026-11-25", fail_on="next-year"))[0], 1)

    def test_ignore_input(self):
        p = write(self.tmp, "i.yml", "".join("- %s\n" % d for d in FED_2026 if d != "2026-11-26"))
        self.assertEqual(run_main(self.env(p, "us-federal"))[0], 1)
        self.assertEqual(run_main(self.env(p, "us-federal", ignore="2026-11-26"))[0], 0)

    def test_malformed_files_exit_2(self):
        for name, text in [("a.yml", "holidays: [1]\n"), ("b.json", "{"), ("c.csv", "x\n1\n"),
                           ("d.txt", "2026-01-01\n")]:
            p = write(self.tmp, name, text)
            rc, out = run_main(self.env(p, "us-federal"))
            self.assertEqual(rc, 2, name)
            self.assertTrue(out.startswith("::error file="), name)

    def test_missing_file_unknown_calendar_bad_inputs(self):
        self.assertEqual(run_main(self.env(os.path.join(self.tmp, "nope.yml"), "us-federal"))[0], 2)
        p = write(self.tmp, "ok.yml", "- 2026-01-01\n")
        rc, out = run_main(self.env(p, "XX"))
        self.assertEqual(rc, 2)
        self.assertIn("GB-ENG", out)
        self.assertEqual(run_main(self.env(p, "us-federal", fail_on="bogus"))[0], 2)
        self.assertEqual(run_main(self.env(p, "us-federal", ignore="2026-1-1"))[0], 2)
        self.assertEqual(run_main(self.env(p, "us-federal", today="soon"))[0], 2)
        self.assertEqual(run_main(self.env("", "us-federal"))[0], 2)

    def test_json_and_csv_inputs_end_to_end(self):
        import json
        pj = write(self.tmp, "h.json", json.dumps([{"date": d, "name": "x"} for d in FED_2026]))
        self.assertEqual(run_main(self.env(pj, "us-federal"))[0], 0)
        pc = write(self.tmp, "h.csv", "date,name\n" + "".join("%s,x\n" % d for d in FED_2026))
        self.assertEqual(run_main(self.env(pc, "us-federal"))[0], 0)
        pc = write(self.tmp, "h2.csv", "date,name\n2026-07-04,Independence Day\n")
        rc, out = run_main(self.env(pc, "us-federal", years="2026"))
        self.assertEqual(rc, 1)
        self.assertIn("line=2", out)

    def test_step_summary_written(self):
        p = write(self.tmp, "s.yml", "- 2026-07-04\n")
        e = self.env(p, "us-federal", years="2026")
        e["GITHUB_STEP_SUMMARY"] = os.path.join(self.tmp, "sum.md")
        run_main(e)
        with open(e["GITHUB_STEP_SUMMARY"], encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("## Holiday drift check", md)
        self.assertIn("| weekend | 2026-07-04 | 1 | fail |", md)

    def test_message_cannot_inject_commands(self):
        p = write(self.tmp, "inj.csv", "date,name\n2026-12-24,evil%0A::error::x\n")
        rc, out = run_main(self.env(p, "us-federal", years="2026"))
        for line in out.splitlines():
            self.assertTrue(line.startswith("::") or "=" in line.split(" ")[0], line)

    def test_subprocess_exit_codes_and_env(self):
        p = write(self.tmp, "sp.yml", "- 2026-07-04\n")
        env = dict(os.environ, PF_FILE=p, PF_CALENDAR="us-federal", PF_YEARS="2026", PF_TODAY="2026-06-01")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "holiday_drift.py")], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("weekend", r.stdout)


class TestBundledData(unittest.TestCase):
    PAIRS = [
        ("federal_holidays.csv", "us-calendar/free/sample/federal_holidays.csv"),
        ("nyse_closures_2026_2027.csv", "us-calendar/free/sample/nyse_closures_2026_2027.csv"),
        ("public_holidays_2026_2028.csv", "world-holidays/free/data/public_holidays_2026_2028.csv"),
        ("regions.csv", "world-holidays/free/data/regions.csv"),
    ]

    def test_bundled_files_match_sources(self):
        products = os.path.abspath(os.path.join(ROOT, ".."))
        if not os.path.isdir(os.path.join(products, "us-calendar")) or \
                not os.path.isdir(os.path.join(products, "world-holidays")):
            self.skipTest("source product folders not present (public repo)")
        for name, rel in self.PAIRS:
            with open(os.path.join(ROOT, "data", name), "rb") as a, \
                    open(os.path.join(products, rel), "rb") as b:
                self.assertEqual(a.read(), b.read(), name)

    def test_calendar_ids_and_years(self):
        self.assertEqual(len(CALS), 28)
        self.assertEqual(CALS["us-federal"].years, {2026, 2027, 2028})
        self.assertEqual(CALS["nyse"].years, {2026, 2027})
        for cid, cal in CALS.items():
            if cid not in ("nyse",):
                self.assertEqual(cal.years, {2026, 2027, 2028}, cid)


if __name__ == "__main__":
    unittest.main()
