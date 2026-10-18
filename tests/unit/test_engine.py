"""F5/F8 — engine do ciclo de vida, lote, estados, cleanup, checkpoint e retomada (processo falso, sem navegador)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from nekkora_rpa import (
    CancelToken,
    CheckpointStore,
    Engine,
    InMemoryInputProvider,
    InMemoryResultSink,
    MemoryEventSink,
    ProcessResult,
    Reconciliation,
    ReconciliationVerdict,
    RpaProcess,
    RunStatus,
    Runtime,
    SingleInputProvider,
    SinkRejected,
    TransactionItem,
    TransactionStatus,
)
from nekkora_rpa.core.config import from_mapping
from nekkora_rpa.core.contracts import TransactionOutcome
from nekkora_rpa.core.engine import _check_transition
from nekkora_rpa.errors import (
    BusinessRuleRejected,
    InvalidConfiguration,
    SecurityPolicyBlocked,
    TransientTechnicalFailure,
)

S = TransactionStatus
SENT = "SENTINELA-CPF-123.456.789-09"


def config(**batch: int) -> object:
    return from_mapping(
        {
            "runtime": {
                "environment": "lab",
                "allowed_origins": ["http://127.0.0.1:1"],
                "base_url": "http://127.0.0.1:1",
                "process_name": "fake",
            },
            "batch": {"max_transaction_attempts": 1, "max_consecutive_technical_failures": 3, **batch},
        },
        base_dir=Path.cwd(),
    )


Behavior = Callable[[Runtime, TransactionItem, int], ProcessResult]


class Fake(RpaProcess):
    name = "fake"
    requires_browser = False

    def __init__(self, behaviors: dict[str, Behavior] | None = None) -> None:
        self.behaviors = behaviors or {}
        self.calls: dict[str, int] = {}
        self.recovers = 0
        self.ended = 0
        self.init_error: Exception | None = None
        self.end_error: Exception | None = None
        self.reconcile_verdicts: dict[str, ReconciliationVerdict] = {}
        self.reconciled: list[str] = []

    def init(self, rt: Runtime) -> None:
        if self.init_error:
            raise self.init_error

    def process(self, rt: Runtime, item: TransactionItem) -> ProcessResult:
        n = self.calls[item.reference] = self.calls.get(item.reference, 0) + 1
        b = self.behaviors.get(item.reference)
        if b is not None:
            return b(rt, item, n)
        return ProcessResult({"ok": item.reference})

    def recover(self, rt: Runtime) -> None:
        self.recovers += 1

    def reconcile(self, rt: Runtime, item: TransactionItem) -> Reconciliation:
        self.reconciled.append(item.reference)
        v = self.reconcile_verdicts.get(item.reference, ReconciliationVerdict.UNKNOWN)
        return Reconciliation(v, ProcessResult({"reconciliado": True}) if v is ReconciliationVerdict.DONE else None)

    def end(self, rt: Runtime) -> None:
        self.ended += 1
        if self.end_error:
            raise self.end_error


def items(*refs: str) -> InMemoryInputProvider:
    return InMemoryInputProvider([TransactionItem(r, {"cpf": SENT, "senha": SENT}) for r in refs])


def run(
    proc: Fake,
    provider: object,
    *,
    sink: object | None = None,
    run_dir: Path | None = None,
    cancel: CancelToken | None = None,
    checkpoint: CheckpointStore | None = None,
    **batch: int,
):
    events = MemoryEventSink()
    sink = sink or InMemoryResultSink()
    eng = Engine(
        proc,
        provider,
        sink,
        config(**batch),
        run_dir=run_dir,
        event_sinks=[events],
        cancel=cancel,  # type: ignore[arg-type]
        checkpoint=checkpoint,
    )
    summary = eng.run()
    return summary, events, sink


def statuses(summary) -> list[TransactionStatus]:  # type: ignore[no-untyped-def]
    return [t.status for t in summary.transactions]


def transient_until(ok_at: int) -> Behavior:
    def b(rt: Runtime, item: TransactionItem, n: int) -> ProcessResult:
        if n < ok_at:
            raise TransientTechnicalFailure(detail="servico_indisponivel")
        return ProcessResult({"ok": True})

    return b


def side_effect_then(exc: Exception) -> Behavior:
    def b(rt: Runtime, item: TransactionItem, n: int) -> ProcessResult:
        rt.ctx.mark_side_effect()
        raise exc

    return b


def rejected(rt: Runtime, item: TransactionItem, n: int) -> ProcessResult:
    raise BusinessRuleRejected("CLIENTE_INEXISTENTE")


# ------------------------------------------------------------------------------------------------ ciclo e lote
def test_ciclo_completo_e_eventos_de_fase():
    summary, events, sink = run(Fake(), items("a", "b"))
    assert summary.status is RunStatus.COMPLETED and statuses(summary) == [S.SUCCEEDED, S.SUCCEEDED]
    phases = [
        (e.event_code.value, e.phase.value if e.phase else None)
        for e in events.events
        if e.event_code.value.startswith("PHASE_")
    ]
    assert phases[0] == ("PHASE_STARTED", "INIT") and phases[-1] == ("PHASE_STARTED", "END")
    assert [p for _, p in phases].count("PROCESS") == 2 and [p for _, p in phases].count("TRANSFER_DATA_OUT") == 2
    assert len(sink.delivered) == 2


def test_entrada_unica():
    summary, _, _ = run(Fake(), SingleInputProvider(TransactionItem("unico")))
    assert statuses(summary) == [S.SUCCEEDED]


def test_lote_com_invalido_entre_validos_e_falha_transitoria_recuperada():
    proc = Fake({"b": rejected, "c": transient_until(2)})
    summary, events, sink = run(proc, items("a", "b", "c", "d"), max_transaction_attempts=2)
    assert statuses(summary) == [S.SUCCEEDED, S.BUSINESS_REJECTED, S.SUCCEEDED, S.SUCCEEDED]
    assert summary.status is RunStatus.COMPLETED
    assert proc.calls == {"a": 1, "b": 1, "c": 2, "d": 1} and proc.recovers == 1
    assert events.codes().count("TRANSACTION_RETRY_SCHEDULED") == 1
    assert sorted(o.status.value for o in sink.delivered.values()) == [
        "BUSINESS_REJECTED",
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
    ]


def test_negocio_nunca_e_repetido():
    proc = Fake({"a": rejected})
    run(proc, items("a"), max_transaction_attempts=3)
    assert proc.calls == {"a": 1}


def test_falha_depois_de_efeito_vira_outcome_unknown_e_nao_repete():
    proc = Fake({"a": side_effect_then(TransientTechnicalFailure())})
    summary, events, _ = run(proc, items("a", "b"), max_transaction_attempts=3)
    assert statuses(summary) == [S.OUTCOME_UNKNOWN, S.SUCCEEDED]
    assert proc.calls["a"] == 1
    assert "TRANSACTION_RETRY_DENIED" in events.codes() and summary.status is RunStatus.COMPLETED_WITH_FAILURES


def test_tentativas_de_transacao_esgotadas():
    proc = Fake({"a": transient_until(99)})
    summary, events, _ = run(proc, items("a"), max_transaction_attempts=3)
    assert statuses(summary) == [S.FAILED_TECHNICAL] and proc.calls["a"] == 3 and proc.recovers == 2
    assert summary.transactions[0].attempts == 3


def test_seguranca_para_o_lote_e_end_roda():
    proc = Fake({"b": lambda rt, it, n: (_ for _ in ()).throw(SecurityPolicyBlocked(detail="ORIGIN_NOT_ALLOWED"))})
    summary, _, _ = run(proc, items("a", "b", "c"))
    assert summary.status is RunStatus.STOPPED and summary.stop_code == "SECURITY_POLICY_BLOCKED"
    assert statuses(summary) == [S.SUCCEEDED, S.FAILED_TECHNICAL] and "c" not in proc.calls
    assert proc.ended == 1


def test_falhas_tecnicas_seguidas_param_o_lote():
    proc = Fake({r: transient_until(99) for r in "abcde"})
    summary, _, _ = run(proc, items(*"abcde"), max_consecutive_technical_failures=2)
    assert summary.status is RunStatus.STOPPED and summary.stop_detail == "consecutive_failures"
    assert len(summary.transactions) == 2 and "c" not in proc.calls


def test_sucesso_zera_a_sequencia_de_falhas():
    proc = Fake({"a": transient_until(99), "c": transient_until(99)})
    summary, _, _ = run(proc, items("a", "b", "c", "d"), max_consecutive_technical_failures=2)
    assert summary.status is RunStatus.COMPLETED_WITH_FAILURES and len(summary.transactions) == 4


def test_init_falha_end_roda_e_causa_original_preservada():
    proc = Fake()
    proc.init_error = InvalidConfiguration(detail="login_rejected")
    proc.end_error = RuntimeError("falha no END " + SENT)
    summary, events, _ = run(proc, items("a"))
    assert summary.status is RunStatus.INIT_FAILED and summary.stop_detail == "login_rejected"
    assert proc.ended == 1 and proc.calls == {} and summary.cleanup_ok is False
    assert "CLEANUP_FAILED" in events.codes()
    assert SENT not in json.dumps([e.to_dict() for e in events.events])


def test_erro_inesperado_do_processo_vira_codigo_estavel_sem_mensagem():
    proc = Fake({"a": lambda rt, it, n: {}[SENT]})  # KeyError com o valor sensível na mensagem
    summary, events, sink = run(proc, items("a"))
    t = summary.transactions[0]
    assert t.status is S.FAILED_TECHNICAL and t.error_code == "UNEXPECTED_ERROR"
    assert SENT not in json.dumps([e.to_dict() for e in events.events])
    assert [e.cause_type for e in events.events if e.event_code.value == "TRANSACTION_FAILED"] == ["KeyError"]


def test_entrada_indisponivel_para_o_lote():
    class Quebrado:
        def next_item(self):  # type: ignore[no-untyped-def]
            raise OSError("fila fora " + SENT)

    summary, events, _ = run(Fake(), Quebrado())
    assert summary.status is RunStatus.STOPPED and summary.stop_code == "INPUT_PROVIDER_FAILED"
    assert SENT not in json.dumps([e.to_dict() for e in events.events])


def test_referencia_duplicada_no_lote():
    class Dup:
        def __init__(self) -> None:
            self.n = 0

        def next_item(self):  # type: ignore[no-untyped-def]
            self.n += 1
            return TransactionItem("mesma") if self.n <= 2 else None

    summary, _, _ = run(Fake(), Dup())
    assert summary.stop_detail == "duplicate_reference" and len(summary.transactions) == 1


def test_cancelamento():
    cancel = CancelToken()

    def cancela(rt: Runtime, item: TransactionItem, n: int) -> ProcessResult:
        cancel.cancel()
        rt.ctx.cancel.raise_if_cancelled()
        return ProcessResult()

    proc = Fake({"b": cancela})
    summary, _, _ = run(proc, items("a", "b", "c"), cancel=cancel)
    assert summary.status is RunStatus.CANCELLED and statuses(summary) == [S.SUCCEEDED, S.CANCELLED]
    assert "c" not in proc.calls and proc.ended == 1


# ------------------------------------------------------------------------------------------------ destino
class SinkFalha:
    def __init__(self, exc: Exception, idempotent: bool = False) -> None:
        self.exc = exc
        self.idempotent = idempotent

    def deliver(self, item: TransactionItem, outcome: TransactionOutcome) -> None:
        raise self.exc


def test_destino_incerto_depois_de_efeito_vira_outcome_unknown():
    proc = Fake({"a": lambda rt, it, n: (rt.ctx.mark_side_effect(), ProcessResult())[1]})
    summary, events, _ = run(proc, items("a"), sink=SinkFalha(TimeoutError("rede")))
    t = summary.transactions[0]
    assert t.status is S.OUTCOME_UNKNOWN and t.detail == "SINK_UNCERTAIN" and t.delivery.value == "UNCERTAIN"
    assert "SINK_UNCERTAIN" in events.codes()


def test_destino_recusado_sem_efeito_e_reprocessavel():
    summary, _, _ = run(Fake(), items("a"), sink=SinkFalha(SinkRejected("cheio")))
    assert summary.transactions[0].status is S.FAILED_TECHNICAL


def test_destino_incerto_nao_idempotente_sem_efeito_ainda_e_desconhecido():
    summary, _, _ = run(Fake(), items("a"), sink=SinkFalha(OSError("disco")))
    assert summary.transactions[0].status is S.OUTCOME_UNKNOWN


def test_destino_incerto_idempotente_sem_efeito_e_reprocessavel():
    summary, _, _ = run(Fake(), items("a"), sink=SinkFalha(OSError("disco"), idempotent=True))
    assert summary.transactions[0].status is S.FAILED_TECHNICAL


# ------------------------------------------------------------------------------------------------ checkpoint e retomada
def crash_on(ref: str) -> Behavior:
    def b(rt: Runtime, item: TransactionItem, n: int) -> ProcessResult:
        rt.ctx.mark_side_effect()
        raise KeyboardInterrupt  # interrupção do processo no meio da transação

    return b


def test_retomada_nao_repete_confirmadas_e_nao_reprocessa_em_andamento(tmp_path: Path):
    p1 = Fake({"c": crash_on("c")})
    with pytest.raises(KeyboardInterrupt):
        run(p1, items("a", "b", "c", "d"), run_dir=tmp_path)
    assert p1.ended == 1  # END rodou mesmo na interrupção
    p2 = Fake()
    summary, events, _ = run(p2, items("a", "b", "c", "d"), run_dir=tmp_path)
    assert statuses(summary) == [S.SKIPPED, S.SKIPPED, S.OUTCOME_UNKNOWN, S.SUCCEEDED]
    assert p2.calls == {"d": 1} and p2.reconciled == ["c"]
    assert summary.transactions[2].detail == "INTERRUPTED_RUN"
    p3 = Fake()
    summary3, _, _ = run(p3, items("a", "b", "c", "d"), run_dir=tmp_path)
    assert statuses(summary3) == [S.SKIPPED] * 4 and p3.calls == {}
    assert summary3.transactions[2].detail == "NEEDS_REVIEW"


@pytest.mark.parametrize(
    ("verdict", "calls", "status"),
    [
        (ReconciliationVerdict.NOT_DONE, {"c": 1}, S.SUCCEEDED),
        (ReconciliationVerdict.DONE, {}, S.SUCCEEDED),
    ],
)
def test_reconciliacao_decide_a_retomada(tmp_path: Path, verdict, calls, status):  # type: ignore[no-untyped-def]
    with pytest.raises(KeyboardInterrupt):
        run(Fake({"c": crash_on("c")}), items("c"), run_dir=tmp_path)
    p2 = Fake()
    p2.reconcile_verdicts["c"] = verdict
    summary, _, sink = run(p2, items("c"), run_dir=tmp_path)
    assert p2.calls == calls and statuses(summary) == [status]
    assert len(sink.delivered) == 1


def test_falha_tecnica_sem_efeito_e_reprocessada_na_execucao_seguinte(tmp_path: Path):
    run(Fake({"a": transient_until(99)}), items("a", "b"), run_dir=tmp_path)
    p2 = Fake()
    summary, _, _ = run(p2, items("a", "b"), run_dir=tmp_path)
    assert p2.calls == {"a": 1} and statuses(summary) == [S.SUCCEEDED, S.SKIPPED]


def test_checkpoint_sem_dados_sensiveis_e_com_ids_pseudonimos(tmp_path: Path):
    refs = ["PEDIDO-" + SENT, "b"]
    run(
        Fake({refs[0]: rejected}),
        InMemoryInputProvider([TransactionItem(r, {"cpf": SENT}) for r in refs]),
        run_dir=tmp_path,
    )
    for f in tmp_path.iterdir():
        text = f.read_text(encoding="utf-8")
        assert SENT not in text and "PEDIDO" not in text and "123.456" not in text, f.name
    body = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))["body"]
    assert all(tx.startswith("tx-") and len(tx) == 23 for tx in body["transactions"])


def test_checkpoint_corrompido_bloqueia_sem_sobrescrever(tmp_path: Path):
    run(Fake(), items("a"), run_dir=tmp_path)
    cp = tmp_path / "checkpoint.json"
    text = cp.read_text(encoding="utf-8").replace('"SUCCEEDED"', '"FAILED_TECHNICAL"')
    cp.write_text(text, encoding="utf-8")
    proc = Fake()
    summary, _, _ = run(proc, items("a"), run_dir=tmp_path)
    assert summary.status is RunStatus.INIT_FAILED and summary.stop_code == "CHECKPOINT_CORRUPTED"
    assert proc.calls == {} and cp.read_text(encoding="utf-8") == text


def test_checkpoint_ilegivel(tmp_path: Path):
    (tmp_path / "checkpoint.json").write_text("{nao json", encoding="utf-8")
    summary, _, _ = run(Fake(), items("a"), run_dir=tmp_path)
    assert summary.stop_code == "CHECKPOINT_CORRUPTED" and summary.stop_detail == "unreadable"


def test_checkpoint_de_outro_processo(tmp_path: Path):
    other = CheckpointStore(tmp_path / "checkpoint.json", "outro")
    other.save()
    summary, _, _ = run(Fake(), items("a"), run_dir=tmp_path)
    assert summary.stop_detail == "other_process"


def test_falha_de_disco_no_checkpoint_para_antes_de_agir(tmp_path: Path):
    writes = []

    def writer(path: Path, text: str) -> None:
        writes.append(1)
        if len(writes) >= 3:  # 1: a em andamento, 2: a final, 3: b em andamento → falha
            raise OSError("disco cheio")
        path.write_text(text, encoding="utf-8")

    proc = Fake()
    cp = CheckpointStore(tmp_path / "checkpoint.json", "fake", writer=writer)
    summary, _, _ = run(proc, items("a", "b", "c"), run_dir=tmp_path, checkpoint=cp)
    assert summary.status is RunStatus.STOPPED and summary.stop_code == "CHECKPOINT_WRITE_FAILED"
    assert proc.calls == {"a": 1}  # b nunca começou: sem registro de "em andamento" não se age


def test_escrita_atomica_nao_deixa_temporarios(tmp_path: Path):
    run(Fake(), items("a", "b"), run_dir=tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["checkpoint.json", "events.jsonl", "summary.json"]


def test_transicoes_monotonicas():
    _check_transition(S.IN_PROGRESS, S.SUCCEEDED)
    for bad in [
        (S.SUCCEEDED, S.IN_PROGRESS),
        (S.OUTCOME_UNKNOWN, S.SUCCEEDED),
        (S.IN_PROGRESS, S.SKIPPED),
        (S.SUCCEEDED, S.FAILED_TECHNICAL),
    ]:
        with pytest.raises(AssertionError):
            _check_transition(*bad)


def test_resumo_persistido(tmp_path: Path):
    run(Fake({"b": rejected}), items("a", "b"), run_dir=tmp_path)
    s = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert s["status"] == "COMPLETED" and s["counts"] == {"SUCCEEDED": 1, "BUSINESS_REJECTED": 1}


# ------------------------------------------------------------------------------------------------ reconciliação na execução
def efeito_e_falha_na_primeira(rt: Runtime, item: TransactionItem, n: int) -> ProcessResult:
    if n == 1:
        rt.ctx.mark_side_effect()
        raise TransientTechnicalFailure(detail="comunicacao")
    return ProcessResult({"ok": True})


def test_desconhecido_reconciliado_como_feito_nao_repete():
    proc = Fake({"a": efeito_e_falha_na_primeira})
    proc.reconcile_verdicts["a"] = ReconciliationVerdict.DONE
    summary, events, sink = run(proc, items("a"), max_transaction_attempts=3)
    assert statuses(summary) == [S.SUCCEEDED] and proc.calls == {"a": 1} and proc.reconciled == ["a"]
    assert list(sink.delivered.values())[0].output == {"reconciliado": True}
    assert "RECONCILIATION_COMPLETED" in events.codes()


def test_desconhecido_reconciliado_como_nao_feito_e_tentado_de_novo_com_seguranca():
    proc = Fake({"a": efeito_e_falha_na_primeira})
    proc.reconcile_verdicts["a"] = ReconciliationVerdict.NOT_DONE
    summary, _, _ = run(proc, items("a"), max_transaction_attempts=2)
    assert statuses(summary) == [S.SUCCEEDED] and proc.calls == {"a": 2} and proc.recovers == 1


def test_desconhecido_reconciliado_como_nao_feito_sem_tentativas_fica_reprocessavel():
    proc = Fake({"a": efeito_e_falha_na_primeira})
    proc.reconcile_verdicts["a"] = ReconciliationVerdict.NOT_DONE
    summary, _, _ = run(proc, items("a"), max_transaction_attempts=1)
    t = summary.transactions[0]
    assert t.status is S.FAILED_TECHNICAL and t.error_code == "TRANSIENT_TECHNICAL_FAILURE"


def test_reconciliacao_que_falha_e_desconhecido():
    class Quebra(Fake):
        def reconcile(self, rt: Runtime, item: TransactionItem) -> Reconciliation:
            raise RuntimeError("tela fora " + SENT)

    proc = Quebra({"a": efeito_e_falha_na_primeira})
    summary, events, _ = run(proc, items("a"), max_transaction_attempts=3)
    assert statuses(summary) == [S.OUTCOME_UNKNOWN] and proc.calls == {"a": 1}
    assert SENT not in json.dumps([e.to_dict() for e in events.events])
