"""F7 — logs e privacidade em navegador real: sentinelas deliberadas em entradas, segredos, seletores, DOM, URL e
exceções do Playwright não podem aparecer em NENHUM artefato persistido nem na saída."""

from __future__ import annotations

import io
import json
import traceback
from pathlib import Path

import pytest

from nekkora_rpa import (
    ConsoleEventSink,
    Engine,
    InMemoryInputProvider,
    ProcessResult,
    RpaProcess,
    Runtime,
    Secret,
    SelectorRegistry,
    TransactionItem,
)
from nekkora_rpa.data import JsonDirectoryResultSink
from nekkora_rpa.errors import NekkoraRpaError

pytestmark = pytest.mark.browser

CPF = "123.456.789-09"
SENHA = "Senha-SENTINELA-77"
SEL = "SENTINELA-SELETOR"
DOM = "Aurora Ficticia"
QUERY = "SENTINELA-QUERY"

REGISTRO = {
    "schema": "nekkora-rpa/selectors",
    "version": "1.0.0",
    "system": "priv",
    "targets": {
        "priv.campo": {
            "preferred": {"strategy": "css", "expression": f"#campo-texto:not([data-x='{SEL}'])"},
            "expected": {"tag": "input", "role": "textbox", "name": "Nome"},
        },
        "priv.senha": {
            "preferred": {"strategy": "css", "expression": f"#campo-senha:not(.{SEL})"},
            "expected": {"tag": "input", "type": "password"},
        },
        "priv.ambiguo": {
            "preferred": {"strategy": "css", "expression": f"[data-testid=duplicado]:not(.{SEL})"},
            "expected": {"tag": "button"},
        },
        "priv.titulo": {
            "preferred": {"strategy": "css", "expression": f"#titulo-adv:not(.{SEL})"},
            "expected": {"tag": "h1"},
        },
        "priv.inexistente": {"preferred": {"strategy": "css", "expression": f"#{SEL}"}, "expected": {"tag": "button"}},
    },
}
FORBIDDEN = [CPF, SENHA, SEL, DOM, QUERY, "SENTINELA"]


class Ataque(RpaProcess):
    name = "privacidade"
    tracebacks: list[str]

    def __init__(self, base: str) -> None:
        self.base = base
        self.tracebacks = []

    def process(self, rt: Runtime, item: TransactionItem) -> ProcessResult:
        act = rt.act
        act.navigate(f"/adversarial/resolver.html?cpf={CPF}&q={QUERY}", step_id="P-01")
        act.fill("priv.campo", str(item.data["cpf"]), step_id="P-02")
        act.fill("priv.senha", item.data["senha"], step_id="P-03")  # type: ignore[arg-type]
        act.page.evaluate(f"() => document.getElementById('titulo-adv').textContent = '{DOM} {CPF}'")
        texto = act.read_text("priv.titulo", step_id="P-04")
        assert CPF in texto  # o processo recebe o valor; o log não
        for key in ("priv.ambiguo", "priv.inexistente"):
            try:
                act.click(key, step_id="P-05", timeout_ms=500)
            except NekkoraRpaError as err:
                self.tracebacks.append("".join(traceback.format_exception(err)))
                self.tracebacks.append(str(err) + repr(err))
        if item.reference.endswith("2"):
            raise RuntimeError(f"falha do processo com {CPF} e {SENHA}")
        return ProcessResult({"ok": True})


def test_nenhum_valor_sensivel_em_artefatos(clean_lab, tmp_path: Path):  # type: ignore[no-untyped-def]
    from tests.conftest import lab_config

    registry = SelectorRegistry.from_text(json.dumps(REGISTRO), environment="lab")
    console = io.StringIO()
    proc = Ataque(clean_lab.url)
    items = [TransactionItem(f"{CPF}-{n}", {"cpf": CPF, "senha": Secret("senha", SENHA)}) for n in (1, 2)]
    engine = Engine(
        proc,
        InMemoryInputProvider(items),
        JsonDirectoryResultSink(tmp_path / "resultados"),
        lab_config(clean_lab.url),
        registry=registry,
        run_dir=tmp_path / "run",
        event_sinks=[ConsoleEventSink(console)],
    )
    summary = engine.run()
    assert [t.status.value for t in summary.transactions] == ["SUCCEEDED", "FAILED_TECHNICAL"]
    assert len(proc.tracebacks) == 8
    texts = {"console": console.getvalue(), **{f"tb{i}": t for i, t in enumerate(proc.tracebacks)}}
    for f in (tmp_path / "run").iterdir():
        texts[f.name] = f.read_text(encoding="utf-8")
    for f in (tmp_path / "resultados").iterdir():
        texts[f.name] = f.read_text(encoding="utf-8")
    for name, text in texts.items():
        for s in FORBIDDEN:
            assert s not in text, (name, s)
    events = [json.loads(line) for line in texts["events.jsonl"].splitlines()]
    assert {e["event_code"] for e in events} >= {"TARGET_REJECTED", "ACTION_FAILED", "TRANSACTION_FAILED"}
    # sem capturas de tela: o framework não produz imagem alguma
    assert not [p for p in tmp_path.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
