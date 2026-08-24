"""`vqapr._internal.extensions.identity` — the `v1` fingerprint and canonical config schemas.

This is pure internal identity plumbing: it does not touch registration, loading, or any current
public behavior. Every assertion is about the byte preimage, the canonical config encoding, and
the stable-source/drift boundary the T2 candidate-catalog and callback-drift work will build on.
"""

from __future__ import annotations

import importlib
import struct
import sys
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr._internal.extensions.identity import (
    ExtensionIdentity,
    ExtensionKind,
    authority_id,
    canonical_config_bytes,
    compute_fingerprint,
    identify,
    installed_package_version,
    stable_source_bytes,
    verify_no_drift,
)

_MODULE_SOURCE = '''\
class {name}:
    """A minimal top-level class for identity fixtures."""

    def __init__(self, value: int = 0) -> None:
        self.value = value
'''


def _write_module(tmp_path: Path, module_name: str, class_name: str = "Sample") -> type:
    """Write a temp importable top-level module and return its class, imported for real.

    `stable_source_bytes` requires an importable module backed by a file, so fixtures import
    through `sys.path`/`importlib`, not `spec_from_file_location` against an unregistered name —
    the identity codec must work for the same shape of import Python actually performs.
    """
    package_dir = tmp_path / f"_pkg_{module_name}"
    package_dir.mkdir(exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / f"{module_name}.py").write_text(
        _MODULE_SOURCE.format(name=class_name), encoding="utf-8"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module(f"_pkg_{module_name}.{module_name}")
    finally:
        sys.path.remove(str(tmp_path))
    return getattr(module, class_name)


@pytest.fixture(autouse=True)
def _clean_imported_modules():
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.startswith("_pkg_"):
            del sys.modules[name]


# --------------------------------------------------------------------------------------
# vqapr.config/v1 canonical encoding
# --------------------------------------------------------------------------------------


def test_canonical_config_sorts_keys_by_utf8_byte_order() -> None:
    forward = canonical_config_bytes({"b": 1, "a": 2, "c": 3})
    reordered = canonical_config_bytes({"c": 3, "a": 2, "b": 1})
    assert forward == reordered
    assert forward.index(b'"a"') < forward.index(b'"b"') < forward.index(b'"c"')


def test_canonical_config_distinguishes_list_and_tuple() -> None:
    as_list = canonical_config_bytes({"x": [1, 2]})
    as_tuple = canonical_config_bytes({"x": (1, 2)})
    assert as_list != as_tuple


def test_canonical_config_type_tags_prevent_collisions() -> None:
    """`1`, `True`, `"1"`, and `Decimal("1")` must never encode identically."""
    encodings = {
        canonical_config_bytes({"v": 1}),
        canonical_config_bytes({"v": True}),
        canonical_config_bytes({"v": "1"}),
        canonical_config_bytes({"v": Decimal("1")}),
    }
    assert len(encodings) == 4


def test_canonical_config_accepts_the_full_scalar_and_collection_set() -> None:
    aware = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    encoded = canonical_config_bytes(
        {
            "none": None,
            "flag": False,
            "count": -7,
            "coeff": Decimal("12.340"),
            "label": "korea",
            "day": date(2024, 1, 2),
            "moment": time(9, 30),
            "stamp": aware,
            "nested_map": {"inner": 1},
            "items_list": [1, "two", None],
            "items_tuple": (1, 2),
        }
    )
    assert isinstance(encoded, bytes)
    # Round-trips deterministically.
    assert encoded == canonical_config_bytes(
        {
            "stamp": aware,
            "items_tuple": (1, 2),
            "items_list": [1, "two", None],
            "nested_map": {"inner": 1},
            "moment": time(9, 30),
            "day": date(2024, 1, 2),
            "label": "korea",
            "coeff": Decimal("12.340"),
            "count": -7,
            "flag": False,
            "none": None,
        }
    )


def test_canonical_config_none_and_empty_mapping_encode_the_same() -> None:
    assert canonical_config_bytes(None) == canonical_config_bytes({})


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (1.5, "float"),
        (Path("x"), "Path"),
        (lambda: None, "callable"),
        ({1, 2}, "set"),
        (frozenset({1}), "set"),
        (b"raw", "bytes"),
        (Decimal("NaN"), "finite"),
        (Decimal("Infinity"), "finite"),
        (datetime(2024, 1, 1), "timezone-aware"),
    ],
)
def test_canonical_config_rejects_disallowed_values(value: object, match: str) -> None:
    with pytest.raises((TypeError, ValueError), match=match):
        canonical_config_bytes({"bad": value})


def test_canonical_config_rejects_non_string_keys() -> None:
    with pytest.raises(TypeError):
        canonical_config_bytes({1: "a"})  # type: ignore[dict-item]


def test_canonical_config_rejects_arbitrary_objects() -> None:
    class Unsupported:
        pass

    with pytest.raises(TypeError):
        canonical_config_bytes({"x": Unsupported()})


