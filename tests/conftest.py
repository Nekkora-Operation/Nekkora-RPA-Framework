"""Fixtures compartilhadas: laboratório local, configuração LAB, sessão de navegador e ações.

Variáveis de ambiente:
- ``NK_BROWSER_CHANNEL``: ``chromium`` (padrão, Chromium do Playwright) ou ``chrome`` (Google Chrome instalado);
- ``NK_HEADLESS``: ``0`` para janela visível (padrão ``1``).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.server import Lab  # noqa: E402

from nekkora_rpa import (  # noqa: E402
    Actions,
    BrowserSession,
    EventLogger,
    ExecutionContext,
    MemoryEventSink,
    RuntimeConfig,
    SelectorRegistry,
)
from nekkora_rpa.core.config import from_mapping  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def lab_config(lab_url: str, **sections: dict[str, object]) -> RuntimeConfig:
    data: dict[str, dict[str, object]] = {
        "runtime": {"environment": "lab", "allowed_origins": [lab_url], "base_url": lab_url, "process_name": "teste"},
        "timeouts": {"action_ms": 3_000, "navigation_ms": 8_000, "transaction_ms": 60_000},
        "browser": {
            "channel": os.environ.get("NK_BROWSER_CHANNEL", "chromium"),
            "headless": os.environ.get("NK_HEADLESS", "1") != "0",
        },
    }
    for k, v in sections.items():
        data.setdefault(k, {}).update(v)
    return from_mapping(data, base_dir=ROOT)


@pytest.fixture(scope="session")
def lab() -> Iterator[Lab]:
    instance = Lab().start()
    yield instance
    instance.stop()


@pytest.fixture
def clean_lab(lab: Lab) -> Lab:
    lab.reset()
    return lab


@pytest.fixture
def adv_registry() -> SelectorRegistry:
    return SelectorRegistry.load(FIXTURES / "adv-selectors.json", environment="lab")


class Harness:
    def __init__(self, lab: Lab, registry: SelectorRegistry, **sections: dict[str, object]) -> None:
        self.lab = lab
        self.config = lab_config(lab.url, **sections)
        self.events = MemoryEventSink()
        self.logger = EventLogger("ex-teste", "0.1.0", [self.events], registry.revision)
        self.ctx = ExecutionContext.create(self.config, self.logger)
        self.session = BrowserSession(self.config.browser, self.config.origins, self.config.timeouts)
        self.session.start()
        self.actions = Actions(self.ctx, self.session, registry)

    @property
    def page(self):  # type: ignore[no-untyped-def]
        return self.actions.page

    def open_adv(self, query: str = "") -> None:
        self.actions.navigate("/adversarial/resolver.html" + query)

    def lab_counter(self, name: str) -> int:
        return int(self.page.evaluate(f"() => window.__lab.{name}"))

    def codes(self) -> list[str]:
        return self.events.codes()

    def close(self) -> None:
        self.session.close()


@pytest.fixture
def harness(clean_lab: Lab, adv_registry: SelectorRegistry) -> Iterator[Harness]:
    h = Harness(clean_lab, adv_registry)
    yield h
    h.close()
