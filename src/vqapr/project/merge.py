"""Folding one registration into the workspace state, without a workspace.

Three of the four merges never touched `self`: they take a `_State`, decide whether the incoming
declaration is new, conflicting or identical, and return the next `_State` with a flag. They were
methods only because they were written inside the class that calls them, and `_merge_dataset` alone
is 122 lines of that -- the largest single thing `Workspace` held.

`_merge_run` and `_require_run_references` stay on the class: they read `self._runs` and the other
registries to check the references a run names, so they are genuinely about a workspace rather than
about a state.

Pure functions of `(_State, declaration) -> (_State, bool)`, which is what makes them testable with
a constructed state and unable to read anything the caller did not hand them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from vqapr.component.reference import ComponentRef
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.source import SourceSpec
from vqapr.domain.errors import Stage, Status
from vqapr.project.refusals import _workspace_error
from vqapr.project.state import _State


def _merge_dataset(
    state: _State, registration: DatasetRegistration, source: SourceSpec
) -> tuple[_State, bool]:
    if registration.source != source.source_id:
        raise _workspace_error(
            stage=Stage.REGISTER,
            code="dataset.source_mismatch",
            status=Status.CONFLICT,
            requirement="DatasetRegistration.source must match SourceSpec.source_id",
            observed=(
                f"registration source={registration.source!r}, source spec={source.source_id!r}"
            ),
            fix="pass a DatasetRegistration and SourceSpec that name the same source_id",
            retry="bind the dataset and physical source to the same source_id, then retry",
        )

    if registration.span is None:
        # Refused, not measured here. This method is a metadata write and opens no source; the
        # span comes from the full read `validate` already performs, so measuring again would
        # be a second scan of the same file and would turn persistence into an I/O operation.
        raise _workspace_error(
            stage=Stage.REGISTER,
            code="dataset.span_absent",
            status=Status.INVALID,
            requirement="every registration must carry a span measured while it validated",
            observed=f"dataset {str(registration.dataset_id)!r} carries no measured span",
            fix=(
                "call vqapr.public.register_dataset instead of "
                "Workspace.register_dataset directly"
            ),
            retry=(
                "register through vqapr.public.register_dataset, which validates the source "
                "which measures the span while it validates"
            ),
        )

    key = registration.dataset_id
    source_key = source.source_id
    existing_source = state.sources.get(source_key)
    if existing_source is not None and existing_source != source:
        raise _workspace_error(
            stage=Stage.REGISTER,
            code="dataset.source_conflict",
            status=Status.CONFLICT,
            requirement=(
                f"source_id {source_key!r} must keep its existing "
                "physical declaration"
            ),
            observed="a different SourceSpec is already registered",
            fix=(
                f"reuse the registered SourceSpec for {source_key!r}, or register "
                "under a new source_id"
            ),
            retry="use the existing source declaration or choose a new source_id",
        )

    existing = state.datasets.get(key)
    if existing is not None and (
        existing.span is None or existing.grain is None or existing.field_types is None
    ):
        # A quarantined registration is being repaired. It differs from its replacement
        # only in what has been MEASURED about it -- the span it never carried, the
        # grouping verdict -- or in a declaration that did not exist when it was written:
        # the grain (record `137`) and, since record `173`, the field types; the conflict
        # check below would read any of these as a changed declaration and refuse the
        # repair it advertises. Compare on the half that has always been declared, and let
        # the measurements and the later declarations be the things that change.
        repaired = replace(
            existing,
            grain=registration.grain if existing.grain is None else existing.grain,
            span=registration.span,
            field_types=registration.field_types,
            aggregated=registration.aggregated,
            source_digest=registration.source_digest,
            execution_prices=registration.execution_prices,
        )
        if repaired != registration:
            raise _workspace_error(
                stage=Stage.REGISTER,
                code="dataset.registered",
                status=Status.CONFLICT,
                requirement=(
                    f"dataset_id {key!r} must keep its existing declaration "
                    "or use a new identity"
                ),
                observed=(
                    "a different declaration is already registered; repairing a "
                    "span-less registration may add the span but must not change "
                    "anything else"
                ),
                fix=(
                    f"match the quarantined declaration for {key!r} exactly, or "
                    "register under a new dataset_id"
                ),
                retry="use the existing declaration or choose a new dataset_id",
            )
        existing = None

    if existing is not None:
        if existing == registration and existing_source == source:
            return state, False
        # The measured half -- span, the grouping verdict, the digest and the price facts -- is
        # what the one door (record `234`) measured on the bytes as they were. A file that
        # changed is refused on read (`dataset.source_changed`) with "register again" as the
        # fix, and registering again under the SAME declaration is that repair: the measurement
        # is replaced, the declaration must match. A document written before the digest existed
        # takes the same path.
        remeasured = replace(
            existing,
            span=registration.span,
            aggregated=registration.aggregated,
            source_digest=registration.source_digest,
            execution_prices=registration.execution_prices,
        )
        if remeasured == registration and existing_source == source:
            existing = None

    if existing is not None:
        raise _workspace_error(
            stage=Stage.REGISTER,
            code="dataset.registered",
            status=Status.CONFLICT,
            requirement=(
                f"dataset_id {key!r} must keep its existing declaration "
                "or use a new identity"
            ),
            observed="a different declaration is already registered",
            fix=(
                f"keep the registered declaration for {key!r} unchanged, or "
                "choose a new dataset_id"
            ),
            retry="use the existing declaration or choose a new dataset_id",
        )

    return (
        state._replace(
            datasets={**state.datasets, key: registration},
            sources={**state.sources, source_key: source},
        ),
        True,
    )


def _merge_component(state: _State, ref: ComponentRef) -> tuple[_State, bool]:
    key = ref.component_id
    existing = state.components.get(key)
    if existing is not None and existing == ref:
        return state, False
    # An edited source replaces its registration in place, under the same id.
    #
    # This used to refuse and name a NEW component_id as the repair, while `loading.py` --
    # meeting the same edit -- said "re-register the component", which is what this refused.
    # The two pointed at each other, and `docs/implementations/057` names that shape as
    # worse than a generic error.
    #
    # The real cost was never one command: a new id needed a new strategy_configs binding
    # and a spec edit, four steps for a one-line change, and the workspace accumulated
    # `mom`, `mom-eb04...`, `mom-91c7...` for one strategy. Keeping the id also makes "this
    # strategy ran 47 times across 12 fingerprints" countable, which a new id per edit
    # scatters across twelve ids where nothing counts it.
    #
    # Provenance is not weakened. A finished run pins the fingerprint it ran under in its
    # own frozen record, so what a past run used is testified to by that run, not by
    # whichever registration currently holds the id.
    return state._replace(components={**state.components, key: ref}), True


def _merge_declaration(
    state: _State,
    section: str,
    key: str,
    value: object,
    *,
    noun: str = "run_id",
) -> tuple[_State, bool]:
    """One keyed declaration folded into its section: idempotent, conflict, or new.

    `noun` is what the key IS -- `agenda_id` for the agenda-keyed sections, `component_id`
    for strategy configs -- so a refusal names the thing the author wrote (`docs/issues/archive/040`
    measured a refusal that named an agenda the author never touched).
    """
    declarations: Mapping[str, object] = getattr(state, section)
    existing = declarations.get(key)
    if existing is not None:
        if existing == value:
            return state, False
        observed = "a different declaration is already registered"
        if noun == "component_id":
            observed = (
                f"strategy {key!r} is already bound to agenda "
                f"{getattr(existing, 'agenda_id', '?')!r}"
            )
        fix = (
            f"keep the registered declaration for {key!r} unchanged, or choose a new {noun}"
        )
        if noun == "run_id":
            # A run definition is the provenance of a result, so one id pointing at two
            # configurations would be a lie -- but a component replaces in place, and the
            # skill's "editing what you registered is the ordinary loop" reads as the rule
            # for both. The author who edits a run during setup (start date, universe, the
            # strategy list) hits this refusal, and its two options were the two things they
            # did not want. The third option ships, and the refusal now names it
            # (`docs/issues/archive/084`).
            fix += (
                f", or withdraw it first with `vqapr rm run-definition {key}` and register "
                "the edited declaration again"
            )
        raise _workspace_error(
            stage=Stage.REGISTER,
            code="run.registered",
            status=Status.CONFLICT,
            requirement=(
                f"{noun} {key!r} must keep its existing declaration or use a new identity"
            ),
            observed=observed,
            fix=fix,
            retry=f"use the existing declaration or choose a new {noun}",
        )
    updated = {**declarations, key: value}
    return state._replace(**{section: updated}), True
