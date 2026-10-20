"""Normalização genérica de textos LIDOS da página (0.3.0).

O framework não interpreta o conteúdo de negócio: estas funções só tornam comparável e gravável o texto que o processo
leu com ``Actions.read_text``/``Actions.read_items``. Nenhuma delas registra o texto recebido.

- ``normalize_text``: Unicode NFC, espaços (inclusive os não separáveis) colapsados em um, sem espaço nas pontas.
- ``join_items``: junta itens de uma lista exibida (``<li>``) com um separador explícito, sem itens vazios.
- ``parse_long_date``: data POR EXTENSO (``21 de junho de 1839``, ``1º de maio de 1990``) → ``AAAA-MM-DD``. Só devolve a
  data quando dia, mês e ano estão TODOS no texto e há exatamente uma data distinta; caso contrário ``None`` (nunca
  completa um dia ou mês ausente nem escolhe entre duas datas).
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import quote, unquote, urlsplit

__all__ = ["DATE_LANGUAGES", "join_items", "normalize_address", "normalize_text", "parse_long_date", "same_address"]

_SPACES = re.compile(r"\s+", re.UNICODE)

_MONTHS: dict[str, dict[str, int]] = {
    "pt": {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    },
}
DATE_LANGUAGES = frozenset(_MONTHS)

# dia (1–31, opcionalmente "1º"/"1°") "de" mês "de" ano (1 a 4 dígitos); limites de palavra dos dois lados
_LONG_DATE = re.compile(
    r"(?<![\w])(?P<day>[0-3]?\d)(?:\s*[º°o])?\s+de\s+(?P<month>[^\W\d_]+)\s+de\s+(?P<year>\d{1,4})(?![\w])",
    re.IGNORECASE | re.UNICODE,
)


def normalize_text(value: str) -> str:
    """Texto comparável: NFC, espaços colapsados, sem espaço nas pontas. Não altera letras nem pontuação."""
    if not isinstance(value, str):
        raise TypeError("value")
    return _SPACES.sub(" ", unicodedata.normalize("NFC", value)).strip()


def join_items(items: Iterable[str], separator: str = "; ") -> str:
    """Itens normalizados (vazios descartados) unidos por ``separator`` (não vazio, sem quebra de linha)."""
    if not isinstance(separator, str) or not separator or "\n" in separator or "\r" in separator:
        raise ValueError("separator")
    out = [normalize_text(i) for i in items]
    return separator.join(i for i in out if i)


def _fold(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word.lower()) if not unicodedata.combining(c))


def parse_long_date(text: str, *, language: str = "pt") -> str | None:
    """``AAAA-MM-DD`` da ÚNICA data por extenso completa contida em ``text``; ``None`` se não houver, se houver mais de
    uma distinta ou se a data não existir no calendário (ex.: 31 de fevereiro)."""
    if language not in _MONTHS:
        raise ValueError("language")
    if not isinstance(text, str):
        raise TypeError("text")
    months = _MONTHS[language]
    found: set[str] = set()
    for m in _LONG_DATE.finditer(unicodedata.normalize("NFC", text)):
        month = months.get(_fold(m.group("month")))
        if month is None:
            continue
        day, year = int(m.group("day")), int(m.group("year"))
        if year < 1:
            return None
        try:
            found.add(_dt.date(year, month, day).isoformat())
        except ValueError:
            return None  # data impossível: não "corrige"
    if len(found) != 1:
        return None
    return next(iter(found))


def normalize_address(url: str) -> str:
    """Forma canônica de um endereço http(s) para COMPARAÇÃO (não para navegar). Fora de http(s) → ``ValueError``."""
    if not isinstance(url, str):
        raise TypeError("url")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("url")
    port = parts.port
    host = parts.hostname.lower()
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        host = f"{host}:{port}"
    path = quote(unicodedata.normalize("NFC", unquote(parts.path or "/")), safe="/:@!$&'()*+,;=-._~")
    return f"{scheme}://{host}{path}" + (f"?{parts.query}" if parts.query else "")


def same_address(a: str, b: str) -> bool:
    """``True`` se ``a`` e ``b`` são o mesmo endereço pela forma canônica de ``normalize_address``."""
    try:
        return normalize_address(a) == normalize_address(b)
    except ValueError:
        return False
