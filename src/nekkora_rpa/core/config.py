"""Configuração de execução (TOML local, sem credenciais) com sobreposição por parâmetros (CLI).

Leitura estrita: seção ou campo desconhecido, tipo errado ou valor fora do limite → ``InvalidConfiguration``.
Caminhos relativos são resolvidos a partir da pasta do arquivo de configuração (nunca do diretório corrente).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors.exceptions import InvalidConfiguration
from ..resilience.retry import RetryPolicy
from ..resilience.timing import MAX_TIMEOUT_MS
from ..security.origins import OriginPolicy, origin_of

_SCHEMA: dict[str, dict[str, type | tuple[type, ...]]] = {
    "runtime": {"environment": str, "allowed_origins": list, "base_url": str, "process_name": str},
    "timeouts": {"action_ms": int, "navigation_ms": int, "transaction_ms": int},
    "retry": {
        "max_attempts": int,
        "initial_backoff_ms": int,
        "max_backoff_ms": int,
        "multiplier": (int, float),
        "jitter_ratio": (int, float),
    },
    "batch": {"max_transaction_attempts": int, "max_consecutive_technical_failures": int},
    "browser": {"channel": str, "headless": bool},
    "paths": {"selectors": str, "run_dir": str},
}


@dataclass(frozen=True)
class Timeouts:
    action_ms: int = 8_000
    navigation_ms: int = 15_000
    transaction_ms: int = 120_000


@dataclass(frozen=True)
class BatchPolicy:
    """``max_transaction_attempts``: tentativas da TRANSAÇÃO inteira, só permitidas quando nenhuma ação com efeito
    colateral foi despachada. ``max_consecutive_technical_failures``: falhas técnicas seguidas que param o lote."""

    max_transaction_attempts: int = 1
    max_consecutive_technical_failures: int = 3


@dataclass(frozen=True)
class BrowserConfig:
    channel: str = "chromium"
    headless: bool = True


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    origins: OriginPolicy
    base_url: str
    process_name: str
    timeouts: Timeouts = field(default_factory=Timeouts)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    batch: BatchPolicy = field(default_factory=BatchPolicy)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    selectors_path: Path | None = None
    run_dir: Path | None = None


def _bad(detail: str) -> InvalidConfiguration:
    return InvalidConfiguration(detail=detail)


def _apply_overrides(data: dict[str, Any], overrides: Mapping[str, object]) -> None:
    for dotted, value in overrides.items():
        section, _, name = dotted.partition(".")
        if section not in _SCHEMA or name not in _SCHEMA[section]:
            raise _bad("config_override_unknown")
        data.setdefault(section, {})[name] = value


def _int(v: object, lo: int, hi: int, detail: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise _bad(detail)
    return v


def from_mapping(data: Mapping[str, Any], *, base_dir: Path) -> RuntimeConfig:
    for section, values in data.items():
        if section not in _SCHEMA or not isinstance(values, dict):
            raise _bad("config_unknown_section")
        for name, v in values.items():
            expected = _SCHEMA[section].get(name)
            if expected is None:
                raise _bad("config_unknown_field")
            if not isinstance(v, expected) or (isinstance(v, bool) and expected is not bool):
                raise _bad(f"config_{section}_{name}")
    rt = data.get("runtime", {})
    if "environment" not in rt or "allowed_origins" not in rt or "base_url" not in rt or "process_name" not in rt:
        raise _bad("config_runtime_missing")
    env = rt["environment"]
    allowed = rt["allowed_origins"]
    if not all(isinstance(a, str) for a in allowed):
        raise _bad("config_runtime_allowed_origins")
    origins = OriginPolicy(allowed, environment=env)
    base_url = rt["base_url"]
    if origin_of(base_url) is None or not origins.is_allowed(base_url):
        raise _bad("config_base_url_not_allowed")
    from ..observability.safety import is_token

    if not is_token(rt["process_name"]):
        raise _bad("config_process_name")
    t = data.get("timeouts", {})
    timeouts = Timeouts(
        action_ms=_int(t.get("action_ms", 8_000), 100, MAX_TIMEOUT_MS, "config_timeouts_action_ms"),
        navigation_ms=_int(t.get("navigation_ms", 15_000), 100, MAX_TIMEOUT_MS, "config_timeouts_navigation_ms"),
        transaction_ms=_int(t.get("transaction_ms", 120_000), 100, MAX_TIMEOUT_MS, "config_timeouts_transaction_ms"),
    )
    r = data.get("retry", {})
    retry = RetryPolicy(
        max_attempts=r.get("max_attempts", 1),
        initial_backoff_ms=r.get("initial_backoff_ms", 200),
        max_backoff_ms=r.get("max_backoff_ms", 2_000),
        multiplier=float(r.get("multiplier", 2.0)),
        jitter_ratio=float(r.get("jitter_ratio", 0.0)),
    )
    b = data.get("batch", {})
    batch = BatchPolicy(
        max_transaction_attempts=_int(b.get("max_transaction_attempts", 1), 1, 5, "config_batch"),
        max_consecutive_technical_failures=_int(
            b.get("max_consecutive_technical_failures", 3), 1, 1000, "config_batch"
        ),
    )
    br = data.get("browser", {})
    channel = br.get("channel", "chromium")
    if channel not in ("chromium", "chrome"):
        raise _bad("config_browser_channel")
    p = data.get("paths", {})
    selectors = (base_dir / p["selectors"]).resolve() if "selectors" in p else None
    run_dir = (base_dir / p["run_dir"]).resolve() if "run_dir" in p else None
    return RuntimeConfig(
        environment=env,
        origins=origins,
        base_url=base_url,
        process_name=rt["process_name"],
        timeouts=timeouts,
        retry=retry,
        batch=batch,
        browser=BrowserConfig(channel=channel, headless=br.get("headless", True)),
        selectors_path=selectors,
        run_dir=run_dir,
    )


def load_config(path: Path | str, overrides: Mapping[str, object] | None = None) -> RuntimeConfig:
    path = Path(path).resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise _bad("config_unreadable") from None
    if overrides:
        _apply_overrides(data, overrides)
    return from_mapping(data, base_dir=path.parent)
