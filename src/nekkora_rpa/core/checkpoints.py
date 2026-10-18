"""Checkpoint local ``nekkora-rpa/checkpoint`` 1.0.0.

Guarda só identificadores pseudônimos, estados e códigos — nenhum valor de entrada, saída, referência de item,
URL ou texto. Escrita atômica (arquivo temporário na mesma pasta → ``flush`` + ``fsync`` → ``os.replace``) e
integridade por sha-256 do corpo canônico. Arquivo ilegível, de outra versão, de outro processo ou com integridade
quebrada → ``CHECKPOINT_CORRUPTED``: a execução NÃO recomeça do zero em silêncio.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from ..errors.exceptions import CheckpointCorrupted, CheckpointWriteFailed
from ..observability.logger import utc_now
from ..observability.safety import is_token
from .contracts import DeliveryStatus, TransactionStatus

SCHEMA = "nekkora-rpa/checkpoint"
VERSION = "1.1.0"
READABLE = frozenset({"1.0.0", "1.1.0"})  # retomada de checkpoints gravados pela 0.1.0


@dataclass
class CheckpointRecord:
    status: TransactionStatus
    delivery: DeliveryStatus = DeliveryStatus.NOT_DELIVERED
    side_effects: int = 0
    attempts: int = 0
    error_code: str | None = None
    detail: str | None = None
    execution_id: str | None = None
    updated_utc: str | None = None


def transaction_id_for(salt: str, reference: str) -> str:
    digest = hmac.new(bytes.fromhex(salt), reference.encode("utf-8"), hashlib.sha256).hexdigest()
    return "tx-" + digest[:20]


def _canonical(body: dict[str, object]) -> str:
    return json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


Writer = Callable[[Path, str], None]


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class CheckpointStore:
    def __init__(self, path: Path | None, process_name: str, *, writer: Writer | None = None) -> None:
        self.path = path
        self.process_name = process_name
        self._writer = writer or atomic_write
        self.salt = secrets.token_hex(16)
        self.records: dict[str, CheckpointRecord] = {}
        self.loaded = False

    def load(self) -> None:
        """Carrega o arquivo se existir. Arquivo ausente = execução nova. Sem caminho = só em memória."""
        if self.path is None or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or set(raw) != {"body", "integrity"}:
                raise ValueError
            body = raw["body"]
            expected = "sha256:" + hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
            if not hmac.compare_digest(str(raw["integrity"]), expected):
                raise CheckpointCorrupted(detail="integrity")
            if body.get("schema") != SCHEMA or body.get("version") not in READABLE:
                raise CheckpointCorrupted(detail="version")
            if body.get("process_name") != self.process_name:
                raise CheckpointCorrupted(detail="other_process")
            salt = body["salt"]
            bytes.fromhex(salt)
            records: dict[str, CheckpointRecord] = {}
            for tx, r in body["transactions"].items():
                if not is_token(tx) or not isinstance(r, dict):
                    raise ValueError
                rec = CheckpointRecord(
                    status=TransactionStatus(r["status"]),
                    delivery=DeliveryStatus(r["delivery"]),
                    side_effects=int(r["side_effects"]),
                    attempts=int(r["attempts"]),
                    error_code=r.get("error_code"),
                    detail=r.get("detail"),
                    execution_id=r.get("execution_id"),
                    updated_utc=r.get("updated_utc"),
                )
                for v in (rec.error_code, rec.detail, rec.execution_id, rec.updated_utc):
                    if v is not None and not is_token(v):
                        raise ValueError
                records[tx] = rec
        except CheckpointCorrupted:
            raise
        except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError, AttributeError):
            raise CheckpointCorrupted(detail="unreadable") from None
        self.salt = salt
        self.records = records
        self.loaded = True

    def transaction_id(self, reference: str) -> str:
        return transaction_id_for(self.salt, reference)

    def get(self, tx: str) -> CheckpointRecord | None:
        return self.records.get(tx)

    def put(self, tx: str, record: CheckpointRecord) -> None:
        record.updated_utc = utc_now()
        self.records[tx] = record
        self.save()

    def save(self) -> None:
        if self.path is None:
            return
        body: dict[str, object] = {
            "schema": SCHEMA,
            "version": VERSION,
            "process_name": self.process_name,
            "salt": self.salt,
            "transactions": {
                tx: {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(r).items() if v is not None}
                for tx, r in sorted(self.records.items())
            },
        }
        doc = {"body": body, "integrity": "sha256:" + hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._writer(self.path, json.dumps(doc, ensure_ascii=True, indent=1, sort_keys=True) + "\n")
        except OSError:
            raise CheckpointWriteFailed() from None
