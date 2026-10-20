"""Contratos do ciclo de vida: item, resultado, estados, provider de entrada, destino de resultado e processo."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from ..errors.exceptions import InputProviderFailed
from ..observability.safety import require_token

if TYPE_CHECKING:
    from ..libs.actions import Actions
    from ..security.secrets import SecretProvider
    from .context import ExecutionContext


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    BUSINESS_REJECTED = "BUSINESS_REJECTED"
    FAILED_TECHNICAL = "FAILED_TECHNICAL"
    """Falhou SEM nenhuma ação de efeito colateral despachada: reprocessar é seguro."""
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    """Pode ter produzido efeito: nunca é reprocessado automaticamente; exige reconciliação/revisão."""
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset(
    {
        TransactionStatus.SUCCEEDED,
        TransactionStatus.BUSINESS_REJECTED,
        TransactionStatus.FAILED_TECHNICAL,
        TransactionStatus.OUTCOME_UNKNOWN,
        TransactionStatus.SKIPPED,
        TransactionStatus.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: dict[TransactionStatus, frozenset[TransactionStatus]] = {
    TransactionStatus.PENDING: frozenset(
        {TransactionStatus.IN_PROGRESS, TransactionStatus.SKIPPED, TransactionStatus.CANCELLED}
    ),
    TransactionStatus.IN_PROGRESS: TERMINAL - {TransactionStatus.SKIPPED},
}


class DeliveryStatus(StrEnum):
    NOT_DELIVERED = "NOT_DELIVERED"
    COMMITTED = "COMMITTED"
    UNCERTAIN = "UNCERTAIN"
    REJECTED = "REJECTED"


@dataclass(frozen=True, repr=False)
class TransactionItem:
    """Um item de trabalho.

    ``reference``: chave estável do item para retomada (ex.: número do pedido). Pode ser dado de negócio, por isso
    NUNCA é registrada: o framework deriva dela um ``transaction_id`` pseudônimo (HMAC com sal do checkpoint).
    ``data``: entradas do processo; nunca registradas, nunca no checkpoint."""

    reference: str
    data: Mapping[str, object] = field(default_factory=dict)

    def __repr__(self) -> str:
        return "TransactionItem(***)"


@dataclass(frozen=True, repr=False)
class ProcessResult:
    """Saída de negócio de uma transação bem-sucedida, entregue ao ``ResultSink`` (nunca registrada)."""

    output: Mapping[str, object] = field(default_factory=dict)

    def __repr__(self) -> str:
        return "ProcessResult(***)"


@dataclass(frozen=True, repr=False)
class TransactionOutcome:
    transaction_id: str
    status: TransactionStatus
    output: Mapping[str, object] | None = None
    error_code: str | None = None
    detail: str | None = None

    def __repr__(self) -> str:
        return f"TransactionOutcome({self.transaction_id}, {self.status}, {self.error_code})"


class ReconciliationVerdict(StrEnum):
    DONE = "DONE"
    """O efeito comprovadamente aconteceu (o processo devolve o resultado lido do sistema)."""
    NOT_DONE = "NOT_DONE"
    """O efeito comprovadamente NÃO aconteceu: reprocessar é seguro."""
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, repr=False)
class Reconciliation:
    verdict: ReconciliationVerdict
    result: ProcessResult | None = None

    def __repr__(self) -> str:
        return f"Reconciliation({self.verdict})"


# --------------------------------------------------------------------------------------------- entrada e saída
class InputProvider(Protocol):
    def next_item(self) -> TransactionItem | None:
        """Próximo item, ou ``None`` quando acabou. Falha → exceção (o lote para: entrada indisponível)."""
        ...


class SingleInputProvider:
    """Entrada única (processo sem lote)."""

    def __init__(self, item: TransactionItem) -> None:
        self._item: TransactionItem | None = item

    def next_item(self) -> TransactionItem | None:
        item, self._item = self._item, None
        return item


class InMemoryInputProvider:
    def __init__(self, items: Iterable[TransactionItem]) -> None:
        self._items = list(items)
        self._pos = 0
        refs = [i.reference for i in self._items]
        if len(set(refs)) != len(refs):
            raise InputProviderFailed(detail="duplicate_reference")

    def next_item(self) -> TransactionItem | None:
        if self._pos >= len(self._items):
            return None
        self._pos += 1
        return self._items[self._pos - 1]


class SinkRejected(Exception):
    """O destino recusou ANTES de gravar (comprovadamente não entregue)."""

    def __init__(self, reason: str = "rejected") -> None:
        super().__init__(require_token(reason, "reason"))


class ResultSink(Protocol):
    idempotent: bool
    """``True`` se entregar de novo o mesmo ``transaction_id`` não duplica (o destino deduplica pela chave)."""

    def deliver(self, item: TransactionItem, outcome: TransactionOutcome) -> None:
        """Grava o desfecho. ``SinkRejected`` = não gravou. Qualquer outra exceção = INCERTO (pode ter gravado)."""
        ...


class OutputStatus(StrEnum):
    """Desfecho da CONSOLIDAÇÃO de um destino que só materializa a saída no fim (ex.: planilha)."""

    COMMITTED = "COMMITTED"
    """A saída foi gravada e conferida (ou já estava gravada com o mesmo conteúdo)."""
    WITHHELD = "WITHHELD"
    """A saída NÃO foi gravada de propósito (execução incompleta, transações sem sucesso...): nada parcial."""
    FAILED = "FAILED"
    """A gravação falhou; o arquivo final anterior (se havia) ficou intacto."""


@dataclass(frozen=True)
class OutputReport:
    status: OutputStatus
    rows: int
    detail: str | None = None
    """Token do motivo (``incomplete_run``, ``locked``...), nunca conteúdo."""

    def __post_init__(self) -> None:
        if self.detail is not None:
            require_token(self.detail, "detail")


@dataclass(frozen=True)
class OutputRun:
    """O que o engine informa ao destino na consolidação: o desfecho de cada transação DESTA execução e se o lote
    chegou ao fim (sem parada, cancelamento ou falha de INIT)."""

    complete: bool
    statuses: tuple[tuple[str, TransactionStatus], ...] = ()


class FinalizingResultSink(ResultSink, Protocol):
    """Destino com CONSOLIDAÇÃO no fim (0.3.0): ``deliver`` prepara cada transação; ``finalize`` materializa a saída
    uma única vez, de forma atômica e reconciliável. O engine chama ``finalize`` na fase TRANSFER_DATA_OUT, depois do
    lote e antes do END. Nunca deve propagar exceção: falhas viram ``OutputReport(FAILED, ...)``."""

    def finalize(self, run: OutputRun) -> OutputReport: ...


class InMemoryResultSink:
    idempotent = True

    def __init__(self) -> None:
        self.delivered: dict[str, TransactionOutcome] = {}

    def deliver(self, item: TransactionItem, outcome: TransactionOutcome) -> None:
        self.delivered[outcome.transaction_id] = outcome


# --------------------------------------------------------------------------------------------- processo
@dataclass
class Runtime:
    """O que o processo recebe em cada fase."""

    ctx: ExecutionContext
    actions: Actions | None
    secrets: SecretProvider | None

    @property
    def act(self) -> Actions:
        if self.actions is None:
            from ..errors.exceptions import InvalidConfiguration

            raise InvalidConfiguration(detail="process_without_browser")
        return self.actions


class RpaProcess:
    """Base de um processo. Sobrescreva ``process``; as demais fases são opcionais.

    - ``requires_browser``: o engine abre a sessão Playwright no INIT e a fecha no END.
    - ``required_secrets``: nomes conferidos no INIT (os valores não são lidos ali).
    - ``recover``: chamado antes de uma nova tentativa da transação (ex.: voltar à tela inicial). Só há nova tentativa
      quando nenhuma ação de efeito colateral foi despachada.
    - ``reconcile``: chamado na retomada para uma transação que ficou EM ANDAMENTO numa execução interrompida.
      Padrão: ``UNKNOWN`` (o item vai para revisão, nunca é reprocessado às cegas)."""

    name: str = "process"
    requires_browser: bool = True
    required_secrets: tuple[str, ...] = ()

    def init(self, rt: Runtime) -> None:
        pass

    def process(self, rt: Runtime, item: TransactionItem) -> ProcessResult:
        raise NotImplementedError

    def recover(self, rt: Runtime) -> None:
        pass

    def reconcile(self, rt: Runtime, item: TransactionItem) -> Reconciliation:
        return Reconciliation(ReconciliationVerdict.UNKNOWN)

    def end(self, rt: Runtime) -> None:
        pass