def test_canonical_config_rejects_non_mapping_input() -> None:
    with pytest.raises(TypeError):
        canonical_config_bytes([1, 2])  # type: ignore[arg-type]


def test_canonical_config_nested_collections_reject_float_deep_inside() -> None:
    with pytest.raises(TypeError, match="float"):
        canonical_config_bytes({"outer": {"inner": [1, 2.5]}})


# --------------------------------------------------------------------------------------
# stable source loading
# --------------------------------------------------------------------------------------


def test_stable_source_bytes_reads_the_full_module_file(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "mod_a")
    source = stable_source_bytes(cls)
    on_disk = (tmp_path / "_pkg_mod_a" / "mod_a.py").read_bytes()
    assert source == on_disk


def test_stable_source_bytes_rejects_a_locally_defined_class() -> None:
    def factory() -> type:
        class Local:
            pass

        return Local

    with pytest.raises(ValueError, match="function or method"):
        stable_source_bytes(factory())


def test_stable_source_bytes_rejects_a_nested_class(tmp_path: Path) -> None:
    package_dir = tmp_path / "_pkg_nested"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "nested.py").write_text(
        "class Outer:\n    class Inner:\n        pass\n", encoding="utf-8"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module("_pkg_nested.nested")
    finally:
        sys.path.remove(str(tmp_path))
    with pytest.raises(ValueError, match="nested"):
        stable_source_bytes(module.Outer.Inner)


def test_stable_source_bytes_rejects_a_repl_defined_class() -> None:
    """A class built via `exec` in a synthetic module has no readable defining file."""
    namespace: dict[str, object] = {"__name__": "__not_a_real_module__"}
    exec("class Dynamic:\n    pass\n", namespace)
    with pytest.raises(ValueError):
        stable_source_bytes(namespace["Dynamic"])  # type: ignore[arg-type]


def test_stable_source_bytes_rejects_a_module_with_no_source_file() -> None:
    with pytest.raises(ValueError):
        stable_source_bytes(int)


# --------------------------------------------------------------------------------------
# vqapr-extension-fingerprint/v1
# --------------------------------------------------------------------------------------


def test_compute_fingerprint_matches_the_length_delimited_preimage() -> None:
    import hashlib

    module_bytes = b"class X:\n    pass\n"
    qualname = "X"
    config = {"alpha": 1}
    version = "9.9.9"
    fingerprint = compute_fingerprint(
        kind=ExtensionKind.DATA_MODEL,
        module_bytes=module_bytes,
        qualname=qualname,
        config=config,
        package_version=version,
    )

    def field(data: bytes) -> bytes:
        return struct.pack(">Q", len(data)) + data

    expected_preimage = (
        field(b"data_model")
        + field(version.encode("utf-8"))
        + field(module_bytes)
        + field(qualname.encode("utf-8"))
        + field(canonical_config_bytes(config))
    )
    assert fingerprint == hashlib.sha256(expected_preimage).hexdigest()
    assert len(fingerprint) == 64
    assert fingerprint == fingerprint.lower()


def test_identify_is_independent_of_module_name_and_path(tmp_path: Path) -> None:
    """Same source content, same qualname, same config, different file path/module name."""
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()

    def make(base: Path, module_name: str) -> type:
        package = base / f"_pkg_{module_name}"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / f"{module_name}.py").write_text(
            _MODULE_SOURCE.format(name="Sample"), encoding="utf-8"
        )
        sys.path.insert(0, str(base))
        try:
            module = importlib.import_module(f"_pkg_{module_name}.{module_name}")
        finally:
            sys.path.remove(str(base))
        return module.Sample

    cls_a = make(left_dir, "identical_alpha")
    cls_b = make(right_dir, "identical_beta")

    identity_a = identify(cls_a, kind=ExtensionKind.STRATEGY_MODEL, config={"k": 1})
    identity_b = identify(cls_b, kind=ExtensionKind.STRATEGY_MODEL, config={"k": 1})

    assert identity_a.fingerprint == identity_b.fingerprint
    assert identity_a.authority_id == identity_b.authority_id
    assert str(cls_a.__module__) != str(cls_b.__module__)


def test_identify_is_independent_of_config_key_order(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "order_mod")
    forward = identify(cls, kind=ExtensionKind.CONSTRAINT, config={"a": 1, "b": 2, "c": 3})
    reordered = identify(cls, kind=ExtensionKind.CONSTRAINT, config={"c": 3, "b": 2, "a": 1})
    assert forward.fingerprint == reordered.fingerprint


def test_authority_id_is_opaque_and_excludes_human_name() -> None:
    fingerprint = "a" * 64
    identity_id = authority_id(ExtensionKind.DATA_MODEL, fingerprint)
    assert identity_id == f"extension/v1/data_model/{fingerprint}"
    assert "Sample" not in identity_id


