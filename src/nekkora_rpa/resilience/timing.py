"""Relógio, prazos e cancelamento.

Todo prazo é absoluto (instante monotônico de fim), nunca "reiniciado" a cada tentativa: o tempo de uma ação inclui
localização, esperas, tentativas e backoff. Nenhum prazo é infinito.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

from ..errors.codes import ErrorCode
from ..errors.exceptions import Cancelled, InvalidArgument

MAX_TIMEOUT_MS = 30 * 60 * 1000


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float, cancel: CancelToken) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float, cancel: CancelToken) -> None:
        if seconds > 0 and cancel.wait(seconds):
            raise Cancelled()


class CancelToken:
    """Cancelamento cooperativo: pedido de fora (outra thread ou sinal), observado entre etapas e esperas."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> bool:
        return self._event.wait(seconds)

    def raise_if_cancelled(self, step_id: str | None = None) -> None:
        if self._event.is_set():
            raise Cancelled(step_id=step_id)


def check_timeout_ms(value: int, what: str = "timeout_ms") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > MAX_TIMEOUT_MS:
        raise InvalidArgument(ErrorCode.INVALID_ARGUMENT, detail=what)
    return value


@dataclass(frozen=True)
class Deadline:
    """Instante monotônico de fim."""

    end: float
    clock: Clock

    @staticmethod
    def after_ms(ms: int, clock: Clock) -> Deadline:
        return Deadline(clock.monotonic() + check_timeout_ms(ms) / 1000.0, clock)

    def remaining_ms(self) -> int:
        return max(0, int((self.end - self.clock.monotonic()) * 1000))

    @property
    def expired(self) -> bool:
        return self.clock.monotonic() >= self.end

    def earliest(self, other: Deadline | None) -> Deadline:
        return self if other is None or self.end <= other.end else other
