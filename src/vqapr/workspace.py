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
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.domain.identifiers import DatasetId, dataset_id

WORKSPACE_DIRECTORY = ".vqapr"
WORKSPACE_FILENAME = "workspace.yaml"
OPEN_STAGE = "workspace.open"
REGISTER_STAGE = "workspace.dataset.register"
LOOKUP_STAGE = "workspace.dataset.lookup"
WRITE_STAGE = "workspace.write"


class Workspace:
    """명시적으로 선택한 project root의 등록 선언 모음.

    현재 작업 디렉터리나 process-global provider를 보지 않는다. 호출자가 project root를 전달하고,
    이후 run은 이 mutable workspace를 다시 읽지 않는 frozen input을 별도로 만들어야 한다.
    """

    __slots__ = ("_datasets", "project_root")

    def __init__(
        self,
        project_root: str | Path,
        datasets: Mapping[DatasetId, DatasetRegistration],
    ) -> None:
        self.project_root = Path(project_root)
        self._datasets = {key: _detach(value) for key, value in datasets.items()}

    @property
    def path(self) -> Path:
        return self.project_root / WORKSPACE_DIRECTORY / WORKSPACE_FILENAME

    @classmethod
    def create(cls, project_root: str | Path) -> Workspace:
        """새 project workspace를 만들거나 이미 있으면 그대로 연다."""
        candidate = cls(project_root, {})
        if candidate.path.exists():
            return cls.open(project_root)
        candidate._write()
        return candidate

    @classmethod
    def open(cls, project_root: str | Path) -> Workspace:
        """기존 workspace 전체를 읽는다. 없거나 손상됐으면 일부 상태를 반환하지 않는다."""
        candidate = cls(project_root, {})
        try:
            text = candidate.path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise _workspace_error(
                stage=OPEN_STAGE,
                code=f"{OPEN_STAGE}.missing",
                requirement=f"workspace must exist at {candidate.path}",
                observed="path does not exist",
                retry="create the workspace, then retry",
            ) from error
        except OSError as error:
            raise _workspace_error(
                stage=OPEN_STAGE,
                code=f"{OPEN_STAGE}.unreadable",
                requirement=f"workspace must be readable at {candidate.path}",
                observed=str(error),
                retry="make the workspace readable, then retry",
            ) from error

        try:
            datasets = _decode(text)
        except (TypeError, ValueError, yaml.YAMLError) as error:
            raise _workspace_error(
                stage=OPEN_STAGE,
                code=f"{OPEN_STAGE}.invalid",
                requirement="workspace YAML must contain valid registered dataset declarations",
                observed=str(error),
                retry="fix or recreate the workspace, then retry",
            ) from error
        return cls(project_root, datasets)

    @property
    def datasets(self) -> tuple[DatasetRegistration, ...]:
        """dataset_id 순으로 정렬된 detached 선언들."""
        return tuple(_detach(self._datasets[key]) for key in sorted(self._datasets))

    def dataset(self, raw_dataset_id: str) -> DatasetRegistration:
        """등록된 선언 하나를 조회한다."""
        key = dataset_id(raw_dataset_id)
        try:
            return _detach(self._datasets[key])
        except KeyError as error:
            raise _workspace_error(
                stage=LOOKUP_STAGE,
                code=f"{LOOKUP_STAGE}.missing",
                requirement=f"dataset {key!r} must be registered in this workspace",
                observed=f"registered datasets: {', '.join(sorted(self._datasets)) or '(none)'}",
                retry="register the dataset, then retry",
            ) from error

    def register_dataset(self, registration: DatasetRegistration) -> bool:
        """선언을 보관한다. 새 선언이면 True, 동일한 재등록이면 False다.

        같은 ``dataset_id``가 다른 선언을 뜻하도록 조용히 바꾸지 않는다. replace는 이 slice의
        지원 범위가 아니다.
        """
        key = registration.dataset_id
        existing = self._datasets.get(key)
        if existing is not None:
            if existing == registration:
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

        self._datasets[key] = _detach(registration)
        try:
            self._write()
        except VqaprError:
            del self._datasets[key]
            raise
        return True

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _encode(self._datasets)
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


def _detach(registration: DatasetRegistration) -> DatasetRegistration:
    return DatasetRegistration.of(
        str(registration.dataset_id),
        str(registration.source),
        instrument_field=registration.instrument_field,
        available_at=registration.available_at,
        key_fields=registration.key_fields,
        fields=dict(registration.fields),
    )


def _encode(datasets: Mapping[DatasetId, DatasetRegistration]) -> str:
    document = {
        "datasets": {
            str(key): {
                "source": str(registration.source),
                "instrument_field": registration.instrument_field,
                "available_at": registration.available_at,
                "key_fields": list(registration.key_fields),
                "fields": dict(registration.fields),
            }
            for key, registration in sorted(datasets.items(), key=lambda item: str(item[0]))
        }
    }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)


def _decode(text: str) -> dict[DatasetId, DatasetRegistration]:
    document = yaml.safe_load(text)
    if not isinstance(document, dict) or set(document) != {"datasets"}:
        raise ValueError("workspace root must contain exactly a datasets mapping")
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
        decoded[registration.dataset_id] = registration
    return decoded


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
