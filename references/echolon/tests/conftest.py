"""Explicit store-path injection for the artifact-backed falsifiers.

echolon does not know where the artifact store lives, what it is called, or how
it sits relative to this checkout. A caller that wants the store-backed
falsifiers to run *injects* the location; nothing here derives a path from the
source tree, so the store can be renamed or relocated without editing echolon.

Injection, highest precedence first:

1. the artifact's own environment variable — an absolute path to that one
   artifact;
2. ``DOLPHINQUANT_STORE_ROOT`` — the store root, onto which the artifact's
   store-relative path is appended.

Resolution is deliberately three-valued, and the third value is the point of
this module:

* nothing injected     -> SKIP. A public checkout has no store; that is a
  legitimate state, not a failure.
* injected but absent  -> FAIL, loudly, naming the variable that supplied the
  path. A caller that named a store and got the name or the nesting level wrong
  must hear about it.
* injected and present -> the path.

The third case is not hypothetical. Before this module existed each falsifier
guessed the store as ``Path(__file__).resolve().parents[4] / "output_bank/..."``
— one directory level above the real store — so eight falsifiers reported
``skipped`` against a path that could never exist. A skip is indistinguishable
from a pass in a suite total, so the wrong root was invisible for as long as it
stood. Guessing is what broke them; a guess is therefore not available here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

#: Store root injected by the caller. Only the store-relative tails below are
#: echolon's business; the root, and hence the store's name, is not.
STORE_ROOT_ENV = "DOLPHINQUANT_STORE_ROOT"


@dataclass(frozen=True)
class StoreArtifact:
    """One store artifact, addressed either directly or under the store root."""

    env_var: str
    store_relative: str


P2_V4_PANEL = StoreArtifact(
    env_var="DOLPHINQUANT_P2_V4_PANEL",
    store_relative="market/panels/p2_v4_shfe_czce_dce_ine",
)
P2_V5_CONTRACTS = StoreArtifact(
    env_var="DOLPHINQUANT_P2_V5_CONTRACTS",
    store_relative="market/panels/p2_v5_shfe_czce_dce_gfex/contracts",
)
GFEX_RAW_BARS = StoreArtifact(
    env_var="DOLPHINQUANT_GFEX_BARS",
    store_relative="datasets/xtdata_expansion_20260711/raw/bars/GFEX",
)
DCE_COMMISSION_AUTHORITY_V2 = StoreArtifact(
    env_var="DCE_COMMISSION_AUTHORITY_V2",
    store_relative="datasets/dce_commission_authority_v2/artifact.json",
)
COMMISSION_AUTHORITY_V3 = StoreArtifact(
    env_var="COMMISSION_AUTHORITY_V3",
    store_relative="datasets/commission_authority_v3/artifact.json",
)


def resolve_store_artifact(artifact: StoreArtifact) -> Path:
    """Return an injected artifact path, or skip/fail per the module contract.

    Raises no exception of its own: pytest's ``skip`` and ``fail`` are the two
    reporting channels, and every path out of this function uses one of them or
    returns a path that exists.
    """
    configured = os.environ.get(artifact.env_var)
    if configured:
        path = Path(configured)
        origin = artifact.env_var
    else:
        root = os.environ.get(STORE_ROOT_ENV)
        if not root:
            pytest.skip(
                f"no artifact store injected: set {STORE_ROOT_ENV} to the store "
                f"root, or {artifact.env_var} to "
                f"<store>/{artifact.store_relative}"
            )
        path = Path(root) / artifact.store_relative
        origin = f"{STORE_ROOT_ENV}={root}"

    if not path.exists():
        pytest.fail(
            f"injected store artifact does not exist: {path}\n"
            f"  supplied by: {origin}\n"
            f"  store-relative path: {artifact.store_relative}\n"
            "An injected path that is missing is a caller error, not a reason "
            "to skip — correct the injection or unset it."
        )
    return path


@pytest.fixture
def p2_v4_panel() -> Path:
    return resolve_store_artifact(P2_V4_PANEL)


@pytest.fixture
def p2_v5_contracts() -> Path:
    return resolve_store_artifact(P2_V5_CONTRACTS)


@pytest.fixture
def gfex_raw_bars() -> Path:
    return resolve_store_artifact(GFEX_RAW_BARS)


@pytest.fixture
def dce_commission_authority_v2() -> Path:
    return resolve_store_artifact(DCE_COMMISSION_AUTHORITY_V2)


@pytest.fixture
def commission_authority_v3() -> Path:
    return resolve_store_artifact(COMMISSION_AUTHORITY_V3)
