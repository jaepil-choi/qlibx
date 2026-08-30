"""What a run spec is, named once, below the verbs that read it.

`check` and `run` both need to know the two run kinds and what each cannot execute without. That
vocabulary used to live in `cli/run.py`, which meant `cli/check.py` imported `cli/run.py` to reach
it -- one CLI verb importing another to borrow a definition neither verb owns.

That edge is why the eight judgments could not simply be called from `run`: moving them below the
CLI would have completed a cycle, `cli.run -> flow.judgments -> cli.run`. So the vocabulary moves
here, to a module both verbs sit above, and the edge disappears rather than being routed around.

**Data only, deliberately.** The functions that read these tables -- `spec_kind`,
`require_declared_keys`, `_require_nested_keys` -- stay in `cli/run.py`, because each raises
`InputError` from `cli.inputs`. Bringing them down here would put a `cli` import under `flow/`,
which is the same layering violation in the other direction and a quieter one: an import edge, not
a cycle, so nothing would crash to tell you.
"""

SIMULATION = "strategy"
MATERIALIZATION = "datamodel"

_REQUIRED_BY_KIND = {
    SIMULATION: (
        "strategy",
        "valuation",
        "instruments",
        "start",
        "end",
        "exchange",
        "execution_input",
        "initial_account",
    ),
    MATERIALIZATION: (
        "datamodel",
        "instruments",
        "output",
        "evaluate_at",
    ),
}
"""What each run kind cannot execute without, keyed by the component section that names it.

Two kinds, discriminated by which component the spec declares rather than by a `kind:` key of its
own. Every existing spec already says `strategy:`, so none needs an edit, and a spec cannot
disagree with itself about what it is -- a separate `kind:` could name one thing while the
component section named another.

Of the simulation's eight, `instruments` is shared and `strategy` is what `datamodel` replaces, so
**six do not apply**: `valuation`, `start`, `end`, `exchange`, `execution_input` and
`initial_account`. A materialization has no venue, no execution table, no account, no valuation and
no trading period -- `materialize()` takes evaluation instants and instruments and nothing else.
Forcing one required set on both would make an author declare six keys that mean nothing for their
run, which is the failure this tuple's own history warns about.

The six are enumerated rather than counted, because a bare number here is a claim no reader can
check without deriving it from both tuples — and the first version of this sentence said five.
"""
