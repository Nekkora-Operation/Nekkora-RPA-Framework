"""Política de origens permitidas (allowlist).

Ambientes:
- ``lab``: só **loopback** (``127.0.0.1``, ``localhost``, ``[::1]``); qualquer outra origem é recusada na carga.
- ``benchmark`` (0.2.0): site público de treinamento autorizado explicitamente pela usuária — lista FECHADA de origens
  ``https`` exatas (sem curinga, sem caminho, sem loopback). Não é LAB e nunca é tratado como tal. As mesmas guardas de
  rede valem: o que não estiver na lista (inclusive recursos de terceiros da página) é bloqueado.

Em execução, a política é aplicada em três pontos:
1. antes de ``navigate`` (o destino é conferido antes de qualquer requisição);
2. no roteamento do contexto do navegador: toda requisição (navegação, redirecionamento, recurso, aba nova) para
   origem fora da lista é abortada antes de sair;
3. antes de cada ação sobre elemento: a página atual precisa estar numa origem permitida.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from ..errors.exceptions import InvalidConfiguration, SecurityPolicyBlocked

ENVIRONMENTS = frozenset({"lab", "benchmark"})
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
        if environment not in ENVIRONMENTS:
            raise InvalidConfiguration(detail="environment")
        self.environment = environment
        normalized: set[str] = set()
        for url in allowed:
            origin = origin_of(url)
            if origin is None or urlsplit(url).path not in ("", "/") or urlsplit(url).query or urlsplit(url).fragment:
                raise InvalidConfiguration(detail="allowed_origins")
            host = urlsplit(origin).hostname
            if environment == "lab" and host not in LOOPBACK_HOSTS:
                raise InvalidConfiguration(detail="allowed_origins_not_lab")
            if environment == "benchmark" and (
                not url.lower().startswith("https://") or host in LOOPBACK_HOSTS or "*" in url or host is None
            ):
                raise InvalidConfiguration(detail="allowed_origins_not_benchmark")
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
