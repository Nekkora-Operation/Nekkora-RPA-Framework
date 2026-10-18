"""Emissor de eventos e destinos (sinks).

``EventLogger`` é a única porta de saída de observabilidade do framework. Destinos:
- ``JsonlEventSink``: JSON Lines, uma linha por evento (fonte da verdade);
- ``ConsoleEventSink``: projeção legível do mesmo evento (stderr por padrão);
- ``MemoryEventSink``: para testes.
Falha de um destino não derruba a automação, mas também não é escondida: é contada em ``sink_failures``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Protocol

from .events import Event, EventCode, Phase


class EventSink(Protocol):
    def write(self, event: Event) -> None: ...

    def close(self) -> None: ...


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def write(self, event: Event) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass

    def codes(self) -> list[str]:
        return [e.event_code.value for e in self.events]


class JsonlEventSink:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh: IO[str] | None = path.open("a", encoding="utf-8", newline="\n")

    def write(self, event: Event) -> None:
        if self._fh is not None:
            self._fh.write(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class ConsoleEventSink:
    """Linha legível: ``hora fase evento [tx] [step] [key] [tentativa] [erro] [ms]`` — só campos do evento."""

    def __init__(self, stream: IO[str] | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr

    def write(self, event: Event) -> None:
        parts = [event.timestamp_utc[11:23], (event.phase or "-").ljust(17), event.event_code.value]
        for label, v in (
            ("tx", event.transaction_id),
            ("step", event.step_id),
            ("key", event.key),
            ("acao", event.action),
            ("tentativa", event.attempt),
            ("resultado", event.outcome),
            ("erro", event.error_code),
            ("detalhe", event.detail),
            ("causa", event.cause_type),
            ("espera_ms", event.delay_ms),
            ("ms", event.elapsed_ms),
        ):
            if v is not None:
                parts.append(f"{label}={v}")
        self.stream.write(" ".join(parts) + "\n")
        self.stream.flush()

    def close(self) -> None:
        pass


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class EventLogger:
    def __init__(
        self,
        execution_id: str,
        framework_version: str,
        sinks: Iterable[EventSink],
        selector_registry_revision: str | None = None,
    ) -> None:
        self.execution_id = execution_id
        self.framework_version = framework_version
        self.sinks = list(sinks)
        self.selector_registry_revision = selector_registry_revision
        self.sink_failures = 0

    def emit(self, code: EventCode, *, phase: Phase | None = None, **fields: str | int | None) -> Event:
        event = Event(
            timestamp_utc=utc_now(),
            execution_id=self.execution_id,
            event_code=code,
            framework_version=self.framework_version,
            phase=phase,
            selector_registry_revision=self.selector_registry_revision,
            **fields,  # type: ignore[arg-type]
        )
        for sink in self.sinks:
            try:
                sink.write(event)
            except OSError:
                self.sink_failures += 1
        return event

    def close(self) -> None:
        for sink in self.sinks:
            try:
                sink.close()
            except OSError:
                self.sink_failures += 1
