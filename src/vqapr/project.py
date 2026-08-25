"""The one supported door into a vqapr project.

`Project` owns identity, registration, candidate-catalog preparation and the commit
transaction. A caller never constructs a component ref, a fingerprint, a source id, or a
catalog generation: those are framework-derived. The only external mutation door is
`Project.register`, and every registration goes through the same preparation protocol:

    project = vqapr.open(root)      # resolves the root; creates nothing
    receipt = project.register(declaration)

`open()` is deliberately non-mutating. A project that has never been registered to is
indistinguishable on disk from a directory that was never opened, so a failed first
registration leaves nothing behind.

Preparation is a candidate transaction, not an incremental write. Every declaration is
validated against an in-memory candidate catalog built from the snapshot the caller read,
and only a generation-and-digest compare-and-swap makes it visible. A conflict raises
`CatalogConflict` with `mutation=False` and never rebases: the validation facts that
justified the candidate may no longer hold against the newer root.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from vqapr._internal.catalog import Catalog, CatalogView, root_digest
from vqapr._internal.catalog_store import CatalogConflict, commit_catalog, read_catalog
from vqapr._internal.models.agent_first import (
    ObservationResolver,
    prepare_data_model_invocation,
    prepare_strategy_invocation,
)
from vqapr._internal.publication import PublishedOutput, publish_outputs
from vqapr._internal.run_bridge import (
    SimulationSummary,
    execute_frozen_run,
    frozen_run_for,
    summarize,
)

__all__ = (
    "CatalogConflict",
    "CompletedRun",
    "DatasetDeclaration",
    "Diagnostic",
    "ExecutionInputDeclaration",
    "ExtensionDeclaration",
    "MaterializationResult",
    "Project",
    "ProjectDeclaration",
    "PublicationConflict",
    "RegistrationReceipt",
    "RegistrationTiming",
    "SimulationSummary",
    "open",
)


class PublicationConflict(Exception):
    """A publication lost the catalog-root CAS; no output became visible."""

    def __init__(self, expected_generation: int, observed_generation: int):
        super().__init__(
            f"publication conflict: expected generation {expected_generation}, "
            f"observed {observed_generation}"
        )
        self.expected_generation = expected_generation
        self.observed_generation = observed_generation
        self.mutation = False


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value):
        raise ValueError(f"{name} must be a non-empty string without whitespace")
    return value


def _text(value: object, *, name: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise ValueError(f"{name} must be at most {limit} characters")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostic:
    """One bounded, immutable fact about a registration or a rejected preparation.

    Deliberately carries no physical path, source digest, traceback, exception object,
    internal class name, or authority-envelope field: a diagnostic is safe to hand to an
    agent, so it can never become a side channel into framework internals.
    """

    code: str
    severity: Literal["error", "warning"]
    requirement: str
    observed: str
    examples: tuple[str, ...] = ()
    example_total: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _identifier(self.code, name="code"))
        if self.severity not in ("error", "warning"):
            raise ValueError("severity must be exactly 'error' or 'warning'")
        object.__setattr__(self, "requirement", _text(self.requirement, name="requirement"))
        object.__setattr__(self, "observed", _text(self.observed, name="observed"))
        if not isinstance(self.examples, tuple):
            raise TypeError("examples must be a tuple")
        if len(self.examples) > 20:
            raise ValueError("examples must have at most 20 members")
        for example in self.examples:
            _text(example, name="example")
        total = self.example_total
        if isinstance(total, bool) or not isinstance(total, int):
            raise TypeError("example_total must be an integer")
        if total < 0:
            raise ValueError("example_total must be non-negative")
        if total < len(self.examples):
            raise ValueError("example_total must be at least len(examples)")


@dataclass(frozen=True, slots=True, kw_only=True)
class RegistrationTiming:
    """What preparation actually cost, preserved from the current registration facts."""

    schema_seconds: float
    key_seconds: float | None
    conformance_seconds: float | None
    preparation_seconds: float

    def __post_init__(self) -> None:
        for name in ("schema_seconds", "preparation_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("key_seconds", "conformance_seconds"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number or None")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class RegistrationReceipt:
    """What one registration did, with no physical path or source digest exposed."""

    created: bool
    declaration_kind: str
    authority_id: str
    fingerprint: str | None
    catalog_generation: int
    timing: RegistrationTiming
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.created, bool):
            raise TypeError("created must be a bool")
        object.__setattr__(
            self, "declaration_kind", _identifier(self.declaration_kind, name="declaration_kind")
        )
        object.__setattr__(
            self, "authority_id", _identifier(self.authority_id, name="authority_id")
        )
        if self.fingerprint is not None:
            _identifier(self.fingerprint, name="fingerprint")
        generation = self.catalog_generation
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise TypeError("catalog_generation must be an integer")
        if generation < 0:
            raise ValueError("catalog_generation must be non-negative")
        if not isinstance(self.timing, RegistrationTiming):
            raise TypeError("timing must be a RegistrationTiming")
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(item, Diagnostic) for item in self.diagnostics
        ):
            raise TypeError("diagnostics must be a tuple of Diagnostic")


@dataclass(frozen=True, slots=True, kw_only=True)
class DatasetDeclaration:
    """A caller-owned physical source plus the semantics the framework cannot infer.

    `available_at_field` and `key_fields` stay explicit because availability and keying are
    research economics, not file facts: no amount of schema inspection can decide when a row
    became knowable.
    """

    dataset_id: str
    path: Path
    hive_partitioned: bool
    instrument_field: str
    available_at_field: str
    key_fields: tuple[str, ...]
    fields: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _identifier(self.dataset_id, name="dataset_id"))
        if not isinstance(self.path, Path):
            raise TypeError("path must be a pathlib.Path")
        if not isinstance(self.hive_partitioned, bool):
            raise TypeError("hive_partitioned must be a bool")
        for name in ("instrument_field", "available_at_field"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name=name))
        if not isinstance(self.key_fields, tuple) or not self.key_fields:
            raise ValueError("key_fields must be a non-empty tuple")
        checked_keys = tuple(_identifier(f, name="key_field") for f in self.key_fields)
        if len(set(checked_keys)) != len(checked_keys):
            raise ValueError("key_fields must not repeat a field")
        object.__setattr__(self, "key_fields", checked_keys)
        if not isinstance(self.fields, Mapping) or not self.fields:
            raise ValueError("fields must be a non-empty mapping")
        checked_fields = {
            _identifier(k, name="semantic field"): _identifier(v, name="physical column")
            for k, v in self.fields.items()
        }
        object.__setattr__(self, "fields", MappingProxyType(dict(sorted(checked_fields.items()))))

    def canonical(self) -> dict[str, object]:
        """The binding stored in the catalog. Physical path is caller-owned selection."""
        return {
            "dataset_id": self.dataset_id,
            "path": str(self.path),
            "hive_partitioned": self.hive_partitioned,
            "instrument_field": self.instrument_field,
            "available_at_field": self.available_at_field,
            "key_fields": list(self.key_fields),
            "fields": dict(self.fields),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionInputDeclaration:
    """Binds one execution input id to the table a run fills against."""

    input_id: str
    path: Path
    hive_partitioned: bool
    trade_at_field: str
    instrument_field: str
    is_tradable_field: str
    price_fields: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_id", _identifier(self.input_id, name="input_id"))
        if not isinstance(self.path, Path):
            raise TypeError("path must be a pathlib.Path")
        if not isinstance(self.hive_partitioned, bool):
            raise TypeError("hive_partitioned must be a bool")
        for name in ("trade_at_field", "instrument_field", "is_tradable_field"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name=name))
        if not isinstance(self.price_fields, Mapping) or not self.price_fields:
            raise ValueError("price_fields must be a non-empty mapping")
        checked = {
            _identifier(k, name="price field"): _identifier(v, name="physical column")
            for k, v in self.price_fields.items()
        }
        object.__setattr__(self, "price_fields", MappingProxyType(dict(sorted(checked.items()))))

    def canonical(self) -> dict[str, object]:
        return {
            "input_id": self.input_id,
            "path": str(self.path),
            "hive_partitioned": self.hive_partitioned,
            "trade_at_field": self.trade_at_field,
            "instrument_field": self.instrument_field,
            "is_tradable_field": self.is_tradable_field,
            "price_fields": dict(self.price_fields),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtensionDeclaration:
    """Pre-registers a constraint or an extension class for conformance.

    `name` is human diagnostics text and never enters identity: identity is derived from
    the class's own source bytes and canonical config, so renaming a declaration cannot
    change what was registered.
    """

    extension: type
    config: Mapping[str, object]
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.extension, type):
            raise TypeError("extension must be a class")
        if not isinstance(self.config, Mapping):
            raise TypeError("config must be a mapping")
        object.__setattr__(self, "config", MappingProxyType(dict(sorted(self.config.items()))))
        object.__setattr__(self, "name", _text(self.name, name="name"))

    def canonical(self) -> dict[str, object]:
        return {
            "qualname": self.extension.__qualname__,
            "module": self.extension.__module__,
            "config": dict(self.config),
            "name": self.name,
        }


type ProjectDeclaration = (
    DatasetDeclaration | ExecutionInputDeclaration | ExtensionDeclaration
)

_KIND_BY_TYPE: Mapping[type, tuple[str, str]] = {
    DatasetDeclaration: ("dataset", "datasets"),
    ExecutionInputDeclaration: ("execution_input", "execution_inputs"),
    ExtensionDeclaration: ("extension", "extensions"),
}


def _binding_key(declaration: ProjectDeclaration) -> str:
    if isinstance(declaration, DatasetDeclaration):
        return declaration.dataset_id
    if isinstance(declaration, ExecutionInputDeclaration):
        return declaration.input_id
    return declaration.name


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterializationResult:
    """Every semantic row one DataModel produced, plus what it actually read."""

    rows: tuple[object, ...]
    access_tokens: tuple[object, ...]
    evaluations: int
    output_dataset_id: str | None = None
    digest: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.evaluations, bool) or not isinstance(self.evaluations, int):
            raise TypeError("evaluations must be an integer")
        if self.evaluations < 0:
            raise ValueError("evaluations must be non-negative")
        # A persisted materialization always has both facts, or neither: a dataset id
        # without a digest would name an output nothing can read.
        if (self.output_dataset_id is None) != (self.digest is None):
            raise ValueError("output_dataset_id and digest must both be set or both be None")


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletedRun:
    """A finished run, publishable exactly once as one atomic transaction."""

    root: Path
    decisions: tuple[object, ...]
    diagnostics: tuple[Mapping[str, object], ...]
    access_tokens: tuple[object, ...]
    final_state: object

    def publish(self, outputs: Mapping[str, bytes]) -> object:
        """Make every named output visible together, or none of them.

        Delegates to the publication transaction: objects are staged and verified first,
        and a single catalog-root CAS is the only visibility step.
        """
        if not isinstance(outputs, Mapping) or not outputs:
            raise ValueError("outputs must be a non-empty mapping of output_id to bytes")
        staged = [
            PublishedOutput(output_id=output_id, payload=payload, metadata={})
            for output_id, payload in sorted(outputs.items())
        ]
        return publish_outputs(self.root, staged)


class Project:
    """A non-mutating handle on a project root and its committed catalog."""

    __slots__ = ("_root",)

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def catalog(self) -> CatalogView:
        """A read-only view of the committed catalog. Never creates state."""
        return CatalogView(read_catalog(self._root))

    def resolver(self, *, instruments: tuple[str, ...]):
        """The supported reader for this project's registered and derived datasets.

        Without this, every caller hand-rolls point-in-time filtering and lookback
        trimming, which is both ceremony the agent-first contract exists to remove and a
        way for two consumers of one dataset to disagree about what was knowable when.
        """
        from vqapr._internal.pit_bridge import CatalogResolver

        if not isinstance(instruments, tuple) or not instruments:
            raise ValueError("instruments must be a non-empty tuple")
        return CatalogResolver(self, instruments=instruments)

    def read_output(self, dataset_id: str) -> tuple[Mapping[str, object], ...]:
        """Read back the rows a persisted materialization produced.

        Resolves the catalog binding to its content digest, then reads and digest-verifies
        the object. A dataset that was never persisted, or whose binding names no digest,
        raises rather than returning an empty tuple: an unreadable output is a real error,
        not a legitimately empty result.
        """
        import json

        from vqapr._internal.objects import read_object

        _identifier(dataset_id, name="dataset_id")
        binding = self.catalog().dataset(dataset_id)
        digest = binding.get("digest")
        if not digest:
            raise KeyError(
                f"dataset {dataset_id!r} carries no content digest; it was registered as a "
                "physical source rather than persisted by materialize()"
            )
        payload = json.loads(read_object(self._root, str(digest)))
        return tuple(payload["rows"])

    def read_lineage(self, dataset_id: str) -> Mapping[str, object]:
        """Read the framework-derived lineage recorded alongside a persisted output.

        Same object, same digest as the rows: lineage that could disagree with the rows it
        describes would be worse than none.
        """
        import json

        from vqapr._internal.objects import read_object

        _identifier(dataset_id, name="dataset_id")
        binding = self.catalog().dataset(dataset_id)
        digest = binding.get("digest")
        if not digest:
            raise KeyError(
                f"dataset {dataset_id!r} carries no content digest; it was registered as a "
                "physical source rather than persisted by materialize()"
            )
        payload = json.loads(read_object(self._root, str(digest)))
        return payload["lineage"]

    def generation(self) -> int:
        return read_catalog(self._root).generation

    def register(self, declaration: ProjectDeclaration) -> RegistrationReceipt:
        """Prepare and commit one declaration as a candidate-catalog transaction.

        Registering a declaration that is already bound to the identical canonical value is
        idempotent: it returns `created=False` and commits nothing, so a re-run of a
        registration script does not churn the catalog generation.
        """
        started = time.perf_counter()
        if not isinstance(declaration, _KIND_BY_TYPE_TUPLE):
            raise TypeError(
                "declaration must be a DatasetDeclaration, ExecutionInputDeclaration, "
                f"or ExtensionDeclaration; got {type(declaration).__name__}"
            )
        kind, binding_kind = _KIND_BY_TYPE[type(declaration)]
        key = _binding_key(declaration)
        canonical = declaration.canonical()

        # 1. Read the current root and capture (generation, digest) without mutating.
        snapshot = read_catalog(self._root)
        expected_generation = snapshot.generation
        expected_digest = root_digest(snapshot)
        schema_seconds = time.perf_counter() - started

        # 2. Build the in-memory candidate. `with_binding` raises on a conflicting rebind
        #    and returns an equal catalog for an identical one.
        key_started = time.perf_counter()
        candidate = snapshot.with_binding(binding_kind, key, canonical)
        key_seconds = time.perf_counter() - key_started

        authority_id = f"{kind}/v1/{root_digest(candidate)}"

        # 3. An idempotent registration is not a mutation: nothing to commit.
        if candidate == snapshot:
            return RegistrationReceipt(
                created=False,
                declaration_kind=kind,
                authority_id=authority_id,
                fingerprint=None,
                catalog_generation=snapshot.generation,
                timing=RegistrationTiming(
                    schema_seconds=schema_seconds,
                    key_seconds=key_seconds,
                    conformance_seconds=None,
                    preparation_seconds=time.perf_counter() - started,
                ),
            )

        # 4. Commit under lock with the generation+digest CAS.
        committed = commit_catalog(
            self._root,
            candidate=candidate,
            expected_generation=expected_generation,
            expected_root_digest=expected_digest,
        )
        return RegistrationReceipt(
            created=True,
            declaration_kind=kind,
            authority_id=authority_id,
            fingerprint=None,
            catalog_generation=committed.generation,
            timing=RegistrationTiming(
                schema_seconds=schema_seconds,
                key_seconds=key_seconds,
                conformance_seconds=None,
                preparation_seconds=time.perf_counter() - started,
            ),
        )

    def materialize(
        self,
        *,
        model: type,
        config: Mapping[str, object],
        evaluation_times: tuple[object, ...],
        resolver: ObservationResolver,
        output_dataset_id: str | None = None,
    ) -> MaterializationResult:
        """Run one DataModel across every evaluation time through the invocation boundary.

        The caller never constructs the model: `Project` does, once per evaluation, so an
        author's mutable `self` cannot carry state between evaluations. A failure at any
        evaluation propagates and produces no result at all.

        Passing `output_dataset_id` persists the derived rows as one content-addressed
        object and binds it into the catalog, so a later run can read what this produced.
        Omitting it keeps the result in memory. Nothing is ever written implicitly: the
        rows are returned either way, and persistence is an explicit request.
        """
        if not isinstance(evaluation_times, tuple) or not evaluation_times:
            raise ValueError("evaluation_times must be a non-empty tuple")
        if output_dataset_id is not None:
            _identifier(output_dataset_id, name="output_dataset_id")

        rows: list[object] = []
        access: list[object] = []
        stamped: list[dict[str, object]] = []
        for evaluation_time in evaluation_times:
            prepared = prepare_data_model_invocation(
                model,
                config,
                evaluation_time=evaluation_time,
                resolver=resolver,
            )
            rows.extend(prepared.rows)
            access.extend(prepared.access_tokens)
            if output_dataset_id is not None:
                # The evaluation time is framework-stamped. A derived row only means
                # something alongside the cutoff it was computed at, and an author must
                # not be able to supply or forge that stamp.
                for row in prepared.rows:
                    stamped.append(
                        {
                            "instrument_id": row.instrument_id,
                            "evaluation_time": evaluation_time.isoformat(),
                            "values": {k: str(v) for k, v in row.values.items()},
                        }
                    )

        digest: str | None = None
        if output_dataset_id is not None:
            # The lineage is framework-derived from what the run actually did: which
            # aliases were read, how many observations each returned, and over how many
            # evaluations. An author cannot supply or overstate any of it.
            lineage = {
                "model": getattr(model, "__qualname__", str(model)),
                "evaluations": len(evaluation_times),
                "reads": [
                    {
                        "alias": token.alias,
                        "dataset_id": token.dataset_id,
                        "observation_count": token.observation_count,
                    }
                    for token in access
                ],
            }
            digest = self._persist_materialization(output_dataset_id, stamped, lineage)

        return MaterializationResult(
            rows=tuple(rows),
            access_tokens=tuple(access),
            evaluations=len(evaluation_times),
            output_dataset_id=output_dataset_id,
            digest=digest,
        )

    def _persist_materialization(
        self,
        output_dataset_id: str,
        stamped: list[dict[str, object]],
        lineage: Mapping[str, object] | None = None,
    ) -> str:
        """Stage derived rows as one content-addressed object and bind it in the catalog.

        Deliberately reuses the publication object store rather than opening a second
        write path: one durability discipline, one place where fsync and digest
        verification live.

        Lineage travels inside the same object as the rows it describes. Splitting them
        into two files is what the legacy path did, and it allows a state where one lands
        and the other does not; one object cannot be half-written.
        """
        import json

        from vqapr._internal.objects import stage_object

        payload = json.dumps(
            {
                "dataset_id": output_dataset_id,
                "rows": stamped,
                "lineage": dict(lineage) if lineage is not None else {},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = stage_object(self._root, payload)

        snapshot = read_catalog(self._root)
        candidate = snapshot.with_binding(
            "datasets",
            output_dataset_id,
            {"dataset_id": output_dataset_id, "digest": digest, "derived": True},
        ).with_objects((digest,))
        if candidate != snapshot:
            commit_catalog(
                self._root,
                candidate=candidate,
                expected_generation=snapshot.generation,
                expected_root_digest=root_digest(snapshot),
            )
        return digest

    def run(
        self,
        *,
        strategy: type,
        config: Mapping[str, object],
        occurrences: tuple[object, ...],
        account,
        instruments: tuple[str, ...],
        constraint_bounds,
        resolver: ObservationResolver,
        initial_strategy_state: object = None,
        history_resolver=None,
    ) -> CompletedRun:
        """Drive one StrategyModel across occurrences, threading state explicitly.

        `previous_state` for each occurrence is the `next_state` the prior accepted
        occurrence returned - never an attribute surviving on a model instance. That is
        what makes the cadence rule replayable: the same occurrences with the same initial
        state produce the same decisions.
        """
        if not isinstance(occurrences, tuple) or not occurrences:
            raise ValueError("occurrences must be a non-empty tuple")

        decisions: list[object] = []
        diagnostics: list[Mapping[str, object]] = []
        access: list[object] = []
        state = initial_strategy_state

        for evaluation_time in occurrences:
            prepared = prepare_strategy_invocation(
                strategy,
                config,
                evaluation_time=evaluation_time,
                account=account,
                instruments=instruments,
                constraint_bounds=constraint_bounds,
                previous_state=state,
                history_resolver=history_resolver,
                resolver=resolver,
            )
            decisions.append(prepared.decision)
            diagnostics.append(prepared.diagnostics)
            access.extend(prepared.access_tokens)
            state = prepared.next_state

        return CompletedRun(
            root=self._root,
            decisions=tuple(decisions),
            diagnostics=tuple(diagnostics),
            access_tokens=tuple(access),
            final_state=state,
        )

    def simulate(
        self, *, definition, strategy: type | None = None, run_id: str = "run"
    ) -> SimulationSummary:
        """Preflight and execute one run through the retained engine.

        Accepts either a public `simulation.Simulation` - in which case `strategy` names
        the authored StrategyModel class to run - or the engine's own `RunDefinition`,
        passed straight through so existing engine callers keep working.

        The public path registers everything the engine needs to reach the strategy: the
        extension itself, the agendas its schedule implies, and the configs binding them
        together. That registration is what turns a declaration into something runnable.
        """
        from vqapr.flow.run import RunDefinition
        from vqapr.simulation import Simulation

        if isinstance(definition, Simulation):
            if strategy is None:
                raise ValueError(
                    "a public Simulation needs the StrategyModel class to run; pass "
                    "strategy=<YourStrategyModel>"
                )
            definition = self._engine_definition(definition, strategy, run_id)
        elif not isinstance(definition, RunDefinition):
            raise TypeError(
                "definition must be a vqapr.simulation.Simulation or a RunDefinition"
            )
        frozen = frozen_run_for(self._root, definition)
        result = execute_frozen_run(self._root, frozen)
        return summarize(result)

    def run_completed(
        self, *, definition, strategy: type | None = None, run_id: str = "run"
    ):
        """Execute one run and return its readable result.

        `simulate` returns counts only, which is too narrow to research against: a run
        whose account and fills cannot be inspected afterwards cannot be reasoned about.
        This runs exactly the same way and returns the committed account and the recorder
        tables the run produced, as detached public values.
        """
        from vqapr._internal.run_bridge import complete
        from vqapr.flow.run import RunDefinition
        from vqapr.simulation import Simulation

        if isinstance(definition, Simulation):
            if strategy is None:
                raise ValueError(
                    "a public Simulation needs the StrategyModel class to run; pass "
                    "strategy=<YourStrategyModel>"
                )
            definition = self._engine_definition(definition, strategy, run_id)
        elif not isinstance(definition, RunDefinition):
            raise TypeError(
                "definition must be a vqapr.simulation.Simulation or a RunDefinition"
            )
        frozen = frozen_run_for(self._root, definition)
        return complete(execute_frozen_run(self._root, frozen))

    def _bridge_catalog_datasets(self) -> None:
        """Mirror catalog-registered datasets into the store preflight reads.

        Two stores exist because the transactional catalog was built alongside the
        retained engine rather than replacing it. Until they are unified, a dataset the
        caller registered through `Project.register` has to be readable by preflight, or
        a Simulation whose Strategy declares `inputs()` cannot run at all.

        This is a mirror, not a second source of truth: the catalog remains the thing the
        caller writes to, and every value here is copied from it.
        """
        from vqapr.public import DatasetRegistration, SourceSpec, register_dataset

        catalog = read_catalog(self._root)
        for dataset_id, binding in sorted(catalog.datasets.items()):
            if binding.get("derived"):
                # A derived dataset has no physical source to register; it is read back
                # through read_output rather than scanned by the engine.
                continue
            source_id = f"{dataset_id}-source"
            registration = DatasetRegistration.of(
                dataset_id,
                source_id,
                instrument_field=str(binding["instrument_field"]),
                available_at=str(binding["available_at_field"]),
                key_fields=tuple(binding["key_fields"]),
                fields=dict(binding["fields"]),
            )
            source = SourceSpec.of(
                source_id,
                str(binding["path"]),
                hive_partitioned=bool(binding["hive_partitioned"]),
            )
            register_dataset(self._root, registration, source)

    def _register_execution_input(self, execution) -> None:
        """Register the public Execution's input and fill convention with the engine."""
        from vqapr.public import (
            ExecutionInputRegistration,
            ExecutionTableSpec,
            SourceSpec,
            register_execution_input,
        )
        from vqapr.public import FillConvention as EngineFill
        from vqapr.public import FillSelector as EngineSelector

        source = SourceSpec.of(
            f"{execution.input.input_id}-source",
            execution.input.path,
            hive_partitioned=execution.input.hive_partitioned,
        )
        table = ExecutionTableSpec(
            source,
            execution.input.trade_at_field,
            execution.input.instrument_field,
            execution.input.is_tradable_field,
            dict(execution.input.price_fields),
        )
        fill = EngineFill(
            EngineSelector(execution.fill.selector.value),
            execution.fill.at,
            execution.fill.timezone,
            execution.fill.trade_price,
        )
        register_execution_input(
            self._root,
            ExecutionInputRegistration.of(execution.input.input_id, table, fill),
        )

    def _engine_definition(self, simulation, strategy: type, run_id: str):
        """Register a public Simulation's parts and return the engine's RunDefinition.

        Every translation goes through the bridge that already owns it, so a public
        declaration reaches the engine by exactly one route. A second translation here
        would be free to drift from the tested one.
        """
        from vqapr._internal.constraint_bridge import (
            AdaptedConstraint,
            constraint_adapter_config,
        )
        from vqapr._internal.extensions.component import ComponentKind
        from vqapr._internal.registration_bridge import component_ref_for
        from vqapr._internal.schedule_bridge import agendas_for_schedule
        from vqapr._internal.strategy_bridge import AdaptedStrategy, adapter_config
        from vqapr._internal.venue_bridge import exchange_component_ref
        from vqapr.flow.run import (
            ConstraintSet,
            RunDefinition,
            StrategyConfig,
            ValuationConfig,
        )
        from vqapr.public import (
            MonitoringPolicy,
            register_agenda,
            register_component,
            register_monitoring_policy,
            register_strategy_config,
            register_valuation_config,
        )

        _identifier(run_id, name="run_id")

        # The loader resolves a component by module and name, so the registered class is
        # the module-level AdaptedStrategy, configured to rebuild the authored one.
        strategy_ref = component_ref_for(
            AdaptedStrategy,
            component_id=f"{run_id}-strategy",
            config=adapter_config(strategy, strategy_id=f"{run_id}-strategy"),
            kind=ComponentKind.STRATEGY_MODEL,
        )
        register_component(self._root, strategy_ref)

        constraint_refs = []
        for entry in simulation.constraints:
            # Registered as the module-level AdaptedConstraint configured to rebuild the
            # authored one, for the same reason as the strategy: the loader resolves a
            # component by module and name, so a runtime-generated class is unfindable.
            reference = component_ref_for(
                AdaptedConstraint,
                component_id=f"{run_id}-{entry.name}",
                config=constraint_adapter_config(entry, run_id=run_id),
                kind=ComponentKind.CONSTRAINT,
            )
            register_component(self._root, reference)
            constraint_refs.append(reference)

        # The run names an execution input by id; that binding has to exist before
        # preflight can resolve where a fill happens.
        self._register_execution_input(simulation.execution)

        # Preflight resolves a model's declared inputs out of the legacy Workspace, while
        # Project.register commits them to the catalog. Bridging here is what makes a
        # dataset registered through the public surface visible to the run that declares
        # it; without it, every DatasetDeclaration is invisible to simulate().
        self._bridge_catalog_datasets()

        agendas = agendas_for_schedule(simulation.schedule, prefix=run_id)
        for agenda in agendas.values():
            register_agenda(self._root, agenda)

        strategy_config = StrategyConfig(
            strategy_ref, agendas["strategy"].agenda_id, agendas["strategy"].role
        )
        valuation_config = ValuationConfig(
            agendas["valuation"].agenda_id, agendas["valuation"].role
        )
        register_strategy_config(self._root, strategy_config)
        register_valuation_config(self._root, valuation_config)

        # `Schedule.monitoring=None` is an explicit declaration of no monitoring, and a
        # declared Cadence must actually reach the engine: schedule_bridge already builds
        # the agenda, so dropping it here would compute a declaration and discard it.
        monitoring_policy = None
        if "monitoring" in agendas:
            monitoring_policy = MonitoringPolicy(
                agendas["monitoring"].agenda_id, agendas["monitoring"].role
            )
            register_monitoring_policy(self._root, monitoring_policy)

        exchange_ref = exchange_component_ref(
            simulation.exchange, component_id=f"{run_id}-exchange"
        )
        register_component(self._root, exchange_ref)

        return RunDefinition(
            strategy_config,
            valuation_config,
            ConstraintSet(tuple(constraint_refs)),
            monitoring_policy,
            exchange_ref,
            simulation.execution.input.input_id,
            simulation.schedule.start,
            simulation.schedule.end,
            _engine_snapshot(simulation.account.snapshot),
            _engine_mode(simulation.account.mode),
            simulation.initial_strategy_state,
            simulation.instruments,
        )

    def register_all(
        self, declarations: tuple[ProjectDeclaration, ...]
    ) -> tuple[RegistrationReceipt, ...]:
        """Prepare every declaration against ONE candidate catalog and commit once.

        This is the shape preflight needs: validation sees all staged declarations
        together, and a rejection anywhere commits none of them.
        """
        started = time.perf_counter()
        if not isinstance(declarations, tuple) or not declarations:
            raise ValueError("declarations must be a non-empty tuple")
        for item in declarations:
            if not isinstance(item, _KIND_BY_TYPE_TUPLE):
                raise TypeError(f"unsupported declaration {type(item).__name__}")

        snapshot = read_catalog(self._root)
        expected_generation = snapshot.generation
        expected_digest = root_digest(snapshot)

        candidate = snapshot
        for item in declarations:
            _, binding_kind = _KIND_BY_TYPE[type(item)]
            candidate = candidate.with_binding(
                binding_kind, _binding_key(item), item.canonical()
            )

        if candidate == snapshot:
            generation = snapshot.generation
            created = False
        else:
            generation = commit_catalog(
                self._root,
                candidate=candidate,
                expected_generation=expected_generation,
                expected_root_digest=expected_digest,
            ).generation
            created = True

        elapsed = time.perf_counter() - started
        timing = RegistrationTiming(
            schema_seconds=elapsed,
            key_seconds=None,
            conformance_seconds=None,
            preparation_seconds=elapsed,
        )
        return tuple(
            RegistrationReceipt(
                created=created,
                declaration_kind=_KIND_BY_TYPE[type(item)][0],
                authority_id=f"{_KIND_BY_TYPE[type(item)][0]}/v1/{root_digest(candidate)}",
                fingerprint=None,
                catalog_generation=generation,
                timing=timing,
            )
            for item in declarations
        )


_KIND_BY_TYPE_TUPLE = tuple(_KIND_BY_TYPE)


def _engine_snapshot(snapshot):
    """Translate the public AccountSnapshot onto the engine's own class.

    Same three fields, different classes - the public one is keyword-only, the engine's is
    positional. Translating field by field rather than hoping they stay compatible.
    """
    from vqapr.public import AccountSnapshot as EngineSnapshot

    return EngineSnapshot(snapshot.version, snapshot.cash, dict(snapshot.positions))


def _engine_mode(mode):
    """Translate the public AccountMode by value, never by name.

    They share member values today. Matching on name would pass now and break silently the
    moment either side renames a member without changing what it means.
    """
    from vqapr.public import AccountMode as EngineMode

    return EngineMode(mode.value)


def open(root: Path | str) -> Project:
    """Open a project at `root` WITHOUT creating anything.

    Shadowing the builtin is deliberate: the supported call is `vqapr.open(root)`, and the
    plan pins that exact spelling as the only entry point.
    """
    resolved = Path(root)
    if not isinstance(root, (Path, str)):
        raise TypeError("root must be a Path or str")
    return Project(resolved)


def empty_catalog() -> Catalog:
    """The in-memory catalog an unregistered root is equivalent to."""
    return Catalog.empty()
