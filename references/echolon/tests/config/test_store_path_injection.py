"""Guards on the store-path seam: echolon must be told where the store is.

Three things are pinned here, each with a seeded failure and a passing control
so that none of these probes can quietly stop being able to fail:

1. ``PortfolioDeployConfig`` carries no artifact-store path at all.
2. The falsifier resolver skips when nothing is injected, and FAILS when
   something is injected but wrong — the case that let eight falsifiers sit
   dark against a store root one directory too high.
3. The store-reading build scripts refuse to run without an explicit root.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import inspect
import json
from pathlib import Path

import pytest

from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig
from tests.conftest import STORE_ROOT_ENV, StoreArtifact, resolve_store_artifact

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"

#: Substrings that would mean echolon had re-learned a store location. The store
#: name is deliberately included: the point of the seam is that renaming the
#: store never requires an echolon edit.
_STORE_PATH_MARKERS = ("output_bank", "dolphinquant_store", "../output")


# --------------------------------------------------------------------------- #
# 1. The deploy config carries no store path.
# --------------------------------------------------------------------------- #
def test_portfolio_deploy_config_declares_no_store_path() -> None:
    """No field of the deploy config is an artifact-store location."""
    fields = {f.name: f for f in dataclasses.fields(PortfolioDeployConfig)}

    assert "output_bank_dir" not in fields

    for name, spec in fields.items():
        default = spec.default if spec.default is not dataclasses.MISSING else None
        assert not isinstance(default, (str, Path)) or not any(
            marker in str(default) for marker in _STORE_PATH_MARKERS
        ), f"field {name} defaults to a store path: {default!r}"


def test_store_path_marker_probe_can_actually_fail() -> None:
    """Control for the scan above: the same check flags a seeded store default.

    Without this, ``test_portfolio_deploy_config_declares_no_store_path`` would
    still pass if the marker list were emptied or the field types changed.
    """

    @dataclasses.dataclass
    class Seeded:
        output_bank_dir: str = "../output_bank"

    seeded = {f.name: f for f in dataclasses.fields(Seeded)}
    offenders = [
        name
        for name, spec in seeded.items()
        if any(marker in str(spec.default) for marker in _STORE_PATH_MARKERS)
    ]
    assert offenders == ["output_bank_dir"]


def test_loading_a_config_that_still_carries_the_legacy_key_ignores_it(
    tmp_path: Path,
) -> None:
    """A host app's own ``output_bank_dir`` key parses without becoming echolon state.

    Real deploy JSONs still carry the key for the host application that owns it.
    Echolon must neither choke on it nor absorb it.
    """
    config_file = tmp_path / "portfolio_deploy_config.json"
    config_file.write_text(
        json.dumps(
            {
                "output_bank_dir": "../output_bank",
                "slots": [],
                # `max_total_capital` lost its default on 2026-07-27 (it was a real
                # account figure sitting in a public repo, and a default on a risk cap is
                # a misleading fallback). Every deploy config must now state it, so this
                # fixture states it too — with an obviously synthetic number.
                "deploy": {"max_total_capital": 1000.0},
            }
        ),
        encoding="utf-8",
    )

    config = PortfolioDeployConfig.load(str(config_file))

    assert not hasattr(config, "output_bank_dir")
    assert config.deploy.max_total_capital == 1000.0


def test_a_deploy_config_without_a_capital_limit_fails_loudly(tmp_path: Path) -> None:
    """The falsifier for removing the default.

    Before 2026-07-27 this config loaded silently and inherited a real account figure
    baked into the library. A deployment that forgot its capital cap would have run
    against a limit nobody chose, and `portfolio_metrics` would have compared total margin
    against that number and reported no breach. Failing at construction is the whole point
    of removing the default, so it is asserted rather than assumed.
    """
    config_file = tmp_path / "portfolio_deploy_config.json"
    config_file.write_text(json.dumps({"slots": [], "deploy": {}}), encoding="utf-8")

    with pytest.raises(TypeError, match="max_total_capital"):
        PortfolioDeployConfig.load(str(config_file))


def test_the_public_repo_carries_no_real_capital_figure() -> None:
    """No account-sized default may reappear in this module.

    A number is easy to put back in a hurry, and a public repository is exactly where it
    must not be. This reads the source rather than the class, so a default restored in any
    form — literal, constant, or factory — trips it.
    """
    source = Path(inspect.getfile(PortfolioDeployConfig)).read_text(encoding="utf-8")
    declaration = next(
        line for line in source.splitlines() if line.strip().startswith("max_total_capital:")
    )
    assert "=" not in declaration, f"max_total_capital has a default again: {declaration!r}"


# --------------------------------------------------------------------------- #
# 2. The falsifier resolver: skip when uninjected, fail when injected wrongly.
# --------------------------------------------------------------------------- #
_PROBE = StoreArtifact(env_var="ECHOLON_TEST_PROBE_ARTIFACT", store_relative="probe/leaf")


def test_resolver_skips_when_nothing_is_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_PROBE.env_var, raising=False)
    monkeypatch.delenv(STORE_ROOT_ENV, raising=False)

    with pytest.raises(pytest.skip.Exception) as excinfo:
        resolve_store_artifact(_PROBE)

    assert STORE_ROOT_ENV in str(excinfo.value)
    assert _PROBE.env_var in str(excinfo.value)


def test_resolver_fails_loudly_when_an_injected_root_is_wrong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The seeded failure: a root that exists but does not hold the artifact.

    This is the exact shape of the defect this seam was built to stop — a store
    root pointing one level away from the real store. It must FAIL, not skip.
    """
    monkeypatch.delenv(_PROBE.env_var, raising=False)
    monkeypatch.setenv(STORE_ROOT_ENV, str(tmp_path))

    with pytest.raises(pytest.fail.Exception) as excinfo:
        resolve_store_artifact(_PROBE)

    assert "does not exist" in str(excinfo.value)
    assert STORE_ROOT_ENV in str(excinfo.value)


