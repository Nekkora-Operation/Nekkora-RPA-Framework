"""Eventos ``nekkora-rpa/events`` 1.0.0.

Um evento é uma estrutura FECHADA: campos fixos, tipos fixos, e todo texto é um código enumerado ou um identificador
validado (``safety.TOKEN``). Não existe campo livre ("message", "extra", "data"): por construção, não há onde colocar um
valor de entrada, um texto da página, uma URL, um seletor ou a mensagem de uma exceção externa. O log legível é só
uma projeção deste mesmo evento.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum

from .safety import is_token

SCHEMA = "nekkora-rpa/events"
SCHEMA_VERSION = "1.1.0"  # 1.1.0 (aditiva): ações download/mark, códigos TABULAR_INVALID/DOWNLOAD_INVALID


class Phase(StrEnum):
    INIT = "INIT"
    TRANSFER_DATA_IN = "TRANSFER_DATA_IN"
    PROCESS = "PROCESS"
    TRANSFER_DATA_OUT = "TRANSFER_DATA_OUT"
    END = "END"


class EventCode(StrEnum):
    ENGINE_STARTED = "ENGINE_STARTED"
    ENGINE_COMPLETED = "ENGINE_COMPLETED"
    PHASE_STARTED = "PHASE_STARTED"
    PHASE_COMPLETED = "PHASE_COMPLETED"
    PHASE_FAILED = "PHASE_FAILED"
    TRANSACTION_STARTED = "TRANSACTION_STARTED"
    TRANSACTION_COMPLETED = "TRANSACTION_COMPLETED"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    TRANSACTION_SKIPPED = "TRANSACTION_SKIPPED"
    TRANSACTION_RETRY_SCHEDULED = "TRANSACTION_RETRY_SCHEDULED"
    TRANSACTION_RETRY_DENIED = "TRANSACTION_RETRY_DENIED"
    RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
    RECONCILIATION_COMPLETED = "RECONCILIATION_COMPLETED"
    TARGET_RESOLVED = "TARGET_RESOLVED"
    TARGET_REJECTED = "TARGET_REJECTED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RETRY_DENIED = "RETRY_DENIED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    SINK_COMMITTED = "SINK_COMMITTED"
    SINK_UNCERTAIN = "SINK_UNCERTAIN"
    SINK_FAILED = "SINK_FAILED"
    CHECKPOINT_SAVED = "CHECKPOINT_SAVED"
    CHECKPOINT_LOADED = "CHECKPOINT_LOADED"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"
    CLEANUP_COMPLETED = "CLEANUP_COMPLETED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Event:
    timestamp_utc: str
    execution_id: str
    event_code: EventCode
    framework_version: str
    phase: Phase | None = None
    transaction_id: str | None = None
    step_id: str | None = None
    key: str | None = None
    action: str | None = None
    attempt: int | None = None
    elapsed_ms: int | None = None
    outcome: str | None = None
    error_code: str | None = None
    detail: str | None = None
    cause_type: str | None = None
    strategy_index: int | None = None
    delay_ms: int | None = None
    count: int | None = None
    selector_registry_revision: str | None = None

    def __post_init__(self) -> None:
        for f in fields(self):
            v = getattr(self, f.name)
            if v is None or isinstance(v, (EventCode, Phase)):
                continue
            if isinstance(v, bool) or (isinstance(v, int) and not -1 < v < 10**12):
                raise ValueError(f"event field {f.name}")
            if isinstance(v, str) and not is_token(v):
                raise ValueError(f"event field {f.name}")
            if not isinstance(v, (str, int)):
                raise ValueError(f"event field {f.name}")

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"schema": SCHEMA, "version": SCHEMA_VERSION}
        for f in fields(self):
            v = getattr(self, f.name)
            if v is not None:
                d[f.name] = v.value if isinstance(v, (EventCode, Phase)) else v
        return d
