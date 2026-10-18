"""FRAMEWORK-002 em navegador real: identidade por rótulo visível (campos que mudam de posição e de id), download
validado e leitura do XLSX baixado."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lab.server import DESAFIO
from tests.conftest import FIXTURES, Harness

from nekkora_rpa import SelectorRegistry
from nekkora_rpa.errors import (
    ActionTimeout,
    DownloadInvalid,
    InvalidConfiguration,
    SecurityPolicyBlocked,
    TargetAmbiguous,
    TargetIdentityMismatch,
    TargetNotFound,
)
from nekkora_rpa.tabular import Column, TabularSchema, read_xlsx

pytestmark = pytest.mark.browser

LABELS = ["First Name", "Last Name", "Company Name", "Role in Company", "Address", "Email", "Phone Number"]
SCHEMA = TabularSchema(tuple(Column(h, integer_as_text=(h == "Phone Number")) for h in LABELS))
XLSX_MAGIC = b"PK\x03\x04"

DOWNLOADS = {
    "schema": "nekkora-rpa/selectors",
    "version": "1.1.0",
    "system": "dl",
    "targets": {
        f"dl.{n}": {"preferred": {"strategy": "id", "value": f"dl-{n}"}, "expected": {"tag": "a"}}
        for n in ("valido", "grande", "texto", "externo", "falha", "nada")
    },
}


def key(label: str) -> str:
    return "desafio.form." + label.lower().replace(" ", "_")


@pytest.fixture
def desafio(clean_lab):  # type: ignore[no-untyped-def]
    reg = SelectorRegistry.load(FIXTURES / "desafio-selectors.json", environment="lab")
    h = Harness(clean_lab, reg, browser={"accept_downloads": True})
    yield h
    h.close()


@pytest.fixture
def downloads(clean_lab):  # type: ignore[no-untyped-def]
    reg = SelectorRegistry.from_text(json.dumps(DOWNLOADS), environment="lab")
    h = Harness(clean_lab, reg, browser={"accept_downloads": True})
    h.actions.navigate("/adversarial/downloads.html")
    yield h
    h.close()


def ids(h: Harness) -> list[str]:
    return list(h.page.evaluate("() => [...document.querySelectorAll('#campos input')].map(i => i.id)"))


def test_campos_por_rotulo_em_rodadas_com_posicao_e_id_novos(desafio):  # type: ignore[no-untyped-def]
    desafio.actions.navigate("/desafio/index.html")
    antes = desafio.actions.mark(key("First Name"))
    desafio.actions.click(
        "desafio.inicio.start", idempotent=True, postcondition=lambda: desafio.actions.replaced(antes)
    )
    previous: list[str] = []
    for rodada in range(10):
        desafio.actions.wait_visible(key("First Name"))
        current = ids(desafio)
        assert set(current).isdisjoint(previous)
        previous = current
        for label in LABELS:
            desafio.actions.fill(key(label), DESAFIO[rodada][label], step_id=f"R{rodada + 1}-{LABELS.index(label) + 1}")
        marca = desafio.actions.mark(key("First Name"))
        # o envio não é idempotente: só é dado por concluído quando o formulário foi de fato substituído
        desafio.actions.click(
            "desafio.form.enviar",
            step_id=f"R{rodada + 1}-S",
            postcondition=lambda m=marca: (
                desafio.actions.replaced(m) or desafio.actions.is_visible("desafio.fim.resultado")
            ),
        )
    desafio.actions.wait_visible("desafio.fim.resultado")
    texto = desafio.actions.read_text("desafio.fim.resultado")
    assert "100%" in texto and "70 out of 70" in texto
    o = desafio.lab.oracle()
    assert o["desafio_inicios"] == 1 and len(o["desafio_submissoes"]) == 10
    for i, sub in enumerate(o["desafio_submissoes"]):
        assert sub["rodada"] == i + 1 and sub["valores"] == DESAFIO[i]


def test_rotulo_duplicado_e_ambiguo(desafio):  # type: ignore[no-untyped-def]
    desafio.actions.navigate("/desafio/index.html?v=sosia")
    with pytest.raises(TargetAmbiguous):
        desafio.actions.fill(key("Email"), "x")
    assert all(
        v == ""
        for v in desafio.page.evaluate("() => [...document.querySelectorAll('#campos input')].map(i => i.value)")
    )


def test_rotulo_irmao_nao_identifica_campo_que_divide_o_conteiner(clean_lab):  # type: ignore[no-untyped-def]
    # E2E-001 (mutação M18): o <label> irmão só é a identidade do ÚNICO campo do contêiner; achado por outra estratégia,
    # um campo que divide o contêiner com outro não "herda" o rótulo (controle positivo: contêiner com um campo só)
    alvo = {"tag": "input", "label": "Email"}
    reg = SelectorRegistry.from_text(
        json.dumps(
            {
                "schema": "nekkora-rpa/selectors",
                "version": "1.1.0",
                "system": "x",
                "targets": {
                    "x.dividido": {"preferred": {"strategy": "id", "value": "k2"}, "expected": alvo},
                    "x.unico": {"preferred": {"strategy": "id", "value": "k3"}, "expected": alvo},
                },
            }
        ),
        environment="lab",
    )
    h = Harness(clean_lab, reg)
    try:
        h.actions.navigate("/desafio/index.html")
        h.page.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
            '<div><label>Email</label><input id="k1"><input id="k2"></div><div><label>Email</label><input id="k3"></div>')""")
        h.actions.fill("x.unico", "ok")
        with pytest.raises(TargetIdentityMismatch):
            h.actions.fill("x.dividido", "x")
        assert h.page.evaluate("() => document.getElementById('k2').value") == ""
    finally:
        h.close()


