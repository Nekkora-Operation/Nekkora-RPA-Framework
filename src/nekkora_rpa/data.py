"""Entrada e destino genéricos baseados em arquivos locais.

- ``JsonLinesInputProvider``: um objeto JSON por linha; ``reference_field`` indica o campo que identifica o item.
- ``JsonDirectoryResultSink``: um arquivo ``<transaction_id>.json`` por transação, escrito de forma atômica.
  Idempotente: entregar de novo o mesmo ``transaction_id`` reescreve o mesmo arquivo (não duplica).

O destino de resultado é o REGISTRO DE NEGÓCIO do processo (contém a saída de negócio), não um log. Ele não recebe
entradas, credenciais nem referências do item — só o ``transaction_id`` pseudônimo, o estado, o código e a saída.
"""

from __future__ import annotations

import json
from pathlib import Path

from .core.checkpoints import atomic_write
from .core.contracts import TransactionItem, TransactionOutcome
from .errors.exceptions import InputProviderFailed
from .observability.safety import is_token, require_token

RESULT_SCHEMA = "nekkora-rpa/result"
RESULT_VERSION = "1.1.0"


class JsonLinesInputProvider:
    def __init__(self, path: Path | str, *, reference_field: str) -> None:
        self.path = Path(path)
        self.reference_field = require_token(reference_field, "reference_field")
        self._items: list[TransactionItem] | None = None
        self._pos = 0

    def _load(self) -> list[TransactionItem]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            raise InputProviderFailed(detail="unreadable") from None
        out: list[TransactionItem] = []
        for n, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                raise InputProviderFailed(detail=f"invalid_line_{n}") from None
            ref = obj.get(self.reference_field) if isinstance(obj, dict) else None
            if not isinstance(ref, str) or not ref:
                raise InputProviderFailed(detail=f"invalid_line_{n}")
            out.append(TransactionItem(ref, obj))
        return out

    def next_item(self) -> TransactionItem | None:
        if self._items is None:
            self._items = self._load()
        if self._pos >= len(self._items):
            return None
        self._pos += 1
        return self._items[self._pos - 1]


class JsonDirectoryResultSink:
    idempotent = True

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def deliver(self, item: TransactionItem, outcome: TransactionOutcome) -> None:
        if not is_token(outcome.transaction_id):
            raise ValueError("transaction_id")
        self.directory.mkdir(parents=True, exist_ok=True)
        doc = {
            "schema": RESULT_SCHEMA,
            "version": RESULT_VERSION,
            "transaction_id": outcome.transaction_id,
            "status": outcome.status.value,
            "error_code": outcome.error_code,
            "detail": outcome.detail,
            "output": dict(outcome.output) if outcome.output is not None else None,
        }
        atomic_write(
            self.directory / f"{outcome.transaction_id}.json",
            json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )


__all__ = ["JsonDirectoryResultSink", "JsonLinesInputProvider"]
