"""한 project가 명령 사이에 축적하는 선언 집합.

workspace는 선언을 보관하고 조회할 뿐 검증하지 않는다. dataset의 물리 스키마와 logical key가
유효한지는 ``data.datasets.validate``가 판정한 뒤 이 경계로 들어온다.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

import yaml

from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.domain.identifiers import DatasetId, SourceId, dataset_id, source_id

WORKSPACE_DIRECTORY = ".vqapr"
WORKSPACE_FILENAME = "workspace.yaml"
OPEN_STAGE = "workspace.open"
REGISTER_STAGE = "workspace.dataset.register"
LOOKUP_STAGE = "workspace.dataset.lookup"
SOURCE_LOOKUP_STAGE = "workspace.source.lookup"
WRITE_STAGE = "workspace.write"
_CONSTRUCTION_TOKEN = object()


class Workspace:
    """명시적으로 선택한 project root의 등록 선언 모음.

    현재 작업 디렉터리나 process-global provider를 보지 않는다. 호출자가 project root를 전달하고,
    이후 run은 이 mutable workspace를 다시 읽지 않는 frozen input을 별도로 만들어야 한다.
    """

    __slots__ = ("_datasets", "_sources", "project_root")

    def __init__(
        self,
        project_root: str | Path,
        datasets: Mapping[DatasetId, DatasetRegistration] | None = None,
        sources: Mapping[SourceId, SourceSpec] | None = None,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise TypeError("construct a workspace with Workspace.create() or Workspace.open()")
        self.project_root = Path(project_root)
        self._datasets = {
            key: _detach_registration(value) for key, value in (datasets or {}).items()
        }
        self._sources = {key: _detach_source(value) for key, value in (sources or {}).items()}

    @classmethod
    def _from_state(
        cls,
        project_root: str | Path,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
    ) -> Workspace:
        return cls(project_root, datasets, sources, _token=_CONSTRUCTION_TOKEN)

    @property
    def path(self) -> Path:
        return self.project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME

    @classmethod
    def create(cls, project_root: str | Path) -> Workspace:
        """새 project workspace를 만들거나 이미 있으면 그대로 연다."""
        candidate = cls._from_state(project_root, {}, {})
        if candidate.path.exists():
            return cls.open(project_root)
        candidate._write({}, {})
        return candidate

    @classmethod
    def open(cls, project_root: str | Path) -> Workspace:
        """기존 workspace 전체를 읽는다. 없거나 손상됐으면 일부 상태를 반환하지 않는다."""
        candidate = cls._from_state(project_root, {}, {})
        datasets, sources = candidate._read()
        return cls._from_state(project_root, datasets, sources)

    @property
    def datasets(self) -> tuple[DatasetRegistration, ...]:
        """dataset_id 순으로 정렬된 detached 선언들."""
        return tuple(_detach_registration(self._datasets[key]) for key in sorted(self._datasets))

    @property
    def sources(self) -> tuple[SourceSpec, ...]:
        """source_id 순으로 정렬된 detached 물리 선언들."""
        return tuple(_detach_source(self._sources[key]) for key in sorted(self._sources))

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        """등록된 선언 하나를 조회한다."""
        try:
            key = dataset_id(raw_dataset_id)
        except ValueError as error:
            raise _workspace_error(
                stage=LOOKUP_STAGE,
                code=f"{LOOKUP_STAGE}.invalid",
                requirement="dataset lookup requires a valid dataset_id",
                observed=str(error),
                retry="use a valid dataset_id, then retry",
            ) from error
        try:
            return _detach_registration(self._datasets[key])
        except KeyError as error:
            raise _workspace_error(
                stage=LOOKUP_STAGE,
                code=f"{LOOKUP_STAGE}.missing",
                requirement=f"dataset {key!r} must be registered in this workspace",
                observed=f"registered datasets: {', '.join(sorted(self._datasets)) or '(none)'}",
                retry="register the dataset, then retry",
            ) from error

    def source(self, raw_source_id: str) -> SourceSpec:
        """등록된 물리 source 선언 하나를 조회한다."""
        try:
            key = source_id(raw_source_id)
        except ValueError as error:
            raise _workspace_error(
                stage=SOURCE_LOOKUP_STAGE,
                code=f"{SOURCE_LOOKUP_STAGE}.invalid",
                requirement="source lookup requires a valid source_id",
                observed=str(error),
                retry="use a valid source_id, then retry",
            ) from error
        try:
            return _detach_source(self._sources[key])
        except KeyError as error:
            raise _workspace_error(
                stage=SOURCE_LOOKUP_STAGE,
                code=f"{SOURCE_LOOKUP_STAGE}.missing",
                requirement=f"source {key!r} must be registered in this workspace",
                observed=f"registered sources: {', '.join(sorted(self._sources)) or '(none)'}",
                retry="register a dataset with that source, then retry",
            ) from error

    def register_dataset(self, registration: DatasetRegistration, source: SourceSpec) -> bool:
        """물리·의미 선언을 보관한다. 새 dataset이면 True, 동일하면 False다.

        같은 ``dataset_id``가 다른 선언을 뜻하도록 조용히 바꾸지 않는다. replace는 이 slice의
        지원 범위가 아니다.
        """
        if registration.source != source.source_id:
            raise _workspace_error(
                stage=REGISTER_STAGE,
                code=f"{REGISTER_STAGE}.source_mismatch",
                requirement="DatasetRegistration.source must match SourceSpec.source_id",
                observed=(
                    f"registration source={registration.source!r}, source spec={source.source_id!r}"
                ),
                retry="bind the dataset and physical source to the same source_id, then retry",
            )

        datasets, sources = self._read()
        key = registration.dataset_id
        source_key = source.source_id
        existing_source = sources.get(source_key)
        if existing_source is not None and existing_source != source:
            raise _workspace_error(
                stage=REGISTER_STAGE,
                code=f"{REGISTER_STAGE}.source_conflict",
                requirement=f"source_id {source_key!r} must keep its existing physical declaration",
                observed="a different SourceSpec is already registered",
                retry="use the existing source declaration or choose a new source_id",
            )

        existing = datasets.get(key)
        if existing is not None:
            if existing == registration and existing_source == source:
                self._replace_state(datasets, sources)
                return False
            raise _workspace_error(
                stage=REGISTER_STAGE,
                code=f"{REGISTER_STAGE}.conflict",
                requirement=(
                    f"dataset_id {key!r} must keep its existing declaration or use a new identity"
                ),
                observed="a different declaration is already registered",
                retry="use the existing declaration or choose a new dataset_id",
            )

        merged_datasets = dict(datasets)
        merged_sources = dict(sources)
        merged_datasets[key] = _detach_registration(registration)
        merged_sources[source_key] = _detach_source(source)
        self._write(merged_datasets, merged_sources)
        self._replace_state(merged_datasets, merged_sources)
        return True

    def _read(
        self,
    ) -> tuple[dict[DatasetId, DatasetRegistration], dict[SourceId, SourceSpec]]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise _workspace_error(
                stage=OPEN_STAGE,
                code=f"{OPEN_STAGE}.missing",
                requirement=f"workspace must exist at {self.path}",
                observed="path does not exist",
                retry="create the workspace, then retry",
            ) from error
        except OSError as error:
            raise _workspace_error(
                stage=OPEN_STAGE,
                code=f"{OPEN_STAGE}.unreadable",
                requirement=f"workspace must be readable at {self.path}",
                observed=str(error),
                retry="make the workspace readable, then retry",
            ) from error

        try:
            return _decode(text)
        except (TypeError, ValueError, yaml.YAMLError) as error:
            raise _workspace_error(
                stage=OPEN_STAGE,
                code=f"{OPEN_STAGE}.invalid",
                requirement=(
                    "workspace YAML must contain valid physical sources and dataset declarations"
                ),
                observed=str(error),
                retry="fix or recreate the workspace, then retry",
            ) from error

    def _replace_state(
        self,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
    ) -> None:
        self._datasets = {key: _detach_registration(value) for key, value in datasets.items()}
        self._sources = {key: _detach_source(value) for key, value in sources.items()}

    def _write(
        self,
        datasets: Mapping[DatasetId, DatasetRegistration],
        sources: Mapping[SourceId, SourceSpec],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _encode(datasets, sources)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{WORKSPACE_FILENAME}.",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise _workspace_error(
                stage=WRITE_STAGE,
                code=f"{WRITE_STAGE}.failed",
                requirement=f"workspace must be written at {self.path}",
                observed=str(error),
                retry="make the workspace directory writable, then retry",
            ) from error


def _detach_registration(registration: DatasetRegistration) -> DatasetRegistration:
    return DatasetRegistration.of(
        str(registration.dataset_id),
        str(registration.source),
        instrument_field=registration.instrument_field,
        available_at=registration.available_at,
        key_fields=registration.key_fields,
        fields=dict(registration.fields),
    )


def _detach_source(source: SourceSpec) -> SourceSpec:
    return SourceSpec.of(
        str(source.source_id),
        source.path,
        hive_partitioned=source.hive_partitioned,
    )


def _encode(
    datasets: Mapping[DatasetId, DatasetRegistration],
    sources: Mapping[SourceId, SourceSpec],
) -> str:
    document = {
        "sources": {
            str(key): {
                "path": str(source.path),
                "hive_partitioned": source.hive_partitioned,
            }
            for key, source in sorted(sources.items(), key=lambda item: str(item[0]))
        },
        "datasets": {
            str(key): {
                "source": str(registration.source),
                "instrument_field": registration.instrument_field,
                "available_at": registration.available_at,
                "key_fields": list(registration.key_fields),
                "fields": dict(registration.fields),
            }
            for key, registration in sorted(datasets.items(), key=lambda item: str(item[0]))
        },
    }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)


def _decode(
    text: str,
) -> tuple[dict[DatasetId, DatasetRegistration], dict[SourceId, SourceSpec]]:
    document = yaml.safe_load(text)
    if not isinstance(document, dict) or set(document) != {"sources", "datasets"}:
        raise ValueError("workspace root must contain exactly sources and datasets mappings")

    raw_sources = document["sources"]
    if not isinstance(raw_sources, dict):
        raise TypeError("sources must be a mapping")

    decoded_sources: dict[SourceId, SourceSpec] = {}
    expected_source = {"path", "hive_partitioned"}
    for raw_id, raw_source in raw_sources.items():
        if not isinstance(raw_id, str):
            raise TypeError("every source_id must be a string")
        if not isinstance(raw_source, dict) or set(raw_source) != expected_source:
            raise ValueError(f"source {raw_id!r} must contain exactly {sorted(expected_source)}")
        path = raw_source["path"]
        hive_partitioned = raw_source["hive_partitioned"]
        if not isinstance(path, str):
            raise TypeError(f"source {raw_id!r} path must be a string")
        if not isinstance(hive_partitioned, bool):
            raise TypeError(f"source {raw_id!r} hive_partitioned must be a boolean")
        source = SourceSpec.of(raw_id, path, hive_partitioned=hive_partitioned)
        decoded_sources[source.source_id] = source

    raw_datasets = document["datasets"]
    if not isinstance(raw_datasets, dict):
        raise TypeError("datasets must be a mapping")

    decoded: dict[DatasetId, DatasetRegistration] = {}
    expected = {"source", "instrument_field", "available_at", "key_fields", "fields"}
    for raw_id, raw_registration in raw_datasets.items():
        if not isinstance(raw_id, str):
            raise TypeError("every dataset_id must be a string")
        if not isinstance(raw_registration, dict) or set(raw_registration) != expected:
            raise ValueError(f"dataset {raw_id!r} must contain exactly {sorted(expected)}")

        source = raw_registration["source"]
        instrument_field = raw_registration["instrument_field"]
        available_at = raw_registration["available_at"]
        key_fields = raw_registration["key_fields"]
        fields = raw_registration["fields"]
        if not all(isinstance(value, str) for value in (source, instrument_field, available_at)):
            raise TypeError(f"dataset {raw_id!r} scalar declarations must be strings")
        if not isinstance(key_fields, list) or not all(
            isinstance(value, str) for value in key_fields
        ):
            raise TypeError(f"dataset {raw_id!r} key_fields must be a list of strings")
        if not isinstance(fields, dict) or not all(
            isinstance(name, str) and isinstance(column, str) for name, column in fields.items()
        ):
            raise TypeError(f"dataset {raw_id!r} fields must map strings to strings")

        registration = DatasetRegistration.of(
            raw_id,
            source,
            instrument_field=instrument_field,
            available_at=available_at,
            key_fields=key_fields,
            fields=fields,
        )
        if registration.source not in decoded_sources:
            raise ValueError(
                f"dataset {raw_id!r} references unregistered source {registration.source!r}"
            )
        decoded[registration.dataset_id] = registration
    return decoded, decoded_sources


def _workspace_error(
    *,
    stage: str,
    code: str,
    requirement: str,
    observed: str,
    retry: str,
) -> VqaprError:
    return VqaprError(
        stage=stage,
        family=FailureFamily.DATA,
        failures=[Failure.bounded(code, requirement, observed=observed)],
        mutation=False,
        retry_precondition=retry,
    )