def test_rotulo_alterado_entre_rodadas_nao_e_encontrado(desafio):  # type: ignore[no-untyped-def]
    a = desafio.actions
    a.navigate("/desafio/index.html?v=trocado")
    m = a.mark(key("Email"))
    a.click("desafio.inicio.start", idempotent=True, postcondition=lambda: a.replaced(m))
    for _ in range(3):
        m = a.mark(key("Email"))
        a.click("desafio.form.enviar", postcondition=lambda m=m: a.replaced(m))
    with pytest.raises(TargetNotFound):
        desafio.actions.fill(key("Email"), "x", timeout_ms=600)


def test_download_valido_e_leitura_do_xlsx(desafio, tmp_path: Path):  # type: ignore[no-untyped-def]
    desafio.actions.navigate("/desafio/index.html")
    f = desafio.actions.download(
        "desafio.inicio.baixar", dest_dir=tmp_path, file_name="entrada.xlsx", magic=XLSX_MAGIC, step_id="G1-01"
    )
    assert f.path == tmp_path / "entrada.xlsx" and f.size_bytes > 1000 and len(f.sha256) == 64
    data = read_xlsx(f.path, SCHEMA)
    assert data.source_sha256 == f.sha256 and len(data.rows) == 10
    assert [dict(r.values) for r in data.rows] == DESAFIO  # inclui o cabeçalho com espaço ("Last Name ")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["entrada.xlsx"]
    with pytest.raises(DownloadInvalid) as e:
        desafio.actions.download("desafio.inicio.baixar", dest_dir=tmp_path, file_name="entrada.xlsx")
    assert e.value.detail == "exists"


@pytest.mark.parametrize(
    ("link", "error", "detail"),
    [
        ("dl.grande", DownloadInvalid, "size"),
        ("dl.texto", DownloadInvalid, "signature"),
        ("dl.falha", DownloadInvalid, None),
    ],
)
def test_downloads_recusados_sem_deixar_arquivo(downloads, tmp_path: Path, link, error, detail):  # type: ignore[no-untyped-def]
    with pytest.raises(error) as e:
        downloads.actions.download(link, dest_dir=tmp_path, file_name="x.xlsx", magic=XLSX_MAGIC, max_bytes=1_000_000)
    if detail:
        assert e.value.detail == detail
    assert list(tmp_path.iterdir()) == []


def test_download_redirecionado_para_outra_origem(downloads, tmp_path: Path):  # type: ignore[no-untyped-def]
    with pytest.raises((SecurityPolicyBlocked, ActionTimeout, DownloadInvalid)):
        downloads.actions.download("dl.externo", dest_dir=tmp_path, file_name="x.xlsx", timeout_ms=3_000)
    assert downloads.lab.oracle()["external_hits"] == 0 and list(tmp_path.iterdir()) == []


