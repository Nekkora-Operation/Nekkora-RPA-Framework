"""F4 — erros e política de retentativa: contagem de tentativas, prazos, backoff, cancelamento e bloqueios."""

from __future__ import annotations

import random
import traceback

import pytest

from nekkora_rpa.errors import (
    ActionTimeout,
    BusinessRuleRejected,
    Cancelled,
    ErrorCategory,
    ErrorCode,
    InvalidConfiguration,
    NekkoraRpaError,
    OutcomeUnknown,
    OutcomeUnknownReason,
    SecurityPolicyBlocked,
    TargetAmbiguous,
    TargetIdentityMismatch,
    TargetNotFound,
    TransientTechnicalFailure,
)
from nekkora_rpa.errors.codes import CATEGORY
from nekkora_rpa.errors.exceptions import external
from nekkora_rpa.resilience.retry import RetryDenial, RetryPolicy, decide, run_with_retry
from nekkora_rpa.resilience.timing import CancelToken, Deadline


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float, cancel: CancelToken) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        cancel.raise_if_cancelled()


def test_todo_codigo_tem_categoria():
    assert set(CATEGORY) == set(ErrorCode)


def test_str_e_repr_so_tem_codigo_e_detalhe():
    err = TargetNotFound(key="clientes.login.entrar", step_id="S-1")
    assert str(err) == "TARGET_NOT_FOUND"
    assert repr(err) == "TargetNotFound(TARGET_NOT_FOUND)"


def test_excecao_externa_nao_e_encadeada_nem_aparece_no_traceback():
    try:
        try:
            raise ValueError("strict mode violation: locator('#cpf-123.456.789-09') resolved to 2 elements SENTINELA")
        except ValueError as exc:
            raise external(ErrorCode.TARGET_AMBIGUOUS, exc, key="adv.x") from None
    except NekkoraRpaError as err:
        text = "".join(traceback.format_exception(err))
        assert err.cause_type == "ValueError" and err.code is ErrorCode.TARGET_AMBIGUOUS
    assert "SENTINELA" not in text and "123.456" not in text


def test_contexto_suprimido_mesmo_sem_from_none():
    try:
        try:
            raise RuntimeError("payload SENTINELA")
        except RuntimeError:
            raise TransientTechnicalFailure()  # noqa: B904 — de propósito: sem "from None"
    except NekkoraRpaError as err:
        assert "SENTINELA" not in "".join(traceback.format_exception(err))


def test_motivo_de_negocio_precisa_ser_codigo():
    assert str(BusinessRuleRejected("CLIENTE_INEXISTENTE")) == "BUSINESS_RULE_REJECTED:CLIENTE_INEXISTENTE"
    with pytest.raises(NekkoraRpaError):
        BusinessRuleRejected("Cliente 123.456.789-09 não existe")


@pytest.mark.parametrize(
    ("error", "denial"),
    [
        (OutcomeUnknown(OutcomeUnknownReason.ACTION_INTERRUPTED), RetryDenial.OUTCOME_UNKNOWN),
        (TargetAmbiguous(), RetryDenial.NOT_RETRYABLE),
        (TargetIdentityMismatch(), RetryDenial.NOT_RETRYABLE),
        (BusinessRuleRejected("REGRA"), RetryDenial.NOT_RETRYABLE),
        (SecurityPolicyBlocked(), RetryDenial.NOT_RETRYABLE),
        (InvalidConfiguration(), RetryDenial.NOT_RETRYABLE),
        (Cancelled(), RetryDenial.NOT_RETRYABLE),
    ],
)
def test_bloqueios_de_retry_automatico(error, denial):  # type: ignore[no-untyped-def]
    d = decide(error, 1, RetryPolicy(max_attempts=5), None)
    assert not d.retry and d.denial is denial


