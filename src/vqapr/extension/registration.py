"""Validate and fingerprint a project-local extension reference; write nothing.

The persisting half is `project/registration.py` since record `196`. It was here, and it opened
a `Workspace.transaction` from inside `extension/` -- so the layer that installs a component sat
below the layer it wrote to, while `project/registration.py` called back down into it. A cycle,
and the wrong way round: what a workspace holds is the project's to decide.

What stays is the half that can refuse, which is the half that needs this package: fingerprint
the source, build the `ComponentRef`, and prove it conforms. `prepare_component` writes nothing
and never could.

This module is the extension registration authority, and `vqapr.extension.registration` is where
it lives.

**It was not always.** Until record `110` the implementation sat in
`vqapr._internal.extensions.registration`
with a four-line forwarding shim at this path, whose docstring promised deletion "when the
internal-transition closes". That promise was made in a file marked temporary and was still true six
months later, by which point a boundary test pinned the shim's existence. Record `110` discharged it
the other way: the shim's path became the real module's path, so no caller changed a line and the
temporary file stopped existing rather than being renewed. See
`docs/design/agent-first-surface.md` for the surface ruling this serves.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.conformance import conformance
from vqapr.extension.fingerprint import fingerprint_component


def _unreadable(kind_label: str, error: OSError, path: str | Path) -> VqaprError:
    return VqaprError(
        stage=Stage.REGISTER,
        failures=[
            Failure.bounded(
                "component.source_unreadable",
                f"{kind_label} source must be a readable Python file",
                # UNAVAILABLE (503), not CONTRACT: fingerprinting failed on an OSError while
                # reading the file at `path` -- the declared path and kind are already fine, only
                # the filesystem read failed, which is what the machine's status describes.
                status=Status.UNAVAILABLE,
                observed=str(error),
                fix=f"create or fix permissions on the {kind_label} source file at {path}",
                cause=error,
                source=FailureSource(file=str(path)),
            )
        ],
        mutation=False,
        retry_precondition="create or repair the component source, then retry",
    )


_LABELS = {
    ComponentKind.DATA_MODEL: "DataModel",
    ComponentKind.STRATEGY_MODEL: "StrategyModel",
    ComponentKind.CONSTRAINT: "Constraint",
    ComponentKind.EXCHANGE: "Exchange",
}


def prepare_component(
    project_root: str | Path,
    raw_component_id: str,
    path: str | Path,
    object_name: str,
    *,
    kind: ComponentKind,
    config: Mapping[str, object] | None = None,
) -> ComponentRef:
    """Fingerprint the source and prove the component conforms; write nothing.

    The half of registration that can refuse. Split from the write so a declaration document can
    prove every component it names before any of them is persisted (`Workspace.transaction`), and
    so a single `register_*` below is exactly this plus one write.
    """
    label = _LABELS[kind]
    target = Path(path).resolve()
    try:
        fingerprint = fingerprint_component(
            target,
            kind=kind,
            object_name=object_name,
            config=config,
        )
    except OSError as error:
        raise _unreadable(label, error, target) from error
    ref = ComponentRef.of(
        raw_component_id,
        kind,
        target,
        object_name,
        config=config,
        fingerprint=fingerprint,
    )
    conformance(ref, project_root=project_root).raise_if_failed()
    return ref
