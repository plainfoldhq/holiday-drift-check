#!/usr/bin/env python3
"""Compare a hand-maintained holiday file with bundled, verified calendars.

Standard library only (Python 3.9+). Inputs come from PF_* environment variables.
"""
import csv
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MIN_YEAR, MAX_YEAR = 2026, 2028
CHECKS = ("missing", "weekend", "extra", "next-year", "coverage")
DEFAULT_FAIL_ON = "missing,weekend"
PLAIN_LINK = "https://plainfoldhq.github.io/"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InputError(Exception):
    """Bad input: reported as one error annotation, exit code 2."""


# ----------------------------------------------------------------- dates

def parse_date(text, where=""):
    text = text.strip()
    if not DATE_RE.match(text):
        raise InputError("%snot a date in YYYY-MM-DD form: %r" % (where, text[:40]))
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise InputError("%snot a real calendar date: %r" % (where, text[:40]))


def parse_years(text):
    """'2026-2027,2029' -> sorted list of years. Empty -> None."""
    text = (text or "").strip()
    if not text:
        return None
    out = set()
    for tok in text.split(","):
        tok = tok.strip()
        m = re.match(r"^(\d{4})(?:\s*-\s*(\d{4}))?$", tok)
        if not m:
            raise InputError("years: cannot read %r (use e.g. 2026-2027 or 2026,2028)" % tok)
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if b < a or b - a > 100:
            raise InputError("years: bad range %r" % tok)
        out.update(range(a, b + 1))
    return sorted(out)


def parse_list(text):
    return [t.strip() for t in (text or "").split(",") if t.strip()]


# ----------------------------------------------------------------- calendars

class Calendar:
    def __init__(self, cal_id, label, weekend):
        self.id = cal_id
        self.label = label
        self.weekend = weekend            # set of weekday numbers (Mon=0)
        self.verified = {}                # date -> name (observed/closing dates)
        self.nominal_weekend = set()      # holiday dates on a weekend with no weekday substitute
        self.shift = {}                   # nominal weekend date -> (observed date, name)
        self.years = set()

    def add(self, d, name):
        if MIN_YEAR <= d.year <= MAX_YEAR:
            self.verified[d] = name
            self.years.add(d.year)

    def finish(self):
        # Fallback for rows named "... (observed)" whose nominal date was not linked:
        # a Friday closure stands for Saturday, a Monday closure for Sunday.
        linked = {obs for obs, _ in self.shift.values()}
        for d, name in self.verified.items():
            if d in linked or not name.endswith("(observed)"):
                continue
            nominal = d + timedelta(days=1) if d.weekday() == 4 else (
                d - timedelta(days=1) if d.weekday() == 0 else None)
            if nominal is not None and nominal.weekday() in self.weekend \
                    and nominal not in self.shift and nominal not in self.verified:
                self.shift[nominal] = (d, name)


def _weekday_set(text):
    names = {w: i for i, w in enumerate(WEEKDAYS)}
    out = set()
    for tok in parse_list(text):
        if tok not in names:
            raise InputError("data: unknown weekday %r in regions.csv" % tok)
        out.add(names[tok])
    return out


