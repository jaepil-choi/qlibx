# On Windows, a strategy naming `Asia/Seoul` fails registration as a 502 blamed on user code, until `tzdata` is installed

**Status: RECEIVED 2026-09-11 (접수) — confirmed against `develop`: `pyproject.toml` does not depend on `tzdata`, and `CalendarLookback` (`src/vqapr/data/lookback.py`) and `domain/values.py` raise a bare `ValueError("unknown IANA timezone")` that the loader attributes to the user's frame. Being fixed on `develop`.** **CLOSED 2026-09-11 by record `263` — vqapr depends on `tzdata` on Windows, and the three places that name a zone refuse through one door (`domain/values.py::iana_zone`) that says `uv add tzdata` when this Python finds no IANA database at all.**

| | |
|---|---|
| vqapr version | `0.14.4` |
| installed from | `git+https://github.com/jaepil-choi/vqapr@b8b47e6c181e65d76e8a2589fd012002dff7c8d2` |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-demo-testbed`, recorded Claude Code session (Opus 5) in a fresh project |
| python / OS | 3.12.13 / Windows 11 Enterprise 10.0.26200 |

## What I was doing

Recording the "write a strategy" demo. A fresh project had `uv add vqapr` (plus matplotlib) and
three registered datasets. The agent was asked for a 12-month momentum top-30 strategy. It wrote
`components/mom12_top30.py`, whose `inputs()` declares
`va.CalendarLookback(days=LOOKBACK_DAYS, timezone="Asia/Seoul")`, and registered it.

## What I expected

That an install of vqapr is enough to name the timezone every KRX example uses. Registration of
the datasets in the same project had already accepted `Asia/Seoul` wall times, so the zone looked
supported.

## What happened

`vqapr register components/mom12_top30.yaml` refused with status 502, `origin: "user"`, pointing at
the user's line 39. The actual cause is that the IANA database is missing on Windows: `zoneinfo`
has no system tz database there, and the `tzdata` package was not installed. The agent diagnosed
this itself (`zoneinfo.TZPATH == ()`, `ZoneInfo('Asia/Seoul')` → `ZoneInfoNotFoundError`,
`tzdata installed: False`) and ran `uv add tzdata`, after which the same registration succeeded.

The envelope below is as the agent captured it. Its command piped the output through
`head -c 1500`, so the line is truncated. Nothing else is edited.

    $ uv run vqapr register components/mom12_top30.yaml
    {"correlation_id": "d2fb324fba904c1290eae9a26d877a5a", "error": "VqaprError: register: 1 failure(s)\n  [502 component.requirements_failed] StrategyModel.requirements() must complete before run", "failures": [{"cause": {"message": "1 validation error for CalendarLookback\ntimezone\n  Value error, unknown IANA timezone: 'Asia/Seoul' [type=value_error, input_value='Asia/Seoul', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.13/v/value_error", "origin": "user", "traceback": "Traceback (most recent call last):\n  File \"C:\\demo\\my-research\\.venv\\Lib\\site-packages\\vqapr\\extension\\loading.py\", line 353, in _requirements\n    requirements = declaration()\n                   ^^^^^^^^^^^^^\n  File \"C:\\demo\\my-research\\.venv\\Lib\\site-packages\\vqapr\\authoring\\component.py\", line 111, in requirements\n    for declaration in self.inputs().values()\n                       ^^^^^^^^^^^^^\n  File \"C:\\demo\\my-research\\components\\mom12_top30.py\", line 39, in inputs\n    lookback=va.CalendarLookback(days=LOOKBACK_DAYS, timezone=TIMEZONE),\n             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"C:\\demo\\my-research\\.venv\\Lib\\site-packages\\vqapr\\data\\lookback.py\", line 29, in __init__\n    super().__init__(**fields)\n  File \"C:\\demo\\my-research\\.venv\\Lib\\site-packages\\pydantic\\main.py\", line 263, in __init__\n    validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self  [truncated here by the capturing command's head -c 1500]

Direct reproduction without a strategy, in a project that has vqapr and no `tzdata` (Windows):

    $ uv run python -c "import zoneinfo; zoneinfo.ZoneInfo('Asia/Seoul')"
    zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key Asia/Seoul'

## Reproduction

1. On Windows, in a new uv project, `uv add vqapr` (nothing else).
2. Write any StrategyModel whose input uses `CalendarLookback(..., timezone="Asia/Seoul")`.
3. `uv run vqapr register <its yaml>` → 502 `component.requirements_failed`, `origin: "user"`.
4. `uv add tzdata`, repeat step 3 → `ok: true`.

Happened once, in a recorded session. Step 4 was verified in the same session.

## Impact

Worked around by the agent in about 30 seconds. But the envelope attributes the failure to the
user's file and line (`origin: "user"`, 502), which by the `report-issue-dev` table means "your own
component raised; fix it". An agent that trusts that attribution edits its strategy instead of the
environment. In the recorded demo the workaround also adds a `uv add tzdata` step and changes
`pyproject.toml`/`uv.lock`, on camera. For the retake I pre-installed `tzdata` in the demo project.

## What would have prevented it

- Declare `tzdata` as a dependency on Windows, e.g. `tzdata; sys_platform == "win32"`. That is
  the standard remedy for `zoneinfo` on Windows.
- Or refuse an unknown zone with its own code and a `fix` that names `uv add tzdata`, not a 502
  attributed to the user's component.
