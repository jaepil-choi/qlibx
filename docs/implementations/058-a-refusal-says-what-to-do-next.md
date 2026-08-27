# A refusal says what to do next

## Why this exists

The package's first reader is an agent, so a refusal has always been structured rather than
prose. But structure is not the same as instruction. A refusal said what was required and what was
found, and then stopped:

```json
{"code": "declaration.read.key_missing",
 "requirement": "datasets.prices must declare source_id",
 "observed": "datasets.prices declares: path"}
```

Everything there is true and none of it says what to type. The reader has to infer the action from
the diagnosis, and infer *where* from nothing at all — the document is not named, so a caller with
several declarations has to guess which one refused.

## What changed

`Failure` carries three more fields, and `Failure.bounded` requires two of them.

**`fix`** is the sentence that fixes this occurrence, in the imperative, using values the site
already has in scope. The same refusal now ends with `add source_id under datasets.prices in the
declaration YAML`.

**`explain`** is a member of `ExplainTopic`, a closed enum of seven. It points at the section of
`agent/skill/SKILL.md` that says why the whole class happens and how to stop causing it. Closed
rather than free-string so the two can be checked against each other; the check runs in both
directions, because asserting only that every topic resolves would let a section accumulate that
no refusal ever reaches.

**`source`** is a `FailureSource(file, key_path, line)` — a structure, not a formatted string.
`"datasets.yaml:12 at datasets.prices"` would force every consumer to write a regex, and that
regex breaks silently the day the wording changes. All three fields may be `None`: a refusal that
does not know its location says so rather than inventing one.

`Failure` also became `kw_only=True`. That is grammar, not taste: `observed`, `examples` and
`example_total` carry defaults, so appending two required fields after them makes the dataclass
raise `TypeError` **at class-definition time** and the module stops importing.

## The migration

49 call sites across 12 files. Four of them are helpers — `materialize._error`,
`workspace._workspace_error`, `loading._failure`, `execution_table._schema_failures` — that funnel
many callers into one construction. Those took `fix` and `explain` as parameters and forwarded
them, so each of the 74 callers supplies wording for its own failure. A single hardcoded `fix`
inside a shared helper would have produced one generic sentence at dozens of unrelated sites,
which is worse than an empty field because it looks like guidance.

**Every pre-existing `code` string survived.** 106 unique codes before, 106 after, zero added,
zero removed, verified by rebuilding the refusal inventory from source and diffing it against the
baseline captured before any of this landed.

## What review caught

An architect review returned WATCH with one P1 and eleven lesser findings. The P1 is the one worth
recording: a refusal told the reader to run `vqapr register data <file>`. There is no `data`
subcommand — `vqapr register` takes a single positional declaration path — so argparse rejects the
command outright. A refusal naming a repair that cannot run is worse than a generic error, because
it spends the reader's trust before it fails them. It had shipped in the previous step and
propagated into an implementation record before anyone typed it.

Two findings were about `fix` strings that only restated their `requirement` with the verb
swapped, which produced the test below. Two more were about `source` claiming locations it did not
have: six sites put a bare instrument id in `key_path`, which the contract defines as a position
in a document, and an in-memory account snapshot has none. Those now default to all-`None`, which
the contract explicitly endorses.

## The test that guards the premise

Nothing typed can stop a `fix` that paraphrases its own `requirement`. `Failure` refuses an empty
one, but `fix="x must be one of: a, b"` alongside `requirement="x must be one of: a, b"`
constructs, validates and ships looking exactly like guidance.

So `test_fix_is_not_a_restatement.py` walks the AST of every site and compares the two strings by
significant vocabulary. A `fix` must contribute at least one word its `requirement` did not
already use. Words are stemmed first, because the natural evasion is inflectional: swapping
`must be declared` for `declare it` looks like new vocabulary and says nothing new. Both evasions
were planted and confirmed to fail, and the stemmer was strengthened when the first version let
the paraphrase through.

## Trade-off

`cli/register.py` reports `source.file` through a `ContextVar` that `apply` sets, rather than
threading a twelfth parameter through eleven small parsing helpers to carry a value that is
constant for the whole call. `line` stays `None` everywhere: `yaml.safe_load` discards position
information, and a wrong line number sends the reader confidently to the wrong place. Recovering
it would mean switching the reader to `yaml.compose`, which is a larger change than this step.

## Validation

```
uv run --no-sync pytest -q                                   # 1,130 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

Count gate MATCH: callback_days 2096, formations 97, membership_rows 110919. Value gate exact,
with weight digests byte-identical to the Step 0 capture, so the step is parity-inert as predicted.

A real refusal, captured end to end through the public API:

```json
{"code": "source.scan.path_missing",
 "source": {"file": "nope.parquet", "key_path": null, "line": null},
 "requirement": "source 's' must point at an existing path",
 "observed": "nope.parquet",
 "fix": "check the path declared for source 's', then create or restore the file or directory at it",
 "explain": "source-access"}
```