def _read_csv(name):
    with open(os.path.join(DATA_DIR, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_calendars(data_dir=None):
    global DATA_DIR
    if data_dir:
        DATA_DIR = data_dir
    cals = {}
    sat_sun = {5, 6}

    fed = Calendar("us-federal", "US federal holidays (observed dates)", set(sat_sun))
    for r in _read_csv("federal_holidays.csv"):
        nominal, observed = date.fromisoformat(r["date"]), date.fromisoformat(r["observed_date"])
        fed.add(observed, r["holiday"] + (" (observed)" if nominal != observed else ""))
        if nominal != observed and MIN_YEAR <= observed.year <= MAX_YEAR:
            fed.shift[nominal] = (observed, r["holiday"])
    fed.finish()
    cals[fed.id] = fed

    ny = Calendar("nyse", "NYSE full-day closures", set(sat_sun))
    for r in _read_csv("nyse_closures_2026_2027.csv"):
        ny.add(date.fromisoformat(r["date"]), r["reason"])
    ny.finish()
    cals[ny.id] = ny

    weekends = {r["region"]: _weekday_set(r["weekend_days"]) for r in _read_csv("regions.csv")}
    labels = {r["region"]: (r["country"] + (", " + r["subdivision"] if r["subdivision"] else ""))
              for r in _read_csv("regions.csv")}
    rows = _read_csv("public_holidays_2026_2028.csv")
    for region in weekends:
        cal = Calendar(region, labels[region], weekends[region])
        mine = [r for r in rows if r["region"] == region]
        verified = [r for r in mine if r["checked"] == "1"]
        for r in verified:
            cal.add(date.fromisoformat(r["date"]), r["name"])
        for r in mine:
            if r["checked"] == "1":
                continue
            d = date.fromisoformat(r["date"])
            if r["is_weekend"] == "1" and d not in cal.verified:
                cal.nominal_weekend.add(d)
                # link to the verified "<name> (observed)" row within 3 days after
                for k in range(1, 4):
                    obs = d + timedelta(days=k)
                    if cal.verified.get(obs) == r["name"] + " (observed)":
                        cal.shift[d] = (obs, r["name"])
                        break
        cal.finish()
        cals[region] = cal
    return cals


# ----------------------------------------------------------------- file parsing

def _strip_scalar(raw, lineno):
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        q = raw[0]
        end = raw.find(q, 1)
        if end < 0 or raw[end + 1:].strip() not in ("",) and not raw[end + 1:].strip().startswith("#"):
            raise InputError("line %d: unsupported YAML (bad quoting)" % lineno)
        return raw[1:end]
    cut = re.search(r"\s#", raw)
    if cut:
        raw = raw[:cut.start()]
    return raw.strip()


def parse_yaml(text):
    """Small safe subset: a list of dates or of mappings with date (and optional name)."""
    items = []   # each: {"date": str|None, "name": str, "line": int, "indent": int}
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped in ("---", "..."):
            continue
        if "\t" in line[:len(line) - len(line.lstrip())]:
            raise InputError("line %d: tabs are not allowed for indentation" % n)
        m = re.match(r"^(\s*)-\s+(.*)$", line)
        if m:
            indent, body = len(m.group(1)), m.group(2)
            if items and indent != items[0]["indent"]:
                raise InputError("line %d: unsupported YAML (nested list); every item must start at the same "
                                 "column as the first one" % n)
            keycol = len(line) - len(body)
            item = {"date": None, "name": "", "line": n, "indent": indent, "map": False, "keycol": keycol}
            items.append(item)
            km = re.match(r"^([A-Za-z_][\w-]*)\s*:(?:\s+(.*))?$", body)
            if km:
                item["map"] = True
                _set_key(item, km.group(1), km.group(2) or "", n)
            else:
                item["date"] = _strip_scalar(body, n)
                item["datefrom"] = n
            continue
        km = re.match(r"^(\s+)([A-Za-z_][\w-]*)\s*:(?:\s+(.*))?$", line)
        if km and items and items[-1]["map"] and len(km.group(1)) == items[-1]["keycol"]:
            _set_key(items[-1], km.group(2), km.group(3) or "", n)
            continue
        raise InputError("line %d: unsupported YAML; expected a list like '- 2026-12-25' or "
                         "'- date: 2026-12-25' (optionally with 'name:')" % n)
    if not items:
        raise InputError("YAML: no list items found")
    out = []
    for it in items:
        if not it["date"]:
            raise InputError("line %d: list item has no date" % it["line"])
        ln = it.get("datefrom", it["line"])
        out.append((parse_date(it["date"], "line %d: " % ln), it["name"], ln))
    return out


def _set_key(item, key, value, n):
    if key not in ("date", "name"):
        raise InputError("line %d: unsupported key %r; items may only have 'date' and 'name'" % (n, key[:40]))
    if key in item.get("seen", ()):
        raise InputError("line %d: duplicate key %r in one item" % (n, key))
    item.setdefault("seen", set()).add(key)
    if key == "date":
        item["date"] = _strip_scalar(value, n) if value.strip() else ""
        item["datefrom"] = n
    elif key == "name":
        item["name"] = _strip_scalar(value, n) if value.strip() else ""


def parse_json(text):
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InputError("JSON: %s" % exc)
    if not isinstance(data, list):
        raise InputError("JSON: top level must be a list of date strings or objects with a 'date'")
    lines = text.splitlines()
    out, pos = [], 0
    for i, el in enumerate(data):
        if isinstance(el, str):
            raw, name = el, ""
        elif isinstance(el, dict) and isinstance(el.get("date"), str):
            raw, name = el["date"], str(el.get("name", "") or "")
        else:
            raise InputError("JSON: item %d must be a date string or an object with a string 'date'" % (i + 1))
        d = parse_date(raw, "JSON item %d: " % (i + 1))
        ln = None
        for j in range(pos, len(lines)):       # best-effort line of this date
            if raw in lines[j]:
                ln, pos = j + 1, j
                break
        out.append((d, name, ln))
    if not out:
        raise InputError("JSON: the list is empty")
    return out


def parse_csv(text):
    import io
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise InputError("CSV: file is empty")
    cols = [h.strip().lower() for h in header]
    if "date" not in cols:
        raise InputError("CSV: needs a 'date' column in the header row (found: %s)" % ", ".join(cols))
    di = cols.index("date")
    ni = cols.index("name") if "name" in cols else None
    out = []
    for row in reader:
        if not row or all(not c.strip() for c in row):
            continue
        n = reader.line_num
        if di >= len(row):
            raise InputError("CSV line %d: row has no date column value" % n)
        d = parse_date(row[di], "CSV line %d: " % n)
        name = row[ni].strip() if ni is not None and ni < len(row) else ""
        out.append((d, name, n))
    if not out:
        raise InputError("CSV: no data rows")
    return out


def read_entries(path):
    ext = os.path.splitext(path)[1].lower()
    parsers = {".yml": parse_yaml, ".yaml": parse_yaml, ".json": parse_json, ".csv": parse_csv}
    if ext not in parsers:
        raise InputError("unsupported file type %r (use .yml, .yaml, .json or .csv)" % ext)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError("cannot read %s: %s" % (path, exc))
    return parsers[ext](text)


# ----------------------------------------------------------------- checks

def fmt(d):
    return "%s (%s)" % (d.isoformat(), WEEKDAYS[d.weekday()])


def covered_text(cal):
    ys = sorted(cal.years)
    return "%d-%d" % (ys[0], ys[-1]) if ys[-1] - ys[0] + 1 == len(ys) else ", ".join(map(str, ys))


def check(entries, cal, years=None, ignore=(), today=None):
    """Return a list of findings: dicts with check, line, message, date."""
    ignore = set(ignore)
    file_dates = {}
    for d, name, line in entries:
        file_dates.setdefault(d, (name, line))
    file_years = {d.year for d in file_dates}
    findings = []

    if years is None:
        selected = file_years & cal.years
        outside = sorted(file_years - cal.years)
    else:
        selected = set(years) & cal.years
        outside = sorted(set(years) - cal.years)

    if outside:
        findings.append({"check": "coverage", "line": None, "date": None, "message": (
            "%s data covers %s only; not checked: %s. Plainfold sells 2000-2050 holiday data: %s"
            % (cal.id, covered_text(cal), ", ".join(map(str, outside)), PLAIN_LINK))})

    def skip(d):
        return d in ignore

    for d, (name, line) in sorted(file_dates.items()):
        if d.year not in selected or skip(d):
            continue
        if d in cal.verified:
            continue
        if d.weekday() in cal.weekend and d in cal.shift and not skip(cal.shift[d][0]):
            obs, oname = cal.shift[d]
            findings.append({"check": "weekend", "line": line, "date": d, "message": (
                "%s is on the weekend; %s observes %s on %s. Use the observed date."
                % (fmt(d), cal.id, oname, fmt(obs)))})
        elif d in cal.nominal_weekend:
            continue     # a known holiday on a weekend with no weekday substitute
        else:
            findings.append({"check": "extra", "line": line, "date": d, "message": (
                "%s%s is not a %s holiday in the bundled data (company-specific days are fine)"
                % (fmt(d), " " + name if name else "", cal.id))})

    for d, name in sorted(cal.verified.items()):
        if d.year in selected and d not in file_dates and not skip(d):
            findings.append({"check": "missing", "line": None, "date": d, "message": (
                "%s %s is a %s holiday but is not in the file%s" % (fmt(d), name, cal.id,
                    " (observed for %d-01-01)" % (d.year + 1) if d.month == 12 and d.day == 31 and "New Year" in name else ""))})

    if today is not None and today >= date(today.year, 10, 1):
        ny = today.year + 1
        if ny in cal.years and ny not in file_years:
            findings.append({"check": "next-year", "line": None, "date": None, "message": (
                "today is %s and the file has no %d dates; %s data covers %d"
                % (today.isoformat(), ny, cal.id, ny))})

    order = {c: i for i, c in enumerate(CHECKS)}
    findings.sort(key=lambda f: (f["date"] or date(1, 1, 1), order[f["check"]]))
    return findings


# ----------------------------------------------------------------- output

def clean(text):
    return " ".join(str(text).replace("%", "pct").split())


def esc_data(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def esc_prop(text):
    return esc_data(text).replace(":", "%3A").replace(",", "%2C")


def annotation(level, path, line, check_name, message):
    props = "file=%s" % esc_prop(path)
    if line:
        props += ",line=%d" % line
    props += ",title=%s" % esc_prop("holiday-drift-check: " + check_name)
    return "::%s %s::%s" % (level, props, esc_data(clean(message)))


def level_for(check_name, fail_on):
    if check_name in fail_on:
        return "error"
    return "notice" if check_name == "extra" else "warning"


def build_summary(cal_id, years_text, findings, fail_on):
    counts = {c: sum(1 for f in findings if f["check"] == c) for c in CHECKS}
    parts = ", ".join("%s %d" % (c, n) for c, n in counts.items() if n)
    failing = sorted({f["check"] for f in findings if f["check"] in fail_on})
    line = "%s %s: %d problem%s" % (cal_id, years_text, len(findings), "" if len(findings) == 1 else "s")
    if parts:
        line += " (%s)" % parts
    if failing:
        line += "; failing checks: %s" % ", ".join(failing)
    return clean(line)


def markdown_summary(cal, path, years_text, findings, fail_on):
    md = ["## Holiday drift check", "",
          "File `%s` against calendar `%s` (%s), years checked: %s." % (path, cal.id, cal.label, years_text), ""]
    if not findings:
        md.append("No problems found.")
    else:
        md += ["| Check | Date | Line | Result | Detail |", "|---|---|---|---|---|"]
        for f in findings:
            res = "fail" if f["check"] in fail_on else "warn"
            md.append("| %s | %s | %s | %s | %s |" % (
                f["check"], f["date"].isoformat() if f["date"] else "",
                f["line"] or "", res, f["message"].replace("|", "\\|")))
    md += ["", "Bundled data covers %s for `%s`. Not legal or payroll advice." % (covered_text(cal), cal.id), ""]
    return "\n".join(md)


def write_outputs(env, problems, summary):
    path = env.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("problems=%d\nsummary=%s\n" % (problems, summary))
    print("problems=%d" % problems)
    print("summary=%s" % summary)


def run(env, data_dir=None):
    """Returns exit code: 0 ok, 1 a fail-on check found problems, 2 bad input."""
    path = env.get("PF_FILE", "")
    try:
        if not path:
            raise InputError("input 'file' is required")
        cal_id = (env.get("PF_CALENDAR") or "").strip()
        cals = load_calendars(data_dir)
        if cal_id not in cals:
            raise InputError("unknown calendar %r; available: %s" % (cal_id, ", ".join(sorted(cals))))
        cal = cals[cal_id]
        fail_on = parse_list(env.get("PF_FAIL_ON") or DEFAULT_FAIL_ON)
        if fail_on == ["none"]:
            fail_on = []
        for c in fail_on:
            if c not in CHECKS:
                raise InputError("fail-on: unknown check %r; known: %s (or 'none')" % (c, ", ".join(CHECKS)))
        years = parse_years(env.get("PF_YEARS", ""))
        ignore = [parse_date(t, "ignore: ") for t in parse_list(env.get("PF_IGNORE", ""))]
        today_s = (env.get("PF_TODAY") or "").strip()
        today = parse_date(today_s, "today: ") if today_s else datetime.now(timezone.utc).date()
        entries = read_entries(path)
    except InputError as exc:
        print(annotation("error", path or "(none)", None, "input", str(exc)))
        write_outputs(env, 0, "input error: " + clean(str(exc)))
        return 2

    file_years = {e[0].year for e in entries}
    if not ((set(years) if years else file_years) & cal.years):
        msg = ("nothing to check: the file's years (%s) are all outside the %s data (%s)"
               % (", ".join(map(str, sorted(set(years) if years else file_years))), cal_id, covered_text(cal)))
        print(annotation("error", path, None, "coverage", msg))
        write_outputs(env, 1, "input error: " + clean(msg))
        return 2

    findings = check(entries, cal, years, ignore, today)
    for f in findings:
        print(annotation(level_for(f["check"], fail_on), path, f["line"], f["check"], f["message"]))

    file_years = {e[0].year for e in entries}
    shown = sorted((set(years) if years else file_years) & cal.years)
    if len(shown) == 1:
        years_text = str(shown[0])
    elif shown and shown[-1] - shown[0] + 1 == len(shown):
        years_text = "%d-%d" % (shown[0], shown[-1])
    else:
        years_text = ",".join(map(str, shown)) or "none"
    summary = build_summary(cal_id, years_text, findings, fail_on)
    write_outputs(env, len(findings), summary)
    sp = env.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as fh:
            fh.write(markdown_summary(cal, path, years_text, findings, fail_on) + "\n")
    return 1 if any(f["check"] in fail_on for f in findings) else 0


def main():
    return run({
        "PF_FILE": os.environ.get("PF_FILE", ""),
        "PF_CALENDAR": os.environ.get("PF_CALENDAR", ""),
        "PF_YEARS": os.environ.get("PF_YEARS", ""),
        "PF_FAIL_ON": os.environ.get("PF_FAIL_ON", ""),
        "PF_IGNORE": os.environ.get("PF_IGNORE", ""),
        "PF_TODAY": os.environ.get("PF_TODAY", ""),
        "GITHUB_OUTPUT": os.environ.get("GITHUB_OUTPUT", ""),
        "GITHUB_STEP_SUMMARY": os.environ.get("GITHUB_STEP_SUMMARY", ""),
    })


if __name__ == "__main__":
    sys.exit(main())
