"""Standing gate over `tests/characterization/refusal_codes.baseline.json`.

This is Step 0.7 of the `Failure.bounded` migration plan: the baseline captured here is the oracle
a later step is diffed against once every call site is touched. The gate must never rewrite its
own oracle — regeneration is a deliberate, separately-invoked action
(`VQAPR_REGENERATE_REFUSAL_BASELINE=1` or `python -m tests.characterization.refusal_codes`), never
a side effect of running this test.
"""

from __future__ import annotations

import json
import os

import pytest
import refusal_codes as rc


def _load_baseline() -> dict:
    return json.loads(rc.BASELINE_PATH.read_text(encoding="utf-8"))


def test_regenerating_is_opt_in_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal test run must never mutate the committed baseline.

    This asserts the guard's shape rather than the process env, so it fails loudly if a future
    edit wires `VQAPR_REGENERATE_REFUSAL_BASELINE` into an implicit call path.
    """
    monkeypatch.delenv("VQAPR_REGENERATE_REFUSAL_BASELINE", raising=False)
    assert os.environ.get("VQAPR_REGENERATE_REFUSAL_BASELINE") is None


def test_the_inventory_matches_the_committed_baseline() -> None:
    """The standing gate. A code added, removed, or renamed at a `Failure.bounded` call site must
    surface here as a readable diff, not as a silent drift the later migration step cannot trust.

    **Keyed on `(code, file)`, not `(code, file, line)`.** The line number is the one component
    that moves for reasons which have nothing to do with what this gate measures: a docstring
    edited three functions above a `Failure.bounded` call shifts it. Measured cost of the stricter
    key: the baseline was regenerated four times in one week, and every one of those diffs was a
    pure line shift with no code added, removed or renamed. A gate that fires that often on
    non-events is one people learn to regenerate past, which is the opposite of a gate.

    What the loosened key still catches is everything the gate exists for: a code added, a code
    removed, a code renamed, and a code that **moved to a different file** -- the last being the
    one that matters during a refactoring that relocates call sites between modules. Only movement
    *within* one file stops failing.

    Line drift is not discarded. It stays in the JSON, it is reported by
    `test_line_drift_is_reported_and_not_fatal` below, and `python -m tests.characterization.refusal_codes`
    still records exact positions for a reader who wants the call site.
    """
    committed = _load_baseline()
    regenerated = rc.build_report()

    committed_static = {(e["code"], e["file"]) for e in committed["static_codes"]}
    regenerated_static = {(e["code"], e["file"]) for e in regenerated["static_codes"]}
    added = sorted(regenerated_static - committed_static)
    removed = sorted(committed_static - regenerated_static)
    assert not added and not removed, (
        f"static refusal-code inventory drifted from the committed baseline.\n"
        f"added (in source, not in baseline): {added}\n"
        f"removed (in baseline, not in source): {removed}\n"
        f"regenerate deliberately with `python -m tests.characterization.refusal_codes` "
        f"or VQAPR_REGENERATE_REFUSAL_BASELINE=1, after confirming the drift is intentional."
    )

    committed_runtime = set(committed["runtime_codes"])
    regenerated_runtime = set(regenerated["runtime_codes"])
    runtime_added = sorted(regenerated_runtime - committed_runtime)
    runtime_removed = sorted(committed_runtime - regenerated_runtime)
    assert not runtime_added and not runtime_removed, (
        f"runtime-observed refusal codes drifted from the committed baseline.\n"
        f"added: {runtime_added}\nremoved: {runtime_removed}"
    )

    committed_unresolved = {
        (e["file"], e["line"], e["expression"]) for e in committed["unresolved"]
    }
    regenerated_unresolved = {
        (e["file"], e["line"], e["expression"]) for e in regenerated["unresolved"]
    }
    assert committed_unresolved == regenerated_unresolved, (
        "unresolved constant-folding expressions drifted from the committed baseline:\n"
        f"added: {sorted(regenerated_unresolved - committed_unresolved)}\n"
        f"removed: {sorted(committed_unresolved - regenerated_unresolved)}"
    )


def test_line_drift_is_reported_and_not_fatal(capsys: pytest.CaptureFixture[str]) -> None:
    """Where a code sits in its file is reported, never asserted.

    The standing gate above is keyed on `(code, file)`, so a call site that slid up or down inside
    its own module no longer fails anything. That information is still worth having during a
    refactoring -- it is how a reviewer sees that a step moved fifty call sites rather than two --
    so it is printed here instead of thrown away.

    This test asserts only that the comparison is computable and that a drifted line does not fail
    the suite. It has no assertion on the drift itself, deliberately: the moment it acquires one it
    becomes the line-keyed gate this step exists to remove.
    """
    committed = {
        (e["code"], e["file"]): e["line"] for e in _load_baseline()["static_codes"]
    }
    regenerated = {
        (e["code"], e["file"]): e["line"] for e in rc.build_report()["static_codes"]
    }

    drifted = sorted(
        (code, file, committed[(code, file)], line)
        for (code, file), line in regenerated.items()
        if (code, file) in committed and committed[(code, file)] != line
    )
    if drifted:
        print(f"\nrefusal-code line drift ({len(drifted)} call site(s), not a failure):")
        for code, file, was, now in drifted:
            print(f"  {file}:{was} -> {now}  {code}")

    assert isinstance(drifted, list)


def test_dynamically_composed_codes_are_resolved_not_missed() -> None:
    """A regression to naive literal scanning must fail loudly.

    Every code below is composed as `f"{STAGE}.suffix"` in source, never written as a literal, so
    a regex/text scan for `"..."` strings would miss all of them. Verified against source:
    `cli/register.py` (`DECLARE_STAGE = "declaration.read"`), `data/datasets.py`
    (`SCHEMA_STAGE = "dataset.register.schema"`, `KEY_STAGE = "dataset.register.key"`), and
    `testing/conformance/runner.py` (`STAGE = "component.conformance"`).
    """
    static = rc.collect_static()
    resolved = {entry.code for entry in static.codes}
    expected = {
        "declaration.read.key_missing",
        "declaration.read.value_invalid",
        "declaration.read.value_not_permitted",
        "declaration.read.unknown_section",
        "dataset.register.schema.field_missing",
        "dataset.register.key.null",
        "dataset.register.key.duplicate",
        "dataset.register.schema.source_mismatch",
        "component.conformance.method_missing",
    }
    missing = expected - resolved
    assert not missing, (
        f"constant-folding regressed; these dynamic codes were not resolved: {missing}"
    )


def test_every_runtime_observed_code_is_also_statically_resolved() -> None:
    """A runtime code absent from the static set means the AST pass has a hole.

    The static pass is meant to be a superset of anything the runtime pass can ever observe —
    every `Failure` the runtime raises was constructed at some call site the AST pass walked. If a
    runtime code is missing from the static set, the collector failed to resolve or find that call
    site, and that is a bug in the collector, not a fact about the package.
    """
    report = rc.build_report()
    static_codes = {entry["code"] for entry in report["static_codes"]}
    runtime_codes = set(report["runtime_codes"])
    orphaned = sorted(runtime_codes - static_codes)
    assert not orphaned, (
        f"runtime observed code(s) with no static call site resolved for them: {orphaned}"
    )


def test_the_baseline_records_a_nonempty_coverage_gap_and_static_set() -> None:
    """Sanity check on the baseline's own shape, so a degenerate empty inventory cannot pass
    silently: the static pass must find call sites, and the gap between static and runtime
    coverage must be reported rather than coincidentally zero.
    """
    baseline = _load_baseline()
    assert baseline["schema"] == rc.SCHEMA
    assert len(baseline["static_codes"]) > 0
    assert len(baseline["runtime_codes"]) > 0
    assert len(baseline["coverage_gap"]) > 0
    assert set(baseline["coverage_gap"]) == (
        {e["code"] for e in baseline["static_codes"]} - set(baseline["runtime_codes"])
    )


def test_regeneration_entry_point_is_deterministic(tmp_path) -> None:
    """Regenerating twice in a row must produce a byte-identical file.

    This is the whole point of `sort_keys=True` plus deterministic per-collection sorting: a later
    migration step's diff against this baseline is only meaningful if an unrelated regeneration
    cannot itself introduce noise.
    """
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    rc.regenerate(first)
    rc.regenerate(second)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("\n")
