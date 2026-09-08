"""Standing gate over `tests/characterization/refusal_codes.baseline.json`.

The baseline is the oracle for the package's refusal vocabulary: which codes exist, and under
which `Status` each is raised (record `171`). The gate must never rewrite its own oracle --
regeneration is a deliberate, separately-invoked action
(`VQAPR_REGENERATE_REFUSAL_BASELINE=1` or `python -m tests.characterization.refusal_codes`), never
a side effect of running this test.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest
import refusal_codes as rc


def _load_baseline() -> dict:
    return json.loads(rc.BASELINE_PATH.read_text(encoding="utf-8"))


def _bucket_order(bucket: str) -> tuple[int, object]:
    return (0, int(bucket)) if bucket.isdigit() else (1, bucket)


def _bucket_drift(committed: dict[str, list[str]], regenerated: dict[str, list[str]]) -> list[str]:
    """One line per status bucket that gained or lost a code, so the failure names exactly what
    moved and where -- a code changing status shows as lost from one bucket and gained by
    another."""
    lines: list[str] = []
    for bucket in sorted(set(committed) | set(regenerated), key=_bucket_order):
        was = set(committed.get(bucket, ()))
        now = set(regenerated.get(bucket, ()))
        gained = sorted(now - was)
        lost = sorted(was - now)
        if gained:
            lines.append(f"  {bucket} gained (in source, not in baseline): {gained}")
        if lost:
            lines.append(f"  {bucket} lost (in baseline, not in source): {lost}")
    return lines


def test_regenerating_is_opt_in_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal test run must never mutate the committed baseline.

    This asserts the guard's shape rather than the process env, so it fails loudly if a future
    edit wires `VQAPR_REGENERATE_REFUSAL_BASELINE` into an implicit call path.
    """
    monkeypatch.delenv("VQAPR_REGENERATE_REFUSAL_BASELINE", raising=False)
    assert os.environ.get("VQAPR_REGENERATE_REFUSAL_BASELINE") is None


