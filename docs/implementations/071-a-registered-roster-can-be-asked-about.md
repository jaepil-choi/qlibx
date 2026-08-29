# 071 — A registered roster can be asked about

`vqapr list` covered eight kinds and not the roster. So a roster could be registered and then not
inspected from the CLI at all — both first-time-user journeys ended up opening
`.vqapr/instruments.json` by hand, which is a file this surface should never require a reader to
know about.

## The shape

```
$ vqapr list instruments
{"ok": true, "stage": "workspace.list", "kind": "instruments", "count": 1,
 "items": [{"digest": "4eab6351...", "tables": {"etf": "...", "stock": "..."},
            "by_kind": {"stock": 2, "etf": 1}, "instruments": 3}]}
```

`count` is the number of rows, as it is for every other kind: a project holds one roster or none.
How many instruments that roster describes is a different question, so it is `items[0].instruments`
rather than an overload of `count`. Conflating the two would make `list instruments` the one kind
whose `count` means something else.

## Two states that are answers, not failures

**No roster.** `count: 0`, `ok: true`. Both before a workspace exists and after one exists without
a roster. `list` is the command an agent runs *first* to orient itself, and this module already
holds that line for every other kind — refusing here would make the first command a failure.

**Tables that moved after registration.** The pointer stores `schema`, `tables` and `digest` and no
counts, so the per-category numbers require reading the parquet files it points at, and that read
can fail for reasons that are not this command's business: a table moved, a disk unmounted, a
relative path resolved from somewhere else.

The counts are therefore best-effort. The digest and the declared tables are always reported —
they come from the pointer and are what identify the roster — and `unreadable` carries the reason
when the tables could not be opened. `by_kind` is then **absent rather than zero**: a count that
could not be taken is not a count of nothing.

That degradation is the whole reason the read is wrapped. Turning an orientation command into a
crash because a parquet moved would reproduce, in the newest verb, the failure mode this slice
exists to remove.

## Why it is not an `_ACCESSORS` entry

Every other kind maps to a plural property on `Workspace` and flows through `_summarize`. The
roster does not: it is a sidecar at `.vqapr/instruments.json` beside `workspace.yaml`, for the
reason `Workspace.roster_path` documents — every `register_*` rewrites the whole workspace document
under an exclusive lock, so a three-thousand-entry roster living inside it would be rewritten on
every unrelated registration and would make each diff unreadable.

So `list instruments` takes its own branch, ahead of the `_ACCESSORS` lookup, in the same way
`runs` already does for its own reason.

## Validation

```
uv run pytest tests/ -q      # 1310 passed, 13 deselected
```

`tests/cli/test_commands.py::test_list_instruments_answers_without_opening_the_sidecar_by_hand`
drives all four states through the CLI: an uninitialised directory, a workspace with no roster, a
registered roster (asserting the digest matches the one `register` returned, the per-category
counts, the instrument total and the declared table keys), and the degraded case after the tables
are deleted — where the digest still resolves, `unreadable` appears, and `by_kind` is absent rather
than reported as empty.

`instruments` appears in `vqapr list --help`, checked by invoking the parser rather than by reading
the source.
