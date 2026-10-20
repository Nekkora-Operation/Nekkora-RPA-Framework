"""0.3.0 em navegador real — leitura semântica de texto NÃO interativo e saída XLSX, sobre o laboratório genérico
``/leitura/`` (pessoas fictícias): campo de busca RECRIADO ao receber foco, envio por Enter com confirmação pelo
endereço, células localizadas pelo cabeçalho da linha (nunca posição), listas exibidas como itens, ambiguidade e
ausência explícitas, e o ciclo INIT → TRANSFER_DATA_IN → PROCESS → TRANSFER_DATA_OUT → END gravando a planilha."""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest
from tests.conftest import Harness, lab_config

from nekkora_rpa import (
    BrowserSession,
    CheckpointStore,
    Engine,
    InMemoryInputProvider,
    MemoryEventSink,
    OutputStatus,
    ProcessResult,
    RpaProcess,
    RunStatus,
    Runtime,
    SelectorRegistry,
    TransactionItem,
)
from nekkora_rpa.errors import BusinessRuleRejected, InvalidArgument, NekkoraRpaError, TargetAmbiguous
from nekkora_rpa.text import join_items, parse_long_date, same_address
from nekkora_rpa.xlsx import ColumnKind, OutputColumn, XlsxResultSink, XlsxSchema, read_back

pytestmark = pytest.mark.browser


def linha(cabecalho: str) -> dict[str, object]:
    # célula da linha cujo cabeçalho é o texto exato (relação semântica th → td, nunca posição)
    return {
        "preferred": {"strategy": "xpath", "expression": f"//tr[th[normalize-space()='{cabecalho}']]/td"},
        "expected": {"tag": "td"},
    }


REG = {
    "schema": "nekkora-rpa/selectors",
    "version": "1.1.0",
    "system": "acervo",
    "targets": {
        "acervo.busca.campo": {
            "preferred": {"strategy": "css", "expression": 'form#buscaform input[name="q"]'},
            "expected": {"tag": "input", "type": "search"},
        },
        "acervo.busca.fixa": {
            "preferred": {"strategy": "css", "expression": 'form#busca-fixa input[name="q"]'},
            "expected": {"tag": "input"},
        },
        "acervo.ficha.titulo": {"preferred": {"strategy": "id", "value": "titulo"}, "expected": {"tag": "h1"}},
        "acervo.ficha.nome_completo": linha("Nome completo"),
        "acervo.ficha.nascimento": linha("Nascimento"),
        "acervo.ficha.morte": linha("Morte"),
        "acervo.ficha.nacionalidade": linha("Nacionalidade"),
        "acervo.ficha.ocupacao": linha("Ocupação"),
        "acervo.ficha.campos": linha("Campo(s)"),
    },
}
SENT = "Ana Maria Exemplo da Silva"


@pytest.fixture
def acervo(clean_lab):  # type: ignore[no-untyped-def]
    h = Harness(clean_lab, SelectorRegistry.from_text(json.dumps(REG), environment="lab"))
    yield h
    h.close()


def buscar(h: Harness, termo: str, destino: str) -> None:
    a = h.actions
    a.click("acervo.busca.campo", idempotent=True, step_id="BUSCA-01")  # o foco RECRIA o campo (nó novo, sem id)
    a.fill("acervo.busca.campo", termo, step_id="BUSCA-02")  # resolvido de novo: acha o campo recriado
    a.press(
        "acervo.busca.campo",
        "Enter",
        idempotent=True,
        step_id="BUSCA-03",
        postcondition=lambda: same_address(a.current_address(), h.lab.url + destino),
    )


def test_busca_recriada_enter_e_leitura_por_cabecalho(acervo: Harness) -> None:
    a = acervo.actions
    a.navigate("/leitura/busca.html")
    assert acervo.page.evaluate("() => !!document.getElementById('campo-busca')")
    buscar(acervo, "Ana Exemplo", "/leitura/ficha-ana.html")
    assert same_address(a.current_address(), acervo.lab.url + "/leitura/ficha-ana.html")
    assert a.read_text("acervo.ficha.titulo") == "Ana Exemplo"
    assert a.read_items("acervo.ficha.nome_completo") == (SENT,)
    assert parse_long_date(" ".join(a.read_items("acervo.ficha.nascimento"))) == "1839-06-21"
    assert parse_long_date(" ".join(a.read_items("acervo.ficha.morte"))) == "1908-09-29"
    assert a.read_items("acervo.ficha.ocupacao") == ("escritora", "jornalista", "tradutora")
    assert a.read_items("acervo.ficha.nacionalidade") == ("brasileira",)
    assert not a.exists("acervo.ficha.campos")
    codes = acervo.codes()
    assert {"press", "read_items", "current_address"} <= {e.action for e in acervo.events.events if e.action}
    assert SENT not in json.dumps([e.to_dict() for e in acervo.events.events])  # nada lido vai para os eventos
    assert "ACTION_FAILED" not in codes


