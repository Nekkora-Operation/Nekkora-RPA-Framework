"""Contexto de execução: identificadores de correlação, configuração, relógio, cancelamento e estado da transação
corrente (prazo total e efeitos colaterais despachados)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .._version import __version__
from ..observability.events import EventCode, Phase
from ..observability.logger import EventLogger
from ..resilience.timing import CancelToken, Clock, Deadline, SystemClock
from .config import RuntimeConfig


def new_execution_id() -> str:
    return "ex-" + uuid.uuid4().hex[:20]


@dataclass
class TransactionScope:
    transaction_id: str
    deadline: Deadline
    attempt: int = 1
    side_effects: int = 0
    """Ações NÃO idempotentes efetivamente despachadas nesta tentativa da transação."""


@dataclass
class ExecutionContext:
    config: RuntimeConfig
    logger: EventLogger
    clock: Clock = field(default_factory=SystemClock)
    cancel: CancelToken = field(default_factory=CancelToken)
    phase: Phase | None = None
    transaction: TransactionScope | None = None

    @property
    def execution_id(self) -> str:
        return self.logger.execution_id

    @staticmethod
    def create(
        config: RuntimeConfig,
        logger: EventLogger,
        *,
        clock: Clock | None = None,
        cancel: CancelToken | None = None,
    ) -> ExecutionContext:
        return ExecutionContext(config, logger, clock or SystemClock(), cancel or CancelToken())

    def emit(self, code: EventCode, **fields: str | int | None) -> None:
        tx = self.transaction
        if tx is not None:
            fields.setdefault("transaction_id", tx.transaction_id)
        self.logger.emit(code, phase=self.phase, **fields)

    def action_deadline(self, timeout_ms: int) -> Deadline:
        """Prazo da ação = o menor entre o prazo pedido e o que resta da transação."""
        d = Deadline.after_ms(timeout_ms, self.clock)
        return d.earliest(self.transaction.deadline) if self.transaction is not None else d

    def mark_side_effect(self) -> None:
        if self.transaction is not None:
            self.transaction.side_effects += 1


__all__ = ["ExecutionContext", "TransactionScope", "__version__", "new_execution_id"]