def test_resolver_fails_loudly_when_an_injected_artifact_path_is_wrong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(_PROBE.env_var, str(tmp_path / "absent"))

    with pytest.raises(pytest.fail.Exception) as excinfo:
        resolve_store_artifact(_PROBE)

    assert _PROBE.env_var in str(excinfo.value)


def test_resolver_returns_the_path_when_injection_is_correct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Passing control: the resolver is capable of succeeding.

    Without this, the two failure tests above would still pass if the resolver
    were broken into failing unconditionally.
    """
    monkeypatch.delenv(_PROBE.env_var, raising=False)
    monkeypatch.setenv(STORE_ROOT_ENV, str(tmp_path))
    leaf = tmp_path / _PROBE.store_relative
    leaf.parent.mkdir(parents=True)
    leaf.write_text("present", encoding="utf-8")

    assert resolve_store_artifact(_PROBE) == leaf


def test_artifact_specific_variable_wins_over_the_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    direct = tmp_path / "elsewhere.json"
    direct.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(STORE_ROOT_ENV, str(tmp_path / "unused-root"))
    monkeypatch.setenv(_PROBE.env_var, str(direct))

    assert resolve_store_artifact(_PROBE) == direct


# --------------------------------------------------------------------------- #
# 3. Build scripts refuse to guess a store root.
# --------------------------------------------------------------------------- #
def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SCRIPT_STORE_ARGUMENTS = (
    ("build_gfex_expiry_data", "--bars-root"),
    ("build_czce_new_products_expiry_data", "--panel-contracts-root"),
)


@pytest.mark.parametrize(("script_name", "flag"), _SCRIPT_STORE_ARGUMENTS)
def test_build_script_requires_its_store_path(
    script_name: str,
    flag: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Seeded failure: omitting the store path is an argparse error.

    Before this, both scripts defaulted the path to a guessed store location and
    ran silently against it.
    """
    module = _load_script(script_name)
    monkeypatch.setattr("sys.argv", [f"{script_name}.py"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 2
    assert flag in capsys.readouterr().err


@pytest.mark.parametrize(("script_name", "flag"), _SCRIPT_STORE_ARGUMENTS)
def test_build_script_parser_is_otherwise_healthy(
    script_name: str,
    flag: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Passing control for the test above.

    Proves the exit-2 comes from the missing argument rather than from a parser
    that fails no matter what — ``--help`` still exits 0 and documents the flag.
    """
    module = _load_script(script_name)
    monkeypatch.setattr("sys.argv", [f"{script_name}.py", "--help"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 0
    assert flag in capsys.readouterr().out


@pytest.mark.parametrize(("script_name", "_flag"), _SCRIPT_STORE_ARGUMENTS)
def test_build_script_source_names_no_store(script_name: str, _flag: str) -> None:
    """No store name survives in the scripts' source."""
    source = (_SCRIPTS / f"{script_name}.py").read_text(encoding="utf-8")
    for marker in _STORE_PATH_MARKERS:
        assert marker not in source, f"{script_name} still names {marker!r}"


# --- what a green CI run is actually asserting -----------------------------------------


#: Every store artifact the suite can depend on. Pinned so the set cannot shrink by
#: accident: an artifact deleted here without its falsifiers going too, or a new one added
#: without being recorded, fails `test_the_store_artifact_set_is_pinned`.
#:
#: WHY PIN A SET OF SKIPS AT ALL. In a public checkout there is no store, so every one of
#: these resolves to SKIP — correctly. The risk is not that they skip; it is that a green
#: CI run reads as though they passed. Nine of these once skipped against a guessed path
#: one directory above the real store, and the wrong root stayed invisible for as long as
#: it stood, because a skip is indistinguishable from a pass in a suite total. The CI job
#: now runs with `-ra` so the reasons print, and this test makes the set itself load-bearing.
EXPECTED_STORE_ARTIFACTS = {
    "DOLPHINQUANT_P2_V4_PANEL",
    "DOLPHINQUANT_P2_V5_CONTRACTS",
    "DOLPHINQUANT_GFEX_BARS",
    "DCE_COMMISSION_AUTHORITY_V2",
    "COMMISSION_AUTHORITY_V3",
}


def _declared_artifacts() -> dict[str, object]:
    """Every `StoreArtifact` the conftest declares, found on the module, not restated."""
    import tests.conftest as conftest_module

    return {
        value.env_var: value
        for value in vars(conftest_module).values()
        if isinstance(value, StoreArtifact)
    }


def test_the_store_artifact_set_is_pinned() -> None:
    """Derived from the conftest itself, so this cannot drift out of agreement with it."""
    assert set(_declared_artifacts()) == EXPECTED_STORE_ARTIFACTS


def test_every_declared_artifact_skips_rather_than_passes_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property a public CI run depends on, asserted for EVERY artifact.

    Skipping is the right behaviour with no store. What must never happen is an artifact
    resolving to something — a guessed path, a stale default — that lets a falsifier run
    against the wrong bytes and report green.
    """
    monkeypatch.delenv(STORE_ROOT_ENV, raising=False)
    for env_var, artifact in _declared_artifacts().items():
        monkeypatch.delenv(env_var, raising=False)
        with pytest.raises(pytest.skip.Exception) as excinfo:
            resolve_store_artifact(artifact)
        assert STORE_ROOT_ENV in str(excinfo.value)
        assert env_var in str(excinfo.value), f"{env_var} is not named in its own skip reason"


def test_the_pinned_set_can_actually_fail() -> None:
    """SEEDED: the discovery is by type, so prove an undeclared artifact would be caught.

    Without this, `test_the_store_artifact_set_is_pinned` could be passing because the
    scan finds nothing at all and the expected set happens to be compared against itself.
    """
    found = _declared_artifacts()
    assert found, "the scan found no artifacts; the pin above would be vacuous"

    intruder = StoreArtifact(
        env_var="DOLPHINQUANT_SEEDED_INTRUDER",
        store_relative="datasets/nothing/at/all",
    )
    seeded = {**found, intruder.env_var: intruder}
    assert set(seeded) != EXPECTED_STORE_ARTIFACTS
