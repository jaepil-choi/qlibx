"""pydantic finds what is wrong with a declaration; the package says it in its own envelope.

Deletion campaign Step 4 (record `145`) hands key sets, types, enums and timestamps to pydantic.
What it does not hand over is the refusal: an agent reads `code`, `status`, `fix` and `source`
(`docs/vqapr-architecture.md` §10), never a pydantic message. `declarations.refusals_from` is the
one place a `ValidationError` becomes a `Diagnosis`, and these are its properties:

- every error of one declaration arrives in one refusal (a missing key beside a wrong type),
  which is what `_require_keys` promised before -- one round trip, not one per key;
- a missing key, an unknown key, a value outside a closed set and a value of the wrong shape
  each get their own code, and the unknown key and the closed set get the nearest-name hint;
- `source.key_path` is the dotted path into the declaration, prefixed with the section and id;
- nothing pydantic wrote appears where an author reads.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from vqapr.declarations import refusals_from
from vqapr.domain.errors import Stage, Status, VqaprError


class Role(StrEnum):
    STRATEGY_CALLBACK = "strategy_callback"
    VALUATION = "valuation"


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    at: time


class Doc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    role: Role
    when: datetime
    inner: Inner
    fields: dict[str, str]


def _errors(payload: dict) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        Doc.model_validate(payload)
    return caught.value


def _refusal(payload: dict) -> VqaprError:
    with pytest.raises(VqaprError) as caught:
        refusals_from(_errors(payload), model=Doc, name="agendas.daily").raise_if_failed()
    return caught.value


def test_every_error_of_one_declaration_arrives_in_one_refusal() -> None:
    refused = _refusal({"rol": "valuation", "when": "nope", "inner": {"at": "15:30"}, "fields": {}})
    assert refused.stage is Stage.REGISTER
    codes = sorted(failure.code for failure in refused.failures)
    assert codes == [
        "declaration.key_missing",
        "declaration.key_missing",
        "declaration.key_unknown",
        "declaration.value_invalid",
    ]
    for failure in refused.failures:
        assert failure.fix and failure.status is Status.INVALID
        assert failure.source.key_path.startswith("agendas.daily")
        # The `ValidationError` rides whole on every entry it produced (record `171`).
        assert failure.cause is not None
        assert failure.cause.type == "ValidationError"
        assert failure.cause.traceback and "ValidationError" in failure.cause.traceback


def test_a_missing_key_names_the_key_and_what_the_declaration_has() -> None:
    (failure,) = [
        f for f in _refusal({"role": "valuation", "when": "2024-01-02T00:00:00+09:00",
                             "inner": {"at": "15:30"}, "fields": {}}).failures
    ]
    assert failure.code == "declaration.key_missing"
    assert failure.requirement == "agendas.daily must declare source_id"
    assert failure.observed == "agendas.daily declares: fields, inner, role, when"
    assert failure.fix == "add source_id under agendas.daily in the declaration YAML"
    assert failure.source.key_path == "agendas.daily"


def test_an_unknown_key_gets_the_nearest_permitted_name() -> None:
    failures = _refusal({"source_id": "s", "rol": "valuation", "when": "2024-01-02T00:00:00+09:00",
                         "inner": {"at": "15:30"}, "fields": {}}).failures
    unknown = [f for f in failures if f.code.endswith("key_unknown")]
    assert len(unknown) == 1
    assert "role" in unknown[0].fix and "'rol'" in unknown[0].fix
    assert unknown[0].source.key_path == "agendas.daily.rol"


def test_a_value_outside_a_closed_set_names_the_set_and_the_nearest_member() -> None:
    (failure,) = _refusal({"source_id": "s", "role": "valuaton",
                           "when": "2024-01-02T00:00:00+09:00", "inner": {"at": "15:30"},
                           "fields": {}}).failures
    assert failure.code == "declaration.value_not_permitted"
    assert "strategy_callback, valuation" in failure.requirement
    assert "'valuation'" in failure.fix
    assert failure.source.key_path == "agendas.daily.role"


def test_a_wrong_shape_is_value_invalid_at_its_own_path() -> None:
    (failure,) = _refusal({"source_id": "s", "role": "valuation",
                           "when": "2024-01-02T00:00:00+09:00", "inner": {"at": "15:30"},
                           "fields": {"a": 1}}).failures
    assert failure.code == "declaration.value_invalid"
    assert failure.source.key_path == "agendas.daily.fields.a"
    assert "string" in failure.requirement


def test_nothing_pydantic_wrote_reaches_the_author() -> None:
    refused = _refusal({"rol": "valuation", "when": "nope", "inner": {"at": "15:30", "x": 1},
                        "fields": {"a": 1}})
    # The fields an author reads. `cause` deliberately carries the `ValidationError` verbatim,
    # traceback and all (record `171`): that is evidence for the reader who suspects the
    # classification, not the sentence the reader acts on.
    for entry in refused.as_dict()["failures"]:
        text = repr({key: entry[key] for key in ("requirement", "observed", "fix", "examples")})
        assert "Extra inputs are not permitted" not in text
        assert "Field required" not in text
        assert "ValidationError" not in text
