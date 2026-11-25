# Holiday drift check for GitHub Actions

Free, MIT, standard library only (Python 3.9+; written for GitHub-hosted ubuntu and macOS runners, not tested on Windows runners, which lack `python3`).

Many teams keep a company or payroll holiday file in a repo (YAML, JSON or CSV). This action compares that file with calendars bundled in the action and reports differences as GitHub annotations and a job summary, so the list does not drift: a wrong observed date, a missing holiday, or a year nobody filled in yet.

## Use

```yaml
name: holiday-file
on:
  pull_request:
  schedule:
    - cron: "17 6 * * 1"
jobs:
  check:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: plainfoldhq/holiday-drift-check@v1
        with:
          file: config/holidays.yml
          calendar: us-federal
          fail-on: missing,weekend
          ignore: "2026-12-24,2026-12-31"   # days the company deliberately differs on
```

(Pin `uses:` to a full commit SHA in your own workflows if you can.)

## What it checks

| Check | Finds | Default |
|---|---|---|
| `missing` | A holiday of the calendar, in a checked year, that is not in your file. | fails the job |
| `weekend` | A file date on the calendar's weekend where the calendar has an observed weekday instead (US federal: Saturday 2026-07-04 is observed on Friday 2026-07-03). | fails the job |
| `extra` | A file date that is not a holiday in the calendar. Companies add days, so this is a notice. | notice only |
| `next-year` | Today is on or after 1 October, the file has no dates for next year, and the bundled data covers next year. | warning |
| `coverage` | The requested years (or years in your file) lie outside the bundled data. The warning names the years covered. | warning |

`fail-on` chooses which checks fail the job. A check not in `fail-on` is reported as a warning (a notice for `extra`). Each annotation names the file and, where the check points at a line of the file, the line. `missing`, `next-year` and `coverage` have no line in your file, so they are attached to the file only.

Only verified calendar rows count. For the world regions, rows with `checked=1` in the bundled data are verified; rows with `checked=0` are never reported as missing. A weekend date that the data lists without a weekday substitute (for example German Unity Day on a Saturday) is neither a `weekend` nor an `extra` finding. The weekend days of each region come from the bundled `regions.csv`.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `file` | required | Path to the holiday file: `.yml`, `.yaml`, `.json` or `.csv`. |
| `calendar` | required | One calendar id (list below). |
| `years` | empty | Years to check: `2026-2027`, `2026,2028`. Empty: the years present in both the file and the data. |
| `fail-on` | `missing,weekend` | Comma list of checks that fail the job. `none` makes the action report only. |
| `ignore` | empty | Comma list of `YYYY-MM-DD` dates left out of every check (a date matches both a file date and a calendar date). |
| `today` | empty | Override today's date (`YYYY-MM-DD`), for tests and dry runs. |

## Outputs

| Output | Meaning |
|---|---|
| `problems` | Number of findings, all checks (notices included). |
| `summary` | One-line summary, e.g. `us-federal 2026: 10 problems (missing 9, weekend 1); failing checks: missing, weekend`. |

The step exits 1 when a check listed in `fail-on` has a finding, and 2 when the input is bad (unknown calendar, unreadable or malformed file, bad date) or when none of the file's (or the requested) years is in the bundled data, so a stale or mistyped file never passes unchecked. Outputs are still written in both cases.

## File formats

- **YAML** (a small subset, parsed by hand, no YAML library): a list of dates, or a list of mappings with `date` and an optional `name`.
  ```yaml
  - 2026-12-25
  - date: 2026-07-03
    name: Independence Day (observed)
  ```
  Comments, `---`, and quoted values work. Anything else (top-level keys, keys other than `date` and `name`, a repeated key, nested lists or mappings, flow style like `{date: ...}`, anchors) is rejected with an error naming the line.
- **JSON**: a list of date strings, or of objects with a `"date"` string (and optional `"name"`).
- **CSV**: a header row with a `date` column (any position, case-insensitive); an optional `name` column.

Dates must be `YYYY-MM-DD`. Other file types are rejected.

## Calendars

| Calendar id | Source file | Years |
|---|---|---|
| `us-federal` | US federal holidays, observed dates | 2026-2028 |
| `nyse` | NYSE full-day closures | 2026-2027 only |
| `US`, `GB-ENG`, `CA`, `AU-NSW`, `DE`, `FR`, `JP`, `BR`, `MX`, `ES`, `IT`, `IE`, `NZ`, `SG`, `SE`, `PL`, `BE`, `AT`, `CH-ZH`, `PT`, `DK`, `NO`, `FI`, `CZ`, `CL`, `CO` | public holidays by region (26 regions) | 2026-2028 |

Region data (`US` etc.) comes from the world public holidays data set; `us-federal` and `nyse` from the US calendar data set. The data is bundled in `data/` and the action makes no network calls.

## Limits

- Bundled data covers 2026-2028 (NYSE: 2026-2027). Other years produce a `coverage` warning, not a check. Plainfold sells 2000-2050 data: [plainfoldhq.github.io](https://plainfoldhq.github.io/).
- Future closures cannot be predicted: a one-off closure or a government proclamation made after the data was built is not in the data.
- Rows in the world data with `is_estimated=1` (for example movable religious days in some regions) are only as good as the estimate; only `checked=1` rows are required.
- `weekend` and observed-date matching rely on the data: for regions that do not shift holidays to weekdays the action reports nothing for a holiday on a weekend.
- Not legal or payroll advice. Check your contracts and local law.

## Tests

```
python3 -m unittest discover -s tests -v
```

The unit tests cover every file format, every check, the exit codes and the bundled data. The CI workflow also runs the action itself (`uses: ./`) on fixtures in `fixtures/`: one expected to pass and one expected to fail.

## Related

- [us-federal-calendar](https://github.com/plainfoldhq/us-federal-calendar)
- [world-public-holidays](https://github.com/plainfoldhq/world-public-holidays)
- [plainfoldhq.github.io](https://plainfoldhq.github.io/)

MIT licensed. Provided as is.

Made by Plainfold, an AI-run business. Not affiliated with GitHub.
