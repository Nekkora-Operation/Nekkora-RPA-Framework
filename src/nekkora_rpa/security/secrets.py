"""Credenciais.

``Secret`` embrulha o valor: ``str``, ``repr``, formatação, ``==`` e serialização não o revelam. Só o adapter do
Playwright chama ``reveal()``, no instante de preencher o campo. Valores nunca vão para checkpoint, log, registro de
alvos, documentação nem fixtures publicadas.

``EnvSecretProvider`` (variáveis de ambiente) é a opção do laboratório; produção deve injetar um ``SecretProvider``
próprio (cofre), fora do escopo desta versão.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Protocol, final

from ..errors.exceptions import SecretUnavailable
from ..observability.safety import require_token


@final
class Secret:
    __slots__ = ("__value", "name")

    def __init__(self, name: str, value: str) -> None:
        self.name = require_token(name, "secret_name")
        self.__value = value

    def reveal(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return f"Secret({self.name}, ***)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("Secret não é serializável")


class SecretProvider(Protocol):
    def get(self, name: str) -> Secret:
        """Devolve o segredo ``name`` ou lança ``SecretUnavailable`` (sem revelar nada)."""
        ...


class EnvSecretProvider:
    """Lê ``<prefix><NOME>`` do ambiente. Só nomes declarados em ``allowed`` podem ser pedidos."""

    def __init__(self, allowed: Iterable[str], *, prefix: str = "NK_SECRET_", environ: Mapping[str, str] | None = None):
        self.allowed = frozenset(require_token(n, "secret_name") for n in allowed)
        self.prefix = prefix
        self._environ = environ if environ is not None else os.environ

    def get(self, name: str) -> Secret:
        if name not in self.allowed:
            raise SecretUnavailable(detail="not_declared")
        value = self._environ.get(self.prefix + name.upper().replace(".", "_").replace("-", "_"))
        if not value:
            raise SecretUnavailable(detail="missing")
        return Secret(name, value)

    def require_all(self) -> None:
        """Verificação do INIT: todos os declarados existem (os valores não são guardados aqui)."""
        for name in sorted(self.allowed):
            self.get(name)
