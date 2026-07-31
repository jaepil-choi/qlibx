"""Load a verified release bundle into a runnable PortfolioStrategy.

The S5 bundle is the only sanctioned way strategy logic reaches the live
host. This module turns a hash-verified bundle directory into signal
engines + blend + constructor config, refusing loudly on any mismatch
between the manifest and what the files actually contain.

Refusal properties (all hard failures, no override):
- ``echolon.bundle.load_bundle`` recomputes every file hash first; a
  tampered bundle never reaches engine loading.
- Each signal module must be self-contained (importable standalone) and
  define exactly one ``SignalEngine`` subclass.
- The loaded engine's ``signal_id``/``family`` must equal the manifest's
  (chain of custody between what was certified and what will trade).
- The constructor must be in integer-lot ``implementation`` sizing; a
  research-sized bundle is not deployable.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from echolon.bundle import BundleManifest, BundleSignal, load_bundle
from echolon.portfolio import ConstructorConfig, PortfolioStrategy
from echolon.signals import SignalEngine


@dataclass(frozen=True)
class BundleStrategyRuntime:
    """Everything GoingMerry needs to run one certified bundle."""

    bundle_dir: Path
    manifest: BundleManifest
    engines: list[SignalEngine]
    strategy: PortfolioStrategy
    rebalance_rule: str
    max_drawdown_pct_of_equity: float
    expectations_path: Path


def load_bundle_strategy(bundle_dir: Path | str) -> BundleStrategyRuntime:
    """Verify a bundle and assemble its PortfolioStrategy."""
    root = Path(bundle_dir)
    manifest = load_bundle(root)  # recomputes ALL hashes; raises on any mismatch
    engines = [_load_signal_engine(root, spec, manifest.bundle_version) for spec in manifest.signals]
    constructor_cfg, rebalance_rule = _constructor_config(manifest)
    strategy = PortfolioStrategy(engines, manifest.blend, constructor_cfg)
    return BundleStrategyRuntime(
        bundle_dir=root,
        manifest=manifest,
        engines=engines,
        strategy=strategy,
        rebalance_rule=rebalance_rule,
        max_drawdown_pct_of_equity=_max_drawdown_pct(manifest),
        expectations_path=root / manifest.expectations,
    )


def _constructor_config(manifest: BundleManifest) -> tuple[ConstructorConfig, str]:
    constructor = dict(manifest.constructor)
    rebalance_rule = constructor.pop("rebalance", None)
    if not rebalance_rule:
        raise ValueError(
            "bundle constructor missing required 'rebalance' field (S5); refusing to load"
        )
    sizing_mode = constructor.get("sizing_mode", "implementation")
    if sizing_mode != "implementation":
        raise ValueError(
            f"bundle constructor sizing_mode={sizing_mode!r} is not deployable: "
            "the live book requires integer-lot 'implementation' sizing"
        )
    # ConstructorConfig forbids extra keys, so any unknown constructor field
    # in the manifest fails here rather than being silently dropped.
    return ConstructorConfig(**constructor), str(rebalance_rule)


def _max_drawdown_pct(manifest: BundleManifest) -> float:
    value = manifest.risk.get("max_drawdown_pct_of_equity")
    if value is None:
        raise ValueError(
            "bundle risk missing required 'max_drawdown_pct_of_equity' (S5); refusing to load"
        )
    pct = float(value)
    if pct <= 0:
        raise ValueError(f"bundle max_drawdown_pct_of_equity must be positive, got {pct}")
    return pct


def _load_signal_engine(root: Path, spec: BundleSignal, bundle_version: str) -> SignalEngine:
    params = _load_params(root / spec.params_file, spec.signal_id)
    module = _import_signal_module(root / spec.file, spec.signal_id, bundle_version)
    engine_cls = _single_engine_class(module, spec)
    engine = engine_cls(**params)
    if engine.signal_id != spec.signal_id:
        raise ValueError(
            f"bundle chain-of-custody violation: manifest says signal_id "
            f"{spec.signal_id!r} but {spec.file} defines {engine.signal_id!r}"
        )
    if engine.family != spec.family:
        raise ValueError(
            f"bundle chain-of-custody violation: manifest says family "
            f"{spec.family!r} for {spec.signal_id} but engine declares {engine.family!r}"
        )
    return engine


def _load_params(params_path: Path, signal_id: str) -> dict:
    params = json.loads(params_path.read_text(encoding="utf-8"))
    if not isinstance(params, dict):
        raise ValueError(
            f"params file for {signal_id} must be a JSON object of constructor "
            f"kwargs, got {type(params).__name__}"
        )
    return params


def _import_signal_module(file_path: Path, signal_id: str, bundle_version: str):
    token = re.sub(r"[^0-9A-Za-z_]", "_", f"{bundle_version}_{signal_id}")
    module_name = f"echolon_bundle_signal_{token}"
    module_spec = importlib.util.spec_from_file_location(module_name, file_path)
    if module_spec is None or module_spec.loader is None:
        raise ValueError(f"cannot import bundle signal file: {file_path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    # Never mutate the bundle: a compiled __pycache__ dropped next to the
    # signal file would break the S5 total-hash-coverage rule on the next
    # load (verified by test — this actually happened).
    previous_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        module_spec.loader.exec_module(module)
    except ImportError as exc:
        del sys.modules[module_name]
        raise ValueError(
            f"bundle signal file {file_path.name} is not self-contained "
            f"(import failed: {exc}). Release bundles must inline every helper "
            "their signal modules use — fix the bundle builder, not the loader."
        ) from exc
    except Exception:
        del sys.modules[module_name]
        raise
    finally:
        sys.dont_write_bytecode = previous_dont_write
    return module


def _single_engine_class(module, spec: BundleSignal) -> type[SignalEngine]:
    candidates = [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, SignalEngine)
        and obj is not SignalEngine
        and obj.__module__ == module.__name__
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"bundle signal file {spec.file} must define exactly one SignalEngine "
            f"subclass, found {len(candidates)}"
        )
    return candidates[0]