def test_campo_recriado_ao_focar_perde_o_id(acervo: Harness) -> None:
    # sem a âncora contextual (form#buscaform), o nó original some: o seletor por id deixa de existir
    acervo.actions.navigate("/leitura/busca.html")
    acervo.actions.click("acervo.busca.campo", idempotent=True)
    assert acervo.page.evaluate("() => document.getElementById('campo-busca') === null")
    assert acervo.page.evaluate("() => document.querySelectorAll('input[name=q]').length") == 2  # duplicata oculta


def test_ausencia_lista_ambiguidade_e_data_incompleta(acervo: Harness) -> None:
    a = acervo.actions
    a.navigate("/leitura/ficha-bruno.html")
    assert not a.exists("acervo.ficha.nome_completo")  # campo ausente: nada é presumido
    assert not a.exists("acervo.ficha.morte")
    assert a.read_items("acervo.ficha.nacionalidade") == (
        "ucraniana",
        "brasileira (naturalizada em 12 de janeiro de 1943)",
    )
    assert join_items(a.read_items("acervo.ficha.campos")) == "física, química"
    assert parse_long_date(" ".join(a.read_items("acervo.ficha.nascimento"))) == "1990-05-01"
    a.navigate("/leitura/ficha-carla.html")
    with pytest.raises(TargetAmbiguous):
        a.read_items("acervo.ficha.nome_completo", timeout_ms=1500)  # dois cabeçalhos iguais: nunca o "primeiro"
    assert parse_long_date(" ".join(a.read_items("acervo.ficha.nascimento"))) is None  # sem dia: não completa


def test_tecla_em_alvo_oculto_nao_e_despachada_e_tecla_fora_da_lista(acervo: Harness) -> None:
    a = acervo.actions
    a.navigate("/leitura/busca.html")
    with pytest.raises(NekkoraRpaError) as e:
        a.press("acervo.busca.fixa", "Enter", timeout_ms=1200)
    assert e.value.code.value in ("TARGET_NOT_READY", "TARGET_NOT_FOUND", "ACTION_TIMEOUT")
    assert same_address(a.current_address(), acervo.lab.url + "/leitura/busca.html")  # nada aconteceu
    with pytest.raises(InvalidArgument):
        a.press("acervo.busca.campo", "Control+A")


# --------------------------------------------------------------------------------------------- ciclo completo
COLUNAS = XlsxSchema(
    (
        OutputColumn("URL", "url", ColumnKind.URL),
        OutputColumn("Nome completo", "nome_completo"),
        OutputColumn("Nascimento", "nascimento", ColumnKind.ISO_DATE, required=False),
        OutputColumn("Ocupação", "ocupacao", required=False),
    ),
    key_field="url",
    sheet="Fichas",
)


class Fichas(RpaProcess):
    """Processo genérico: pesquisa cada termo, confere o endereço, lê os campos (com fonte alternativa declarada)."""

    name = "fichas"

    def process(self, rt: Runtime, item: TransactionItem) -> ProcessResult:
        a = rt.act
        termo, esperado = str(item.data["termo"]), str(item.data["endereco"])
        a.navigate("/leitura/busca.html", step_id="INI-01")
        a.click("acervo.busca.campo", idempotent=True, step_id="PES-01")
        a.fill("acervo.busca.campo", termo, step_id="PES-02")
        a.press(
            "acervo.busca.campo",
            "Enter",
            idempotent=True,
            step_id="PES-03",
            postcondition=lambda: a.current_address().split("?")[0] != rt.ctx.config.base_url + "/leitura/busca.html",
        )
        endereco = a.current_address(step_id="EXT-00")
        if not same_address(endereco, esperado):
            raise BusinessRuleRejected("ENDERECO_DIFERENTE")
        nome = (
            join_items(a.read_items("acervo.ficha.nome_completo", step_id="EXT-01"))
            if a.exists("acervo.ficha.nome_completo")
            else a.read_text("acervo.ficha.titulo", step_id="EXT-02")
        )
        nasc = parse_long_date(" ".join(a.read_items("acervo.ficha.nascimento", step_id="EXT-03"))) or ""
        ocup = (
            join_items(a.read_items("acervo.ficha.ocupacao", step_id="EXT-04"))
            if a.exists("acervo.ficha.ocupacao")
            else ""
        )
        return ProcessResult({"url": endereco, "nome_completo": nome, "nascimento": nasc, "ocupacao": ocup})


