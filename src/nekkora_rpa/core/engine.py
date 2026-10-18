"""Engine do ciclo de vida: INIT → TRANSFER_DATA_IN → PROCESS → TRANSFER_DATA_OUT → (próximo item | END).

Regras centrais:
- O checkpoint marca a transação EM ANDAMENTO **antes** de qualquer ação; se não puder gravar, nada é feito.
- Uma transação só é tentada de novo (no mesmo lote ou numa retomada) se NENHUMA ação de efeito colateral foi
  despachada: falha técnica sem efeito → ``FAILED_TECHNICAL`` (reprocessável); falha depois de efeito possível →
  ``OUTCOME_UNKNOWN`` (nunca reprocessada automaticamente).
- Na retomada, transação encontrada EM ANDAMENTO passa por ``reconcile``; sem prova, fica ``OUTCOME_UNKNOWN``.
- Destino que falha depois de receber → ``OUTCOME_UNKNOWN`` (salvo destino idempotente e nenhum efeito).
- Segurança, configuração, cancelamento, checkpoint e entrada indisponível param o lote; falhas técnicas seguidas
  acima do limite também. Não existe "continuar em qualquer erro".
- END roda sempre que algo foi aberto, inclusive depois de falha no INIT, e nunca substitui a causa original.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .._version import __version__
from ..adapters.playwright.browser import BrowserSession
from ..errors.codes import ErrorCategory, ErrorCode, OutcomeUnknownReason
from ..errors.exceptions import (
    BusinessRuleRejected,
    Cancelled,
    InputProviderFailed,
    InvalidConfiguration,
    NekkoraRpaError,
    OutcomeUnknown,
)
from ..libs.actions import Actions
from ..observability.events import EventCode, Phase
from ..observability.logger import ConsoleEventSink, EventLogger, EventSink, JsonlEventSink
from ..observability.safety import is_token
from ..resilience.timing import CancelToken, Clock, Deadline, SystemClock
from ..security.secrets import SecretProvider
from ..selectors.registry import SelectorRegistry
from .checkpoints import CheckpointRecord, CheckpointStore, atomic_write
from .config import RuntimeConfig
from .context import ExecutionContext, TransactionScope, new_execution_id
from .contracts import (
    ALLOWED_TRANSITIONS,
    DeliveryStatus,
    InputProvider,
    ProcessResult,
    ReconciliationVerdict,
    ResultSink,
    RpaProcess,
    Runtime,
    SinkRejected,
    TransactionItem,
    TransactionOutcome,
    TransactionStatus,
)

_STOP_CATEGORIES = frozenset({ErrorCategory.SECURITY, ErrorCategory.CONFIGURATION, ErrorCategory.CANCELLED})
_FAILURES = frozenset({TransactionStatus.FAILED_TECHNICAL, TransactionStatus.OUTCOME_UNKNOWN})


class RunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    """Todos os itens terminaram em SUCCEEDED, BUSINESS_REJECTED ou SKIPPED."""
    COMPLETED_WITH_FAILURES = "COMPLETED_WITH_FAILURES"
    STOPPED = "STOPPED"
    INIT_FAILED = "INIT_FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TransactionReport:
    transaction_id: str
    status: TransactionStatus
    error_code: str | None
    detail: str | None
    attempts: int
    delivery: DeliveryStatus


@dataclass
class RunSummary:
    execution_id: str
    status: RunStatus
    stop_code: str | None = None
    stop_detail: str | None = None
    transactions: list[TransactionReport] = field(default_factory=list)
    cleanup_ok: bool = True

    def count(self, status: TransactionStatus) -> int:
        return sum(1 for t in self.transactions if t.status is status)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "nekkora-rpa/run-summary",
            "version": "1.0.0",
            "execution_id": self.execution_id,
            "framework_version": __version__,
            "status": self.status.value,
            "stop_code": self.stop_code,
            "stop_detail": self.stop_detail,
            "cleanup_ok": self.cleanup_ok,
            "counts": {s.value: self.count(s) for s in TransactionStatus if self.count(s)},
            "transactions": [
                {
                    "transaction_id": t.transaction_id,
                    "status": t.status.value,
                    "error_code": t.error_code,
                    "detail": t.detail,
                    "attempts": t.attempts,
                    "delivery": t.delivery.value,
                }
                for t in self.transactions
            ],
        }


class _Stop(Exception):
    def __init__(self, error: NekkoraRpaError) -> None:
        super().__init__(error.code.value)
        self.error = error


def _type_name(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if is_token(name) else "Exception"


def _check_transition(old: TransactionStatus, new: TransactionStatus) -> None:
    if new not in ALLOWED_TRANSITIONS.get(old, frozenset()):
        raise AssertionError(f"transição proibida {old}->{new}")


class Engine:
    def __init__(
        self,
        process: RpaProcess,
        provider: InputProvider,
        sink: ResultSink,
        config: RuntimeConfig,
        *,
        secrets: SecretProvider | None = None,
        registry: SelectorRegistry | None = None,
        run_dir: Path | None = None,
        checkpoint: CheckpointStore | None = None,
        event_sinks: list[EventSink] | None = None,
        console: bool = False,
        cancel: CancelToken | None = None,
        clock: Clock | None = None,
        session_factory: Callable[[RuntimeConfig], BrowserSession] | None = None,
        execution_id: str | None = None,
    ) -> None:
        if not is_token(process.name):
            raise InvalidConfiguration(detail="process_name")
        self.process = process
        self.provider = provider
        self.sink = sink
        self.config = config
        self.secrets = secrets
        self.registry = registry
        self.run_dir = run_dir if run_dir is not None else config.run_dir
        self.checkpoint = checkpoint or CheckpointStore(
            (self.run_dir / "checkpoint.json") if self.run_dir else None, process.name
        )
        sinks: list[EventSink] = list(event_sinks or [])
        if self.run_dir is not None:
            sinks.append(JsonlEventSink(self.run_dir / "events.jsonl"))
        if console:
            sinks.append(ConsoleEventSink())
        self.cancel = cancel or CancelToken()
        self.clock = clock or SystemClock()
        self.session_factory = session_factory or (lambda c: BrowserSession(c.browser, c.origins, c.timeouts))
        self.execution_id = execution_id or new_execution_id()
        self.logger = EventLogger(self.execution_id, __version__, sinks)
        self.ctx = ExecutionContext(config, self.logger, self.clock, self.cancel)
        self.session: BrowserSession | None = None
        self.summary = RunSummary(self.execution_id, RunStatus.COMPLETED)
        self._process_init_started = False

    # ------------------------------------------------------------------ execução
    def run(self) -> RunSummary:
        ctx = self.ctx
        rt = Runtime(ctx, None, self.secrets)
        ctx.emit(EventCode.ENGINE_STARTED)
        init_error: NekkoraRpaError | None = None
        stop: NekkoraRpaError | None = None
        self._process_init_started = False
        try:
            self._phase(Phase.INIT)
            try:
                self._init(rt)
                ctx.emit(EventCode.PHASE_COMPLETED)
            except NekkoraRpaError as err:
                init_error = err
            except Exception as exc:  # noqa: BLE001 — falha externa no INIT (ex.: navegador não abriu)
                init_error = NekkoraRpaError(ErrorCode.UNEXPECTED_ERROR, cause_type=_type_name(exc))
            if init_error is not None:
                ctx.emit(
                    EventCode.PHASE_FAILED,
                    error_code=init_error.code.value,
                    detail=init_error.detail,
                    cause_type=init_error.cause_type,
                )
            else:
                try:
                    self._loop(rt)
                except _Stop as s:
                    stop = s.error
        finally:
            self._end(rt, self._process_init_started)
        self._finish(init_error, stop)
        return self.summary

    def _phase(self, phase: Phase) -> None:
        self.ctx.phase = phase
        self.ctx.emit(EventCode.PHASE_STARTED)

    def _init(self, rt: Runtime) -> None:
        cp = self.checkpoint
        cp.load()
        if cp.loaded:
            self.ctx.emit(EventCode.CHECKPOINT_LOADED, count=len(cp.records))
        if self.registry is None and self.config.selectors_path is not None:
            self.registry = SelectorRegistry.load(self.config.selectors_path, environment=self.config.environment)
        if self.registry is not None:
            self.logger.selector_registry_revision = self.registry.revision
        if self.process.required_secrets:
            if self.secrets is None:
                raise InvalidConfiguration(detail="secret_provider_missing")
            for name in self.process.required_secrets:
                self.secrets.get(name)  # só confere a existência; o valor não é guardado
        if self.process.requires_browser:
            if self.registry is None:
                raise InvalidConfiguration(detail="selectors_missing")
            self.session = self.session_factory(self.config)
            self.session.start()
            rt.actions = Actions(self.ctx, self.session, self.registry)
        self._process_init_started = True
        self.process.init(rt)

    def _loop(self, rt: Runtime) -> None:
        streak = 0
        seen: set[str] = set()
        limit = self.config.batch.max_consecutive_technical_failures
        while True:
            if self.cancel.cancelled:
                self.ctx.emit(EventCode.CANCELLED)
                raise _Stop(Cancelled())
            self._phase(Phase.TRANSFER_DATA_IN)
            try:
                item = self.provider.next_item()
            except NekkoraRpaError as err:
                raise _Stop(err) from None
            except Exception as exc:  # noqa: BLE001
                raise _Stop(InputProviderFailed(cause_type=_type_name(exc))) from None
            if item is None:
                self.ctx.emit(EventCode.PHASE_COMPLETED, outcome="NO_MORE_ITEMS")
                return
            if not isinstance(item, TransactionItem) or not isinstance(item.reference, str) or not item.reference:
                raise _Stop(InputProviderFailed(detail="invalid_item"))
            tx = self.checkpoint.transaction_id(item.reference)
            if tx in seen:
                raise _Stop(InputProviderFailed(detail="duplicate_reference"))
            seen.add(tx)
            self.ctx.emit(EventCode.PHASE_COMPLETED, transaction_id=tx)
            report = self._transaction(rt, item, tx)
            if report.status in _FAILURES:
                streak += 1
                if streak >= limit:
                    raise _Stop(
                        NekkoraRpaError(
                            ErrorCode(report.error_code or "UNEXPECTED_ERROR"), detail="consecutive_failures"
                        )
                    )
            elif report.status in (TransactionStatus.SUCCEEDED, TransactionStatus.BUSINESS_REJECTED):
                streak = 0

    # ------------------------------------------------------------------ uma transação
    def _transaction(self, rt: Runtime, item: TransactionItem, tx: str) -> TransactionReport:
        ctx = self.ctx
        prior = self.checkpoint.get(tx)
        attempts = prior.attempts if prior else 0
        if prior is not None and prior.status is not TransactionStatus.IN_PROGRESS:
            reprocess = (
                prior.status in (TransactionStatus.FAILED_TECHNICAL, TransactionStatus.CANCELLED)
                and prior.side_effects == 0
            )
            if not reprocess:
                reason = (
                    "ALREADY_FINAL"
                    if prior.status in (TransactionStatus.SUCCEEDED, TransactionStatus.BUSINESS_REJECTED)
                    else "NEEDS_REVIEW"
                )
                ctx.emit(EventCode.TRANSACTION_SKIPPED, transaction_id=tx, outcome=prior.status.value, detail=reason)
                return self._report(
                    TransactionReport(tx, TransactionStatus.SKIPPED, prior.error_code, reason, attempts, prior.delivery)
                )

        status: TransactionStatus
        result: ProcessResult | None = None
        error: NekkoraRpaError | None = None
        side_effects = prior.side_effects if prior else 0
        stop_after: NekkoraRpaError | None = None
        self._phase(Phase.PROCESS)
        ctx.emit(EventCode.TRANSACTION_STARTED, transaction_id=tx, attempt=attempts + 1)

        # retomada de transação interrompida: só a reconciliação decide; nunca reprocessar às cegas
        if prior is not None and prior.status is TransactionStatus.IN_PROGRESS:
            ctx.transaction = TransactionScope(tx, Deadline.after_ms(self.config.timeouts.transaction_ms, self.clock))
            ctx.emit(EventCode.RECONCILIATION_STARTED)
            try:
                rec = self.process.reconcile(rt, item)
                verdict = rec.verdict
            except Exception as exc:  # noqa: BLE001
                verdict = ReconciliationVerdict.UNKNOWN
                ctx.emit(EventCode.RECONCILIATION_COMPLETED, outcome=verdict.value, cause_type=_type_name(exc))
            else:
                ctx.emit(EventCode.RECONCILIATION_COMPLETED, outcome=verdict.value)
            ctx.transaction = None
            if verdict is ReconciliationVerdict.DONE:
                status, result = TransactionStatus.SUCCEEDED, rec.result or ProcessResult()
                side_effects = max(side_effects, 1)
                return self._deliver(rt, item, tx, status, result, None, side_effects, attempts)
            if verdict is not ReconciliationVerdict.NOT_DONE:
                error = OutcomeUnknown(OutcomeUnknownReason.INTERRUPTED_RUN)
                return self._deliver(
                    rt, item, tx, TransactionStatus.OUTCOME_UNKNOWN, None, error, side_effects, attempts
                )
            side_effects = 0  # comprovadamente não aconteceu

        max_attempts = self.config.batch.max_transaction_attempts
        local_attempt = 0
        while True:
            local_attempt += 1
            attempts += 1
            scope = TransactionScope(
                tx, Deadline.after_ms(self.config.timeouts.transaction_ms, self.clock), attempt=attempts
            )
            ctx.transaction = scope
            self._put(
                tx,
                CheckpointRecord(
                    TransactionStatus.IN_PROGRESS, side_effects=0, attempts=attempts, execution_id=self.execution_id
                ),
            )
            try:
                result = self.process.process(rt, item)
                if not isinstance(result, ProcessResult):
                    raise InvalidConfiguration(detail="process_result_type")
                status, error = TransactionStatus.SUCCEEDED, None
            except BusinessRuleRejected as err:
                status, error = TransactionStatus.BUSINESS_REJECTED, err
            except OutcomeUnknown as err:
                status, error = TransactionStatus.OUTCOME_UNKNOWN, err
            except NekkoraRpaError as err:
                error = err
                status = TransactionStatus.FAILED_TECHNICAL
                if err.category is ErrorCategory.CANCELLED:
                    status = TransactionStatus.CANCELLED
                if err.category in _STOP_CATEGORIES:
                    stop_after = err
            except Exception as exc:  # noqa: BLE001 — erro do código do processo: código estável, sem mensagem
                error = NekkoraRpaError(ErrorCode.UNEXPECTED_ERROR, cause_type=_type_name(exc))
                status = TransactionStatus.FAILED_TECHNICAL
            side_effects = scope.side_effects
            ctx.transaction = None
            if status in (TransactionStatus.FAILED_TECHNICAL, TransactionStatus.CANCELLED) and side_effects > 0:
                # o efeito pode ter acontecido antes da falha: repetir duplicaria
                error = OutcomeUnknown(
                    OutcomeUnknownReason.ACTION_INTERRUPTED, cause_type=error.code.value if error else None
                )
                status = TransactionStatus.OUTCOME_UNKNOWN
            if status is TransactionStatus.FAILED_TECHNICAL and stop_after is None:
                if local_attempt < max_attempts:
                    ctx.emit(
                        EventCode.TRANSACTION_RETRY_SCHEDULED,
                        transaction_id=tx,
                        attempt=attempts,
                        error_code=error.code.value if error else None,
                    )
                    try:
                        self.process.recover(rt)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        ctx.emit(
                            EventCode.TRANSACTION_RETRY_DENIED,
                            transaction_id=tx,
                            attempt=attempts,
                            detail="RECOVER_FAILED",
                            cause_type=_type_name(exc),
                        )
                elif max_attempts > 1:
                    ctx.emit(
                        EventCode.TRANSACTION_RETRY_DENIED,
                        transaction_id=tx,
                        attempt=attempts,
                        detail="ATTEMPTS_EXHAUSTED",
                    )
            elif status is TransactionStatus.OUTCOME_UNKNOWN and max_attempts > 1:
                ctx.emit(
                    EventCode.TRANSACTION_RETRY_DENIED, transaction_id=tx, attempt=attempts, detail="OUTCOME_UNKNOWN"
                )
            break
        report = self._deliver(rt, item, tx, status, result, error, side_effects, attempts)
        if stop_after is not None:
            raise _Stop(stop_after)
        return report

    def _deliver(
        self,
        rt: Runtime,
        item: TransactionItem,
        tx: str,
        status: TransactionStatus,
        result: ProcessResult | None,
        error: NekkoraRpaError | None,
        side_effects: int,
        attempts: int,
    ) -> TransactionReport:
        ctx = self.ctx
        self._phase(Phase.TRANSFER_DATA_OUT)
        outcome = TransactionOutcome(
            tx,
            status,
            result.output if result else None,
            error.code.value if error else None,
            error.detail if error else None,
        )
        try:
            self.sink.deliver(item, outcome)
            delivery = DeliveryStatus.COMMITTED
            ctx.emit(EventCode.SINK_COMMITTED, transaction_id=tx, outcome=status.value)
        except SinkRejected as exc:
            delivery = DeliveryStatus.REJECTED
            ctx.emit(EventCode.SINK_FAILED, transaction_id=tx, outcome=status.value, cause_type=_type_name(exc))
        except Exception as exc:  # noqa: BLE001 — qualquer outra falha: pode ter gravado
            delivery = DeliveryStatus.UNCERTAIN
            ctx.emit(EventCode.SINK_UNCERTAIN, transaction_id=tx, outcome=status.value, cause_type=_type_name(exc))
        if delivery is not DeliveryStatus.COMMITTED and status in (
            TransactionStatus.SUCCEEDED,
            TransactionStatus.BUSINESS_REJECTED,
        ):
            safe = side_effects == 0 and (delivery is DeliveryStatus.REJECTED or self.sink.idempotent)
            if safe:
                status = TransactionStatus.FAILED_TECHNICAL
                error = NekkoraRpaError(ErrorCode.TRANSIENT_TECHNICAL_FAILURE, detail="SINK_" + delivery.value)
            else:
                status = TransactionStatus.OUTCOME_UNKNOWN
                error = OutcomeUnknown(OutcomeUnknownReason.SINK_UNCERTAIN)
        if status is TransactionStatus.OUTCOME_UNKNOWN:
            ctx.emit(EventCode.OUTCOME_UNKNOWN, transaction_id=tx, detail=error.detail if error else None)
        _check_transition(TransactionStatus.IN_PROGRESS, status)
        self._put(
            tx,
            CheckpointRecord(
                status,
                delivery=delivery,
                side_effects=side_effects,
                attempts=attempts,
                error_code=error.code.value if error else None,
                detail=error.detail if error else None,
                execution_id=self.execution_id,
            ),
        )
        code = (
            EventCode.TRANSACTION_COMPLETED
            if status in (TransactionStatus.SUCCEEDED, TransactionStatus.BUSINESS_REJECTED)
            else EventCode.TRANSACTION_FAILED
        )
        ctx.emit(
            code,
            transaction_id=tx,
            outcome=status.value,
            attempt=attempts,
            error_code=error.code.value if error else None,
            detail=error.detail if error else None,
            cause_type=error.cause_type if error else None,
        )
        return self._report(
            TransactionReport(
                tx, status, error.code.value if error else None, error.detail if error else None, attempts, delivery
            )
        )

    def _report(self, report: TransactionReport) -> TransactionReport:
        self.summary.transactions.append(report)
        return report

    def _put(self, tx: str, record: CheckpointRecord) -> None:
        try:
            self.checkpoint.put(tx, record)
        except NekkoraRpaError as err:
            raise _Stop(err) from None
        self.ctx.emit(EventCode.CHECKPOINT_SAVED, transaction_id=tx, outcome=record.status.value)

    # ------------------------------------------------------------------ END
    def _end(self, rt: Runtime, process_init_called: bool) -> None:
        ctx = self.ctx
        self._phase(Phase.END)
        ok = True
        if process_init_called:
            try:
                self.process.end(rt)
            except Exception as exc:  # noqa: BLE001
                ok = False
                ctx.emit(EventCode.CLEANUP_FAILED, detail="process_end", cause_type=_type_name(exc))
        if self.session is not None:
            if self.session.close():
                ctx.emit(EventCode.CLEANUP_COMPLETED, detail="browser")
            else:
                ok = False
                ctx.emit(EventCode.CLEANUP_FAILED, detail="browser")
        self.summary.cleanup_ok = ok

    def _finish(self, init_error: NekkoraRpaError | None, stop: NekkoraRpaError | None) -> None:
        s = self.summary
        if init_error is not None:
            s.status, s.stop_code, s.stop_detail = RunStatus.INIT_FAILED, init_error.code.value, init_error.detail
        elif stop is not None:
            s.status = RunStatus.CANCELLED if stop.category is ErrorCategory.CANCELLED else RunStatus.STOPPED
            s.stop_code, s.stop_detail = stop.code.value, stop.detail
        elif any(t.status in _FAILURES or t.status is TransactionStatus.CANCELLED for t in s.transactions):
            s.status = RunStatus.COMPLETED_WITH_FAILURES
        self.ctx.phase = Phase.END
        self.ctx.emit(
            EventCode.ENGINE_COMPLETED,
            outcome=s.status.value,
            error_code=s.stop_code,
            detail=s.stop_detail,
            count=len(s.transactions),
        )
        if self.run_dir is not None:
            try:
                self.run_dir.mkdir(parents=True, exist_ok=True)
                atomic_write(
                    self.run_dir / "summary.json", json.dumps(s.to_dict(), ensure_ascii=False, indent=2) + "\n"
                )
            except OSError:
                self.logger.sink_failures += 1
        self.logger.close()
