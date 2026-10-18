"""Modules: comportamentos funcionais reutilizáveis, parametrizados por chaves do registro.

Não conhecem nenhum sistema específico: o processo/página informa as chaves. Usados por composição (sem herança e
sem dependência de Pages), o que evita acoplamento circular.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..errors.exceptions import InvalidConfiguration
from ..libs.actions import Actions
from ..observability.safety import require_key, require_token
from ..security.secrets import Secret


@dataclass(frozen=True)
class LoginKeys:
    user: str
    password: str
    submit: str
    success: str
    """Alvo que só existe depois de autenticado (pós-condição objetiva do login)."""
    failure: str | None = None
    """Alvo da mensagem de credencial recusada (se a tela tiver)."""

    def __post_init__(self) -> None:
        for k in (self.user, self.password, self.submit, self.success, self.failure):
            if k is not None:
                require_key(k)


class LoginModule:
    """Autenticação por formulário. Login é tratado como idempotente (não tem efeito de negócio), por isso o clique
    pode ser repetido pela política se falhar antes de confirmar. Credencial recusada → ``INVALID_CONFIGURATION``
    (``login_rejected``): o lote para, em vez de insistir e bloquear a conta."""

    def __init__(self, actions: Actions, keys: LoginKeys, *, step_prefix: str = "LOGIN") -> None:
        self.act = actions
        self.keys = keys
        self.step_prefix = require_token(step_prefix, "step_prefix")

    def login(self, user: str | Secret, password: Secret, *, timeout_ms: int | None = None) -> None:
        if not isinstance(password, Secret):
            raise InvalidConfiguration(detail="password_must_be_secret")
        p = self.step_prefix
        self.act.fill(self.keys.user, user, step_id=f"{p}-01")
        self.act.fill(self.keys.password, password, step_id=f"{p}-02")

        def settled() -> bool:
            if self.act.exists(self.keys.success):
                return True
            if self.keys.failure is not None and self.act.exists(self.keys.failure):
                raise InvalidConfiguration(detail="login_rejected")
            return False

        self.act.click(
            self.keys.submit, step_id=f"{p}-03", idempotent=True, timeout_ms=timeout_ms, postcondition=settled
        )


class FormModule:
    """Preenche campos na ordem dada, cada um com seu ``step_id`` (``<prefixo>-NN``)."""

    def __init__(self, actions: Actions, *, step_prefix: str) -> None:
        self.act = actions
        self.step_prefix = require_token(step_prefix, "step_prefix")

    def fill(self, fields: Sequence[tuple[str, str | Secret]]) -> None:
        for n, (key, value) in enumerate(fields, start=1):
            self.act.fill(key, value, step_id=f"{self.step_prefix}-{n:02d}")


__all__ = ["FormModule", "LoginKeys", "LoginModule"]
