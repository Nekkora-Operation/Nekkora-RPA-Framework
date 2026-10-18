"""Base de Pages: o modelo de UMA tela, com chaves relativas ao prefixo da página.

Uma Page expressa intenções da tela ("preencher filtro", "abrir detalhe") usando a API de ações; ela não conhece
seletores (estão no registro) nem trata retentativa, timeout ou classificação (estão no framework).
"""

from __future__ import annotations

from ..libs.actions import Actions
from ..observability.safety import require_key


class BasePage:
    prefix: str = ""
    """Prefixo das chaves da página, ex.: ``clientes.login``."""
    identity: str = ""
    """Nome (relativo ao prefixo) do alvo que prova que esta é a tela atual."""

    def __init__(self, actions: Actions) -> None:
        require_key(self.prefix + ".x")
        self.act = actions

    def k(self, name: str) -> str:
        return require_key(f"{self.prefix}.{name}")

    def is_current(self) -> bool:
        return self.act.exists(self.k(self.identity))

    def wait_loaded(self, *, timeout_ms: int | None = None, step_id: str | None = None) -> None:
        self.act.wait_visible(self.k(self.identity), timeout_ms=timeout_ms, step_id=step_id)


__all__ = ["BasePage"]
