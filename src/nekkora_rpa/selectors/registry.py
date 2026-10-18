"""Registro central de alvos por chave.

Processos, Pages e Modules referenciam alvos só por chave estável (``clientes.login.entrar``); a referência técnica
(estratégia + expressão) e a identidade esperada ficam aqui, num arquivo versionado. Um registro cobre um sistema:
toda chave começa por ``<system>.``.
"""

from __future__ import annotations

from pathlib import Path

from ..errors.exceptions import InvalidConfiguration
from ..observability.safety import require_key
from .schema import Target, parse


class SelectorRegistry:
    def __init__(self, system: str, revision: str, environment: str, targets: dict[str, Target]) -> None:
        self.system = system
        self.revision = revision
        self.environment = environment
        self._targets = dict(targets)

    @classmethod
    def from_text(cls, text: str, *, environment: str) -> SelectorRegistry:
        system, revision, targets = parse(text, environment=environment)
        return cls(system, revision, environment, targets)

    @classmethod
    def load(cls, path: Path | str, *, environment: str) -> SelectorRegistry:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            raise InvalidConfiguration(detail="selectors_unreadable") from None
        return cls.from_text(text, environment=environment)

    def get(self, key: str) -> Target:
        require_key(key)
        try:
            return self._targets[key]
        except KeyError:
            raise InvalidConfiguration(key=key, detail="selectors_unknown_key") from None

    def keys(self) -> list[str]:
        return sorted(self._targets)

    def __contains__(self, key: object) -> bool:
        return key in self._targets
