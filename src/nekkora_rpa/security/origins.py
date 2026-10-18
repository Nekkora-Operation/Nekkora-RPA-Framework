"""Política de origens permitidas (allowlist).

Nesta versão só existe o ambiente LAB, e LAB é **loopback**: ``127.0.0.1``, ``localhost`` ou ``[::1]``. Qualquer outra
origem configurada é recusada na carga da configuração. Em execução, a política é aplicada em três pontos:
1. antes de ``navigate`` (o destino é conferido antes de qualquer requisição);
2. no roteamento do contexto do navegador: toda requisição (navegação, redirecionamento, recurso, aba nova) para
   origem fora da lista é abortada antes de sair;
3. antes de cada ação sobre elemento: a página atual precisa estar numa origem permitida.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from ..errors.exceptions import InvalidConfiguration, SecurityPolicyBlocked

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_DEFAULT_PORT = {"http": 80, "https": 443}


def origin_of(url: str) -> str | None:
    """``scheme://host:porta`` normalizado, ou ``None`` se a URL não for http(s) absoluta e limpa."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORT or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower()
    host_part = f"[{host}]" if ":" in host else host
    return f"{scheme}://{host_part}:{port or _DEFAULT_PORT[scheme]}"


class OriginPolicy:
    def __init__(self, allowed: Iterable[str], *, environment: str = "lab") -> None:
        if environment != "lab":
            raise InvalidConfiguration(detail="environment")
        normalized: set[str] = set()
        for url in allowed:
            origin = origin_of(url)
            if origin is None or urlsplit(url).path not in ("", "/") or urlsplit(url).query or urlsplit(url).fragment:
                raise InvalidConfiguration(detail="allowed_origins")
            host = urlsplit(origin).hostname
            if host not in LOOPBACK_HOSTS:
                raise InvalidConfiguration(detail="allowed_origins_not_lab")
            normalized.add(origin)
        if not normalized:
            raise InvalidConfiguration(detail="allowed_origins")
        self.allowed = frozenset(normalized)

    def is_allowed(self, url: str) -> bool:
        origin = origin_of(url)
        return origin is not None and origin in self.allowed

    def is_inert(self, url: str) -> bool:
        """Páginas internas sem origem de rede (aba recém-aberta)."""
        return url in ("about:blank", "")

    def require(self, url: str, *, key: str | None = None, step_id: str | None = None) -> None:
        if not self.is_allowed(url):
            raise SecurityPolicyBlocked(key=key, step_id=step_id, detail="ORIGIN_NOT_ALLOWED")
