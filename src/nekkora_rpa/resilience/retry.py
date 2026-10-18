"""Política de retentativa governada pela classificação da falha.

Só repete o que comprovadamente pode ser repetido: falhas ``TRANSIENT_TECHNICAL``. Quem classifica é o adapter, que
sabe se a operação chegou a ser despachada: falha antes do despacho é transitória; falha depois do despacho de uma
operação não idempotente vira ``OUTCOME_UNKNOWN`` e nunca é repetida. Ambiguidade, identidade, negócio, segurança,
configuração e cancelamento também nunca são repetidos.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

from ..errors.codes import CATEGORY, ErrorCategory, ErrorCode
from ..errors.exceptions import InvalidConfiguration, NekkoraRpaError
from .timing import CancelToken, Clock, Deadline

T = TypeVar("T")

_TRANSIENT = frozenset(c for c, cat in CATEGORY.items() if cat is ErrorCategory.TRANSIENT_TECHNICAL)


@dataclass(frozen=True)
class RetryPolicy:
    """Valores explícitos e limitados. ``max_attempts`` conta a primeira tentativa (1 = sem retentativa)."""

    max_attempts: int = 1
    initial_backoff_ms: int = 200
    max_backoff_ms: int = 2_000
    multiplier: float = 2.0
    jitter_ratio: float = 0.0
    retry_on: frozenset[ErrorCode] = field(default=_TRANSIENT)

    def __post_init__(self) -> None:
        ok = (
            isinstance(self.max_attempts, int)
            and 1 <= self.max_attempts <= 10
            and 0 <= self.initial_backoff_ms <= self.max_backoff_ms <= 60_000
            and 1.0 <= self.multiplier <= 10.0
            and 0.0 <= self.jitter_ratio <= 0.5
            and self.retry_on <= _TRANSIENT
        )
        if not ok:
            raise InvalidConfiguration(detail="retry")

    def backoff_ms(self, attempt: int, rng: random.Random | None = None) -> int:
        """Espera antes da tentativa ``attempt + 1`` (``attempt`` >= 1)."""
        base = min(self.max_backoff_ms, self.initial_backoff_ms * self.multiplier ** (attempt - 1))
        if self.jitter_ratio and rng is not None:
            base *= 1 + rng.uniform(-self.jitter_ratio, self.jitter_ratio)
        return int(min(self.max_backoff_ms, max(0, base)))


NO_RETRY = RetryPolicy()


class RetryDenial(StrEnum):
    NOT_RETRYABLE = "NOT_RETRYABLE"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    DEADLINE = "DEADLINE"


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay_ms: int = 0
    denial: RetryDenial | None = None


def decide(
    error: NekkoraRpaError,
    attempt: int,
    policy: RetryPolicy,
    deadline: Deadline | None,
    rng: random.Random | None = None,
) -> RetryDecision:
    """Decisão pura: repetir ou não depois da tentativa ``attempt`` que falhou com ``error``."""
    if error.category is ErrorCategory.UNKNOWN_OUTCOME:
        return RetryDecision(False, denial=RetryDenial.OUTCOME_UNKNOWN)
    if error.category is not ErrorCategory.TRANSIENT_TECHNICAL or error.code not in policy.retry_on:
        return RetryDecision(False, denial=RetryDenial.NOT_RETRYABLE)
    if attempt >= policy.max_attempts:
        return RetryDecision(False, denial=RetryDenial.ATTEMPTS_EXHAUSTED)
    delay = policy.backoff_ms(attempt, rng)
    # a próxima tentativa precisa de tempo útil depois do backoff; senão não adianta esperar
    if deadline is not None and deadline.remaining_ms() <= delay + 50:
        return RetryDecision(False, denial=RetryDenial.DEADLINE)
    return RetryDecision(True, delay_ms=delay)


def run_with_retry(
    operation: Callable[[int], T],
    *,
    policy: RetryPolicy,
    deadline: Deadline | None,
    cancel: CancelToken,
    clock: Clock,
    on_scheduled: Callable[[NekkoraRpaError, int, int], None] | None = None,
    on_denied: Callable[[NekkoraRpaError, int, RetryDenial], None] | None = None,
    rng: random.Random | None = None,
    step_id: str | None = None,
) -> T:
    """Executa ``operation(attempt)`` repetindo só quando ``decide`` permite. A falha final é relançada intacta."""
    attempt = 1
    while True:
        cancel.raise_if_cancelled(step_id)
        try:
            return operation(attempt)
        except NekkoraRpaError as err:
            decision = decide(err, attempt, policy, deadline, rng)
            if not decision.retry:
                if on_denied is not None and decision.denial is not None:
                    on_denied(err, attempt, decision.denial)
                raise
            if on_scheduled is not None:
                on_scheduled(err, attempt, decision.delay_ms)
            clock.sleep(decision.delay_ms / 1000.0, cancel)
            attempt += 1