def test_transitoria_repete_com_backoff_limitado_e_conta_tentativas():
    clock, calls = FakeClock(), []

    def op(n: int) -> str:
        calls.append(n)
        if n < 3:
            raise TransientTechnicalFailure()
        return "ok"

    policy = RetryPolicy(max_attempts=4, initial_backoff_ms=100, max_backoff_ms=150, multiplier=2)
    assert run_with_retry(op, policy=policy, deadline=None, cancel=CancelToken(), clock=clock) == "ok"
    assert calls == [1, 2, 3]
    assert clock.sleeps == [0.1, 0.15]


def test_tentativas_esgotadas_relanca_a_falha_original():
    clock, calls, denied = FakeClock(), [], []

    def op(n: int) -> None:
        calls.append(n)
        raise TransientTechnicalFailure(detail="sempre")

    with pytest.raises(TransientTechnicalFailure) as e:
        run_with_retry(
            op,
            policy=RetryPolicy(max_attempts=3, initial_backoff_ms=10),
            deadline=None,
            cancel=CancelToken(),
            clock=clock,
            on_denied=lambda err, n, d: denied.append((n, d)),
        )
    assert calls == [1, 2, 3] and e.value.detail == "sempre"
    assert denied == [(3, RetryDenial.ATTEMPTS_EXHAUSTED)]


def test_resultado_desconhecido_nunca_e_repetido():
    clock, calls = FakeClock(), []

    def op(n: int) -> None:
        calls.append(n)
        raise OutcomeUnknown(OutcomeUnknownReason.ACTION_INTERRUPTED)

    with pytest.raises(OutcomeUnknown):
        run_with_retry(op, policy=RetryPolicy(max_attempts=10), deadline=None, cancel=CancelToken(), clock=clock)
    assert calls == [1] and clock.sleeps == []


def test_prazo_total_nao_reinicia_por_tentativa():
    clock = FakeClock()
    deadline = Deadline.after_ms(1_000, clock)
    calls = []

    def op(n: int) -> None:
        calls.append(n)
        clock.t += 0.4  # cada tentativa consome 400 ms
        raise ActionTimeout()

    with pytest.raises(ActionTimeout):
        run_with_retry(
            op,
            policy=RetryPolicy(max_attempts=10, initial_backoff_ms=100, max_backoff_ms=100),
            deadline=deadline,
            cancel=CancelToken(),
            clock=clock,
        )
    assert calls == [1, 2]  # 0.4 + 0.1 + 0.4 = 0.9 s; a 3ª não caberia
    assert clock.t <= 1.0


def test_backoff_com_jitter_limitado():
    policy = RetryPolicy(max_attempts=5, initial_backoff_ms=1_000, max_backoff_ms=1_500, jitter_ratio=0.5)
    rng = random.Random(7)
    values = [policy.backoff_ms(n, rng) for n in range(1, 50) for _ in range(3)]
    assert max(values) <= 1_500 and min(values) >= 500


def test_cancelamento_durante_backoff():
    clock, cancel = FakeClock(), CancelToken()

    def op(n: int) -> None:
        cancel.cancel()
        raise TransientTechnicalFailure()

    with pytest.raises(Cancelled):
        run_with_retry(op, policy=RetryPolicy(max_attempts=3), deadline=None, cancel=cancel, clock=clock)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": 11},
        {"initial_backoff_ms": 5_000, "max_backoff_ms": 100},
        {"max_backoff_ms": 120_000},
        {"jitter_ratio": 0.9},
        {"retry_on": frozenset({ErrorCode.OUTCOME_UNKNOWN})},
        {"retry_on": frozenset({ErrorCode.TARGET_AMBIGUOUS})},
    ],
)
def test_politica_invalida_e_recusada(kwargs):  # type: ignore[no-untyped-def]
    with pytest.raises(InvalidConfiguration):
        RetryPolicy(**kwargs)


def test_categorias_principais():
    assert TargetNotFound().category is ErrorCategory.TRANSIENT_TECHNICAL
    assert TargetAmbiguous().category is ErrorCategory.PERMANENT_TECHNICAL
    assert OutcomeUnknown(OutcomeUnknownReason.SINK_UNCERTAIN).category is ErrorCategory.UNKNOWN_OUTCOME