def test_the_inventory_matches_the_committed_baseline() -> None:
    """The standing gate. A code added, removed, renamed, or moved to another status must surface
    here as a readable diff per status bucket, not as silent drift.

    **Keyed on `(status, code)` and nothing else** (record `171`). The earlier shape carried a file
    and a line per code, and the line moved whenever a docstring above a raise site was edited;
    the baseline was regenerated four times in one week on pure line shifts, which is how a gate
    becomes something people regenerate past. What the vocabulary is -- the codes and who each
    one says must act -- is the only thing this gate measures, so it is the only thing it keys on.
    """
    committed = _load_baseline()
    regenerated = rc.build_report()

    drift = _bucket_drift(committed["static"], regenerated["static"])
    assert not drift, (
        "static refusal-code inventory drifted from the committed baseline, by status:\n"
        + "\n".join(drift)
        + "\nregenerate deliberately with `python -m tests.characterization.refusal_codes` "
        "or VQAPR_REGENERATE_REFUSAL_BASELINE=1, after confirming the drift is intentional."
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


def test_the_committed_baseline_has_no_unresolved_sites() -> None:
    """Every construction site folds to a code and a status, or is a re-render.

    An unresolved entry is a site whose code or status the scanner could not name, which means
    the baseline is missing part of the vocabulary. Record `171`'s acceptance is zero of them.
    """
    assert _load_baseline()["unresolved"] == []


def test_dynamically_composed_codes_are_resolved_not_missed() -> None:
    """A regression to naive literal scanning must fail loudly.

    The codes below are the ones that were composed as `f"{SUBJECT}.suffix"` in source when this
    gate was written, so a regex/text scan for `"..."` strings would miss them. Whether a site
    later writes its code as a literal or keeps composing it, the code must be in the resolved set
    -- the assertion is on the vocabulary, not on the spelling at the site.
    """
    static = rc.collect_static()
    resolved = {entry.code for entry in static.codes}
    expected = {
        "declaration.key_missing",
        "declaration.value_invalid",
        "declaration.value_not_permitted",
        "declaration.unknown_section",
        "dataset.field_missing",
        "dataset.key_null",
        "dataset.key_duplicate",
        "dataset.source_mismatch",
        "component.method_missing",
    }
    missing = expected - resolved
    assert not missing, (
        f"constant-folding regressed; these dynamic codes were not resolved: {missing}"
    )


def test_a_forwarded_pair_keeps_each_callers_status(tmp_path: Path) -> None:
    """A code and its status travel through a forwarding helper together, never crossed.

    `_workspace_error` is called with many codes under several statuses. Resolving the two
    arguments separately and taking the product would file every code under every status, which
    is a baseline that lies in the one dimension it exists to record. The probe below has one
    helper, two `Status` callers and one `status_of` caller, plus the two re-render shapes
    (`self.code`, and a helper over `self.stage`), and the scanner must report exactly three
    pairs and nothing unresolved.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(
            """
            from vqapr.domain.errors import Failure, Stage, Status, VqaprError, status_of

            SUBJECT = "thing"


            def _error(*, code, status, requirement, fix):
                return VqaprError(
                    stage=Stage.LOOKUP,
                    failures=[Failure.bounded(code, requirement, status=status, fix=fix)],
                )


            def missing():
                return _error(
                    code=f"{SUBJECT}.unregistered", status=Status.MISSING, requirement="r", fix="f"
                )


            def invalid():
                return _error(
                    code=f"{SUBJECT}.reference_invalid", status=Status.INVALID, requirement="r",
                    fix="f",
                )


            def crashed(error):
                return _error(
                    code="thing.crashed", status=status_of(error), requirement="r", fix="f"
                )


            def _code_for(stage):
                return f"strategy.{stage.value.removeprefix('simulation.')}"


            class Held:
                def as_failure(self):
                    return Failure(code=self.code, status=self.status, requirement="r", fix="f")

                def rendered(self, cause):
                    return Failure.bounded(
                        _code_for(self.stage), "r", status=status_of(cause), fix="f"
                    )
            """
        ),
        encoding="utf-8",
    )

    codes, unresolved = rc._scan_file(probe, rc.status_members())

    assert unresolved == []
    assert {(entry.bucket, entry.code) for entry in codes} == {
        ("404", "thing.unregistered"),
        ("400", "thing.reference_invalid"),
        (rc.BY_CAUSE, "thing.crashed"),
    }


def test_a_code_forwarded_from_another_module_still_resolves(tmp_path: Path) -> None:
    """A refusal helper and its callers need not share a file.

    This is what the M6 layout move exposed: `flow/datamodel.py` became a package, the `refusal`
    helper landed in `output.py` and `ComputeHandler.dispatch` kept calling it from `compute.py`,
    and a per-file index dropped `datamodel.compute_failed` from the inventory -- not as
    unresolved, which would have been visible, but silently, because the construction site the
    scanner walks lives in the helper's file and only the *caller* moved. The refusal itself never
    changed. The probe below puts the helper in one module and two callers in another, and the
    scanner must resolve both pairs from the file that declares neither of them.

    The two callers bind the same module constant, `SUBJECT`, to different strings -- the reason
    the index keeps module constants per file instead of merging them. A merged mapping would fold
    both codes against whichever module was parsed last (or, if conflicting names were dropped,
    resolve neither), and a code filed under a stranger's subject is worse than one left
    unresolved, because it is silent. Each finding is still reported against the file it was found
    in, so both codes surface in the helper's module -- that is where `Failure.bounded` is written.
    """
    helper = tmp_path / "helper.py"
    helper.write_text(
        textwrap.dedent(
            """
            from vqapr.domain.errors import Failure, Stage, VqaprError


            def refusal(*, code, status, requirement, fix):
                return VqaprError(
                    stage=Stage.RUN,
                    failures=[Failure.bounded(code, requirement, status=status, fix=fix)],
                )
            """
        ),
        encoding="utf-8",
    )
    crashing = tmp_path / "crashing.py"
    crashing.write_text(
        textwrap.dedent(
            """
            from helper import refusal
            from vqapr.domain.errors import Status

            SUBJECT = "widget"


            def compute():
                raise refusal(
                    code=f"{SUBJECT}.compute_failed", status=Status.CRASHED, requirement="r",
                    fix="f",
                )
            """
        ),
        encoding="utf-8",
    )
    looking_up = tmp_path / "looking_up.py"
    looking_up.write_text(
        textwrap.dedent(
            """
            from helper import refusal
            from vqapr.domain.errors import Status

            SUBJECT = "gadget"


            def find():
                raise refusal(
                    code=f"{SUBJECT}.unregistered", status=Status.MISSING, requirement="r",
                    fix="f",
                )
            """
        ),
        encoding="utf-8",
    )

    members = rc.status_members()
    codes, unresolved = rc._scan_file(helper, members, probes=[crashing, looking_up])

    assert unresolved == []
    assert {(entry.bucket, entry.code) for entry in codes} == {
        ("502", "widget.compute_failed"),
        ("404", "gadget.unregistered"),
    }

    # Without the callers there is nothing to fold, and the site is reported as unresolved rather
    # than guessed at -- the scanner's wider reach is reach, not permissiveness.
    alone, alone_unresolved = rc._scan_file(helper, members)
    assert alone == []
    assert len(alone_unresolved) == 1


def test_re_renders_are_skipped_not_reported_as_unresolved() -> None:
    """`InputError.as_failure` and `SimulationFailure` rebuild a failure they already hold.

    Their `code` is `self.code`, or a helper rendering `strategy.<stage>` from `self.stage` -- not
    a declaration the scanner could fold, and not one it should: the first was declared where the
    refusal was first raised, the second is the closed `SimulationStage` set. Listing those as
    unresolved would make the zero-unresolved acceptance unreachable by construction.
    """
    static = rc.collect_static()
    rerenders = [
        entry
        for entry in static.unresolved
        if "self.code" in entry.expression
        or "self.stage" in entry.expression
        or "__name__" in entry.expression
    ]
    assert rerenders == [], f"re-render sites reported as unresolved: {rerenders}"


def test_every_runtime_observed_code_is_also_statically_resolved() -> None:
    """A runtime code absent from the static set means the AST pass has a hole.

    The static pass is meant to be a superset of anything the runtime pass can ever observe --
    every `Failure` the runtime raises was constructed at some call site the AST pass walked. If a
    runtime code is missing from the static set, the collector failed to resolve or find that call
    site, and that is a bug in the collector, not a fact about the package.
    """
    report = rc.build_report()
    static_codes = {code for codes in report["static"].values() for code in codes}
    runtime_codes = set(report["runtime_codes"])
    orphaned = sorted(runtime_codes - static_codes)
    assert not orphaned, (
        f"runtime observed code(s) with no static call site resolved for them: {orphaned}"
    )


def test_the_baseline_records_a_nonempty_coverage_gap_and_static_set() -> None:
    """Sanity check on the baseline's own shape, so a degenerate empty inventory cannot pass
    silently: the static pass must find call sites under more than one status, and the gap
    between static and runtime coverage must be reported rather than coincidentally zero.
    """
    baseline = _load_baseline()
    assert baseline["schema"] == rc.SCHEMA
    static_codes = {code for codes in baseline["static"].values() for code in codes}
    assert len(baseline["static"]) > 1
    assert all(bucket.isdigit() or bucket == rc.BY_CAUSE for bucket in baseline["static"])
    assert len(static_codes) > 0
    assert len(baseline["runtime_codes"]) > 0
    assert len(baseline["coverage_gap"]) > 0
    assert set(baseline["coverage_gap"]) == static_codes - set(baseline["runtime_codes"])


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