def test_download_de_outra_origem_recusado_mesmo_se_a_rede_falhar(downloads, tmp_path: Path):  # type: ignore[no-untyped-def]
    # 2ª barreira (E2E-001, mutação M15): simula a guarda de rede FALHANDO (rota removida) e a outra origem servindo um
    # anexo XLSX; o download precisa ser recusado pela origem do próprio arquivo, sem deixar nada na pasta
    ctx = downloads.session._context
    ctx.unroute("**/*")
    externo = downloads.lab.external_url

    def falha_da_rede(route):  # type: ignore[no-untyped-def]
        if route.request.url.startswith(externo):
            route.fulfill(
                status=200,
                body=XLSX_MAGIC + b"\0" * 64,
                headers={"Content-Type": "application/octet-stream", "Content-Disposition": "attachment"},
            )
        else:
            route.continue_()

    ctx.route("**/*", falha_da_rede)
    # link DIRETO para a outra origem (a rota não vê saltos de redirecionamento)
    downloads.page.evaluate("u => document.getElementById('dl-externo').href = u", externo + "/planilha.xlsx")
    with pytest.raises(SecurityPolicyBlocked) as e:
        downloads.actions.download(
            "dl.externo", dest_dir=tmp_path, file_name="x.xlsx", magic=XLSX_MAGIC, timeout_ms=5_000
        )
    assert e.value.detail == "DOWNLOAD_ORIGIN" and list(tmp_path.iterdir()) == []


def test_clique_sem_download(downloads, tmp_path: Path):  # type: ignore[no-untyped-def]
    with pytest.raises(ActionTimeout) as e:
        downloads.actions.download("dl.nada", dest_dir=tmp_path, file_name="x.xlsx", timeout_ms=1_500)
    assert e.value.detail == "no_download"


@pytest.mark.parametrize(
    ("name", "detail"), [("../fora.xlsx", "file_name"), ("x.exe", "file_name"), ("com espaco.xlsx", "file_name")]
)
def test_nome_de_destino_invalido(downloads, tmp_path: Path, name, detail):  # type: ignore[no-untyped-def]
    from nekkora_rpa.errors import InvalidArgument

    with pytest.raises(InvalidArgument) as e:
        downloads.actions.download("dl.valido", dest_dir=tmp_path, file_name=name)
    assert e.value.detail == detail


def test_download_desabilitado_por_padrao(clean_lab, tmp_path: Path):  # type: ignore[no-untyped-def]
    reg = SelectorRegistry.from_text(json.dumps(DOWNLOADS), environment="lab")
    h = Harness(clean_lab, reg)
    try:
        h.actions.navigate("/adversarial/downloads.html")
        with pytest.raises(InvalidConfiguration) as e:
            h.actions.download("dl.valido", dest_dir=tmp_path, file_name="x.xlsx")
        assert e.value.detail == "downloads_disabled"
    finally:
        h.close()


def test_ler_texto_por_padrao_ancorado(desafio):  # type: ignore[no-untyped-def]
    a = desafio.actions
    a.navigate("/desafio/index.html")
    m = a.mark(key("First Name"))
    a.click("desafio.inicio.start", idempotent=True, postcondition=lambda: a.replaced(m))
    for rodada in range(10):
        for label in LABELS:
            a.fill(key(label), DESAFIO[rodada][label])
        m = a.mark(key("First Name"))
        a.click("desafio.form.enviar", postcondition=lambda m=m: a.replaced(m))
    padrao = r"^Your success rate is \d+% \( \d+ out of \d+ fields\) in \d+ milliseconds$"
    texto = a.read_text_matching(padrao, step_id="FIM-01")
    assert "100%" in texto and "70 out of 70" in texto
    assert texto not in json.dumps([e.to_dict() for e in desafio.events.events])


def test_padrao_de_texto_invalido_ausente_e_ambiguo(desafio):  # type: ignore[no-untyped-def]
    from nekkora_rpa.errors import InvalidArgument

    a = desafio.actions
    a.navigate("/desafio/index.html")
    for bad in ("sem ancora", "^aberto", "^(" + "x" * 400 + ")$", "^[$"):
        with pytest.raises(InvalidArgument):
            a.read_text_matching(bad)
    with pytest.raises(TargetNotFound):
        a.read_text_matching(r"^Nao existe nesta pagina$", timeout_ms=500)
    with pytest.raises(TargetAmbiguous):
        a.read_text_matching(r"^(First|Last) Name$", timeout_ms=500)
