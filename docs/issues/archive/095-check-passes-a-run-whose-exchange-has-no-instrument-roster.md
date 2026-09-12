# 095 — `vqapr check` passes a run that dies in order planning for want of an instrument roster

**Status: CLOSED on arrival, 2026-09-10 -- record `203` (0.10.0).** The reported wheel was
`0.9.0.dev1`; commit `f80e5ea7` (2026-09-09, after that stamp) added both doors of the roster
gate: `check` judges `roster.absent` (412) for every strategy run beside its other defects
(`flow/declaration/judgments.py::_judge_roster`), and `preflight_run` refuses the same before the
run freezes (`flow/declaration/roster.py`). The reporter's contrast -- the price requirement was
preflight, the roster a mid-run 500 -- no longer holds. Still open from this report, as a small
follow-up rather than a defect: `vqapr rm` has no `instruments` kind, so a registered roster can be
replaced but not withdrawn.

Filed as `report-2026-09-09-check-passes-a-run-whose-exchange-has-no-instrument-roster.md`;
numbered on triage.

| | |
|---|---|
| vqapr version | `0.9.0.dev1` |
| installed from | `../../vqapr/dist/vqapr-0.9.0.dev1-py3-none-any.whl` |
| reported | 2026-09-09 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Running an enhanced-index book against a `KrxExchange`. I built the venue from
`krx_rules(UNIVERSE)` and used only its first return value, discarding the roster it hands back,
and I did not separately `vqapr new instruments` / register one.

## What I expected

`vqapr check <run-id>` to refuse. The skill's promise is explicit -- "**Prove it before spending a
run.** `check` writes nothing and reports every independent problem at once" -- and the venue
scaffold `vqapr new exchange --profile krx` states the requirement as a refusal:

> A run with no registered roster is **refused here** rather than charged one flat rate, because
> there is no honest answer for an instrument nobody described.

## What happened

`vqapr check enhanced-index` returned `ok: true` with `checked: ["workspace", "run", "judgments",
"preflight"]`. The run then failed in order planning:

    "code": "strategy.due.order_planning", "status": 500,
    "observed": "no instrument roster reached 'krx', so 'A005930' cannot be identified;
                 register instruments and run through the Flow",
    "requirement": "the guarded boundary must complete without raising",
    "fix": "the framework raised ValueError at simulation.due.order_planning; read `observed`,
            and if the message names something you declared, correct it and re-run"

    ValueError: no instrument roster reached 'krx', so 'A005930' cannot be identified
      ... vqapr/exchange/planning.py line 248, in _apply_venue_rules
          required = notional + rules.charge(Side.BUY, notional, instrument_id).total
      ... vqapr/exchange/listings.py line 560, in charge
          terms = self.terms_by_kind.get(self._declared(instrument_id).kind)
      ... vqapr/exchange/listings.py line 455, in _declared
          raise ValueError(...)

The contrast that makes this a report rather than a note: **the other venue requirement of the
same shape IS checked.** With `price_limits=True` and no `base` price on the execution dataset,
`check` refused the run by name before it cost anything:

    "code": "execution.requirement_missing", "status": 404,
    "observed": "price_limit needs price 'base'",
    "requirement": "the execution dataset must declare every price the Exchange requires, or the
                    feature that needs it must be switched off"

Both are "this exchange cannot price a fill without X". One is preflight, the other is a
mid-run 500.

## Reproduction

Reproduced once, and **I could not re-enter the state to capture the envelope verbatim** -- which
is why the fields above are quoted from what I extracted at the time rather than pasted as one
JSON line. `vqapr rm` has no `instruments` kind:

    $ uv run --no-sync vqapr rm instruments
    "error": "... argument kind: invalid choice: 'instruments' (choose from strategy, datamodel,
              component, run-definition, dataset)", "status": 400

A roster can be replaced by re-registering, but not withdrawn, so a workspace that has one cannot
be returned to having none. The original sequence was:

1. Register a `KrxExchange` venue and a run naming it. Register no instrument roster.
2. `vqapr check <run-id>` -> `ok: true`.
3. `vqapr run <run-id>` -> every strategy fails at `simulation.due.order_planning`.

## Impact

Cost one 11-strategy run. Cheap in isolation; the reason it is worth filing is that `check` is
the command whose entire purpose is that a run with four defects costs one command rather than
four round trips, and this defect is one `check` could see -- the exchange is registered, the
roster is a workspace fact, and neither depends on data that only exists at execution.

Half of this was my own mistake and is recorded as such on my side: I reached for `krx_rules` out
of `vqapr.public` instead of starting from `vqapr new exchange --profile krx`, whose scaffold
explains the roster, uses `krx_listings`, and even defaults `price_limits=False`. The skill's
first instruction is "Start from the scaffold" and following it would have saved all of this.

## What would have prevented it

`check` judging the exchange's roster requirement the way it already judges its price
requirement -- ideally with the same shape of message, naming the venue and the missing roster.