def correr(clean_lab, tmp_path: Path, pares: list[tuple[str, str]]):  # type: ignore[no-untyped-def]
    cfg = lab_config(clean_lab.url)
    events = MemoryEventSink()
    (tmp_path / "saida").mkdir(exist_ok=True)
    sink = XlsxResultSink(
        tmp_path / "saida" / "fichas.xlsx", COLUNAS, state_dir=tmp_path / "run", expected_rows=len(pares)
    )
    items = [TransactionItem(e, {"termo": t, "endereco": clean_lab.url + e}) for t, e in pares]
    eng = Engine(
        Fichas(),
        InMemoryInputProvider(items),
        sink,
        cfg,
        registry=SelectorRegistry.from_text(json.dumps(REG), environment="lab"),
        run_dir=tmp_path / "run",
        event_sinks=[events],
        checkpoint=CheckpointStore(tmp_path / "run" / "checkpoint.json", "fichas"),
    )
    return eng.run(), events


def test_ciclo_completo_grava_planilha_conferida(clean_lab, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    pares = [
        ("Ana Exemplo", "/leitura/ficha-ana.html"),
        ("Bruno Modelo", "/leitura/ficha-bruno.html"),
        ("Davi Amostra", "/leitura/ficha-davi.html"),
        ("Eva Formula", "/leitura/ficha-eva.html"),
    ]
    summary, events = correr(clean_lab, tmp_path, pares)
    assert summary.status is RunStatus.COMPLETED, summary.to_dict()
    assert summary.output is not None and summary.output.status is OutputStatus.COMMITTED
    rows = read_back(tmp_path / "saida" / "fichas.xlsx", COLUNAS)
    assert rows == [
        (clean_lab.url + "/leitura/ficha-ana.html", SENT, "1839-06-21", "escritora; jornalista; tradutora"),
        (clean_lab.url + "/leitura/ficha-bruno.html", "Bruno Modelo", "1990-05-01", ""),  # sem "Nome completo": título
        (clean_lab.url + "/leitura/ficha-davi.html", "Davi Ãçêntuado Ünicode 日本 😀", "2001-03-02", ""),
        (clean_lab.url + "/leitura/ficha-eva.html", '=HYPERLINK("http://exemplo.invalid","x")', "1950-05-05", ""),
    ]
    ws = openpyxl.load_workbook(tmp_path / "saida" / "fichas.xlsx")["Fichas"]
    assert ws["B5"].data_type == "s"  # texto lido que parece fórmula continua TEXTO
    phases = [e.phase for e in events.events if e.event_code.value == "PHASE_STARTED"]
    assert phases[0] == "INIT" and phases[-1] == "END" and phases[-2] == "TRANSFER_DATA_OUT"
    assert "TRANSFER_DATA_IN" in phases and "PROCESS" in phases
    dump = json.dumps([e.to_dict() for e in events.events]) + (tmp_path / "run" / "summary.json").read_text("utf-8")
    assert SENT not in dump and "HYPERLINK" not in dump


def test_artigo_errado_e_rejeitado_e_planilha_retida(clean_lab, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    pares = [("Ana Exemplo", "/leitura/ficha-ana.html"), ("Inexistente", "/leitura/ficha-bruno.html")]
    summary, _ = correr(clean_lab, tmp_path, pares)
    assert [t.status.value for t in summary.transactions] == ["SUCCEEDED", "BUSINESS_REJECTED"]
    assert summary.output is not None and summary.output.status is OutputStatus.WITHHELD
    assert not (tmp_path / "saida" / "fichas.xlsx").exists()


def test_sessao_fecha_no_end(clean_lab) -> None:  # type: ignore[no-untyped-def]
    s = BrowserSession(
        lab_config(clean_lab.url).browser, lab_config(clean_lab.url).origins, lab_config(clean_lab.url).timeouts
    )
    s.start()
    assert s.close()