def test_authority_id_rejects_a_non_full_digest() -> None:
    with pytest.raises(ValueError):
        authority_id(ExtensionKind.DATA_MODEL, "abc")
    with pytest.raises(ValueError):
        authority_id(ExtensionKind.DATA_MODEL, "A" * 64)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (ExtensionKind.DATA_MODEL, ExtensionKind.STRATEGY_MODEL),
        (ExtensionKind.STRATEGY_MODEL, ExtensionKind.CONSTRAINT),
        (ExtensionKind.CONSTRAINT, ExtensionKind.DATA_MODEL),
    ],
)
def test_same_source_different_kind_yields_different_fingerprint(
    tmp_path: Path, first: ExtensionKind, second: ExtensionKind
) -> None:
    cls = _write_module(tmp_path, "kind_collision_mod")
    identity_first = identify(cls, kind=first, config={})
    identity_second = identify(cls, kind=second, config={})
    assert identity_first.fingerprint != identity_second.fingerprint


def test_source_drift_changes_the_fingerprint(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "drift_source_mod")
    original = identify(cls, kind=ExtensionKind.DATA_MODEL, config={})

    module_path = tmp_path / "_pkg_drift_source_mod" / "drift_source_mod.py"
    module_path.write_text(
        _MODULE_SOURCE.format(name="Sample").replace("value: int = 0", "value: int = 1"),
        encoding="utf-8",
    )
    drifted = identify(cls, kind=ExtensionKind.DATA_MODEL, config={})
    assert drifted.fingerprint != original.fingerprint


def test_config_drift_changes_the_fingerprint(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "drift_config_mod")
    original = identify(cls, kind=ExtensionKind.CONSTRAINT, config={"threshold": Decimal("1.0")})
    drifted = identify(cls, kind=ExtensionKind.CONSTRAINT, config={"threshold": Decimal("2.0")})
    assert original.fingerprint != drifted.fingerprint


def test_package_version_drift_changes_the_fingerprint(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "drift_version_mod")
    module_bytes = stable_source_bytes(cls)
    old_version = compute_fingerprint(
        kind=ExtensionKind.STRATEGY_MODEL,
        module_bytes=module_bytes,
        qualname=cls.__qualname__,
        config={},
        package_version="0.1.0",
    )
    new_version = compute_fingerprint(
        kind=ExtensionKind.STRATEGY_MODEL,
        module_bytes=module_bytes,
        qualname=cls.__qualname__,
        config={},
        package_version="0.2.0",
    )
    assert old_version != new_version


def test_installed_package_version_matches_the_default_used_by_identify(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "version_default_mod")
    identity = identify(cls, kind=ExtensionKind.DATA_MODEL, config={})
    explicit = compute_fingerprint(
        kind=ExtensionKind.DATA_MODEL,
        module_bytes=stable_source_bytes(cls),
        qualname=cls.__qualname__,
        config={},
        package_version=installed_package_version(),
    )
    assert identity.fingerprint == explicit


def test_verify_no_drift_passes_when_nothing_moved(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "stable_mod")
    identity = identify(cls, kind=ExtensionKind.STRATEGY_MODEL, config={"x": 1})
    verify_no_drift(cls, identity, config={"x": 1})


def test_verify_no_drift_raises_on_source_edit_after_capture(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "predrift_source_mod")
    identity = identify(cls, kind=ExtensionKind.STRATEGY_MODEL, config={})

    module_path = tmp_path / "_pkg_predrift_source_mod" / "predrift_source_mod.py"
    module_path.write_text(
        _MODULE_SOURCE.format(name="Sample").replace("value: int = 0", "value: int = 99"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="drift"):
        verify_no_drift(cls, identity, config={})


def test_verify_no_drift_raises_on_config_change_after_capture(tmp_path: Path) -> None:
    cls = _write_module(tmp_path, "predrift_config_mod")
    identity = identify(cls, kind=ExtensionKind.CONSTRAINT, config={"limit": 1})
    with pytest.raises(ValueError, match="drift"):
        verify_no_drift(cls, identity, config={"limit": 2})


def test_extension_identity_is_frozen_slotted_and_keyword_only() -> None:
    identity = ExtensionIdentity(
        kind=ExtensionKind.DATA_MODEL, fingerprint="a" * 64, authority_id="x"
    )
    with pytest.raises(AttributeError):
        identity.fingerprint = "b" * 64  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        identity.new_attr = 1  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        ExtensionIdentity(ExtensionKind.DATA_MODEL, "a" * 64, "x")  # type: ignore[misc]


# --------------------------------------------------------------------------------------
# failure boundaries on the fingerprint entry points themselves
# --------------------------------------------------------------------------------------


def test_compute_fingerprint_rejects_wrong_kind_type() -> None:
    with pytest.raises(TypeError):
        compute_fingerprint(
            kind="data_model",  # type: ignore[arg-type]
            module_bytes=b"x",
            qualname="X",
        )


def test_compute_fingerprint_rejects_empty_qualname() -> None:
    with pytest.raises(ValueError):
        compute_fingerprint(kind=ExtensionKind.DATA_MODEL, module_bytes=b"x", qualname="   ")


def test_identify_rejects_non_class_target() -> None:
    with pytest.raises(TypeError):
        identify(object(), kind=ExtensionKind.DATA_MODEL)  # type: ignore[arg-type]
