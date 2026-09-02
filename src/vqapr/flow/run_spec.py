"""What a materialization spec is, named once, below the verbs that read it.

`check` and `run` both need to know the one spec kind that is still a file and what it cannot
execute without. That vocabulary used to live in `cli/run.py`, which meant `cli/check.py` imported
`cli/run.py` to reach it -- one CLI verb importing another to borrow a definition neither owns.

**One kind since record `139`.** A simulation is a registered run (`runs:` in a declaration
document) and is named by id; the `strategy:` run-spec file it replaced is refused by name. A
materialization has no venue, no execution table, no account and no trading period -- it takes
evaluation instants and instruments and writes a dataset -- so it stays a file until it, too, has
somewhere to be registered.

**Data only, deliberately.** The functions that read this table stay in `cli/run.py`, because
they raise `InputError` from `cli.inputs`; bringing them down here would put a `cli` import under
`flow/`.
"""

MATERIALIZATION = "datamodel"

_REQUIRED_BY_KIND = {
    MATERIALIZATION: (
        "datamodel",
        "instruments",
        "output",
        "evaluate_at",
    ),
}
"""What a materialization spec cannot execute without, keyed by the section naming the model."""
