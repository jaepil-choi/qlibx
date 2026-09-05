"""`docs/issues/079`. A datamodel returning `Decimal` died eight sessions in, and the refusal
said `type_drift`: "return the same scalar type for each field on every session". The type was
`Decimal` in every session. What moved was its scale -- pyarrow inferred `decimal128(28, 27)`
from one session's ratios and the next session's needed 28 -- and the one accurate sentence in
the envelope was pyarrow's own, wrapped under a diagnosis that contradicted it.

Owner ruling, 2026-09-05: the data and its types are the author's. The framework declares no
schema, casts nothing, and asserts no cause it did not measure.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from vqapr.domain.errors import VqaprError
from vqapr.flow.datamodel import DataModelOutput


def _output(root: Path) -> DataModelOutput:
    # `DataModelOutput` reads `dataset_id` and `value_fields` off its layer and nothing else.
    return DataModelOutput(root, SimpleNamespace(dataset_id="ratios", value_fields=("ratio",)))


def test_the_refusal_quotes_pyarrow_and_the_established_schema_and_guesses_no_further(
    tmp_path: Path,
) -> None:
    output = _output(tmp_path)
    output.open()
    output.append([{"instrument": "A", "ratio": Decimal(402192) / Decimal(391688)}])

    with pytest.raises(VqaprError) as refused:
        output.append([{"instrument": "A", "ratio": Decimal(1) / Decimal(3)}])

    (failure,) = refused.value.as_dict()["failures"]
    assert failure["code"] == "datamodel.output.schema_mismatch"
    assert "ArrowInvalid" in failure["observed"], "pyarrow's own sentence, unwrapped"
    assert "ratio: decimal128(28, 27)" in failure["observed"], "what the first session fixed"
    assert "same scalar type" not in failure["fix"], (
        "the cause it used to assert, and never measured"
    )
    assert "return float" in failure["fix"]
    assert "quantize" in failure["fix"]


def test_the_first_session_is_still_refused_as_invalid_rows(tmp_path: Path) -> None:
    output = _output(tmp_path)
    output.open()

    with pytest.raises(VqaprError) as refused:
        output.append([{"instrument": "A", "ratio": object()}])

    assert refused.value.as_dict()["failures"][0]["code"] == "datamodel.output.rows_invalid"
