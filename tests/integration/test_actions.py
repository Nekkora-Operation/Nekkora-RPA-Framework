"""F3 — Libs e adapter Playwright: click/double_click/fill/wait/navigate/read_text em navegador real."""

from __future__ import annotations

import threading

import pytest

from nekkora_rpa import Secret
from nekkora_rpa.adapters.playwright import interactions
from nekkora_rpa.adapters.playwright.resolver import Resolver
from nekkora_rpa.errors import (
    ActionTimeout,
    Cancelled,
    ErrorCode,
    InvalidArgument,
    NavigationFailed,
    NekkoraRpaError,
    OutcomeUnknown,
    PageClosed,
    SecurityPolicyBlocked,
    TargetNotReady,
    TransientTechnicalFailure,
)
from nekkora_rpa.resilience.retry import RetryPolicy
from nekkora_rpa.resilience.timing import Deadline

pytestmark = pytest.mark.browser


def _retry(h, attempts: int = 3) -> None:  # type: ignore[no-untyped-def]
    h.actions.retry = RetryPolicy(max_attempts=attempts, initial_backoff_ms=50, max_backoff_ms=100)


# ------------------------------------------------------------------------------------------------ click
def test_clique_simples_produz_um_clique(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.click("adv.contador", step_id="C-01", idempotent=True)
    assert harness.lab_counter("cliques") == 1 and harness.lab_counter("duplos") == 0
    assert harness.actions.read_text("adv.cliques") == "1"


@pytest.mark.parametrize("via", ["double_click", "click_count"])
def test_duplo_clique_e_um_dblclick_efetivo(harness, via):  # type: ignore[no-untyped-def]
    harness.open_adv()
    if via == "double_click":
        harness.actions.double_click("adv.contador", idempotent=True)
    else:
        harness.actions.click("adv.contador", click_count=2, idempotent=True)
    assert harness.lab_counter("duplos") == 1
    # o navegador entrega 2 eventos click dentro de um dblclick; o que importa é UM dblclick, não dois cliques soltos
    assert harness.lab_counter("cliques") == 2
    assert [e.action for e in harness.events.events if e.event_code == "ACTION_COMPLETED"][-1] == "double_click"


def test_desabilitado_que_habilita_no_prazo_e_clicado(harness):  # type: ignore[no-untyped-def]
    harness.open_adv("?habilita=600")
    harness.actions.click("adv.habilita", timeout_ms=3_000, idempotent=True)
    assert harness.lab_counter("habilita") == 1


def test_desabilitado_ate_o_fim_vira_target_not_ready_sem_clique(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetNotReady) as e:
        harness.actions.click("adv.sempre_desab", timeout_ms=800)
    assert e.value.detail == "disabled"


def test_coberto_ate_o_fim_nao_e_clicado(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetNotReady) as e:
        harness.actions.click("adv.coberto", timeout_ms=800)
    assert e.value.detail == "not_actionable"
    assert harness.lab_counter("coberto") == 0


def test_coberto_por_instantes_e_clicado_quando_livre(harness):  # type: ignore[no-untyped-def]
    harness.open_adv("?capa=500")
    harness.actions.click("adv.coberto_temp", timeout_ms=3_000, idempotent=True)
    assert harness.lab_counter("cobertoTemp") == 1


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"mode": "dom_event"}, "mode"),
        ({"mode": "os_mouse"}, "mode"),
        ({"click_count": 3}, "click_count"),
        ({"click_count": True}, "click_count"),
        ({"timeout_ms": 0}, "timeout_ms"),
        ({"timeout_ms": -5}, "timeout_ms"),
        ({"timeout_ms": 10**9}, "timeout_ms"),
        ({"step_id": "passo com espaço"}, "step_id"),
        ({"step_id": "http://x/?cpf=1"}, "step_id"),
        ({"postcondition": "sim"}, "postcondition"),
    ],
)
def test_parametros_invalidos_nao_fazem_nada(harness, kwargs, detail):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(InvalidArgument) as e:
        harness.actions.click("adv.salvar", **kwargs)
    assert e.value.detail == detail
    assert harness.lab_counter("salvar") == 0


def test_pagina_fechada(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.page.close()
    with pytest.raises(PageClosed):
        harness.actions.click("adv.salvar")


def test_no_desconectado_entre_verificacao_e_acao_e_target_detached(harness):  # type: ignore[no-untyped-def]
    """A ação age sobre o nó VERIFICADO; se ele sai do DOM, o erro é TARGET_DETACHED (nunca clicar no substituto)."""
    harness.open_adv()
    page = harness.page
    target = harness.actions.registry.get("adv.salvar")
    res = Resolver(harness.ctx.clock, harness.ctx.cancel).resolve(
        page, target, Deadline.after_ms(2_000, harness.ctx.clock)
    )
    assert res is not None
    page.evaluate(
        """() => { const old = document.getElementById('salvar'); const b = old.cloneNode(true);
        b.addEventListener('click', () => window.__lab.salvar += 100); old.replaceWith(b); }"""
    )
    try:
        interactions.click(res.handle, click_count=1, timeout_ms=1_000, trial=True)
        pytest.fail("trial deveria falhar num nó desconectado")
    except Exception as exc:
        err = interactions.not_performed(page, res.handle, exc, "adv.salvar", None)
    assert err.code is ErrorCode.TARGET_DETACHED
    assert harness.lab_counter("salvar") == 0


def _popup(h) -> None:  # type: ignore[no-untyped-def]
    """Abre a página adversarial como janela de script (só essas podem se fechar com window.close())."""
    h.open_adv()
    with h.page.context.expect_page() as info:
        h.page.evaluate("() => window.open('/adversarial/resolver.html')")
    popup = info.value
    popup.wait_for_load_state()
    h.actions.use_page(popup)


def test_falha_depois_do_despacho_e_outcome_unknown_e_nao_repete(harness):  # type: ignore[no-untyped-def]
    _popup(harness)
    _retry(harness, 3)
    with pytest.raises(OutcomeUnknown) as e:
        harness.actions.click("adv.fecha", timeout_ms=3_000)
    assert e.value.detail == "ACTION_INTERRUPTED"
    assert harness.lab.oracle()["hits"].get("/api/lab/efeito") == 1  # o efeito aconteceu UMA vez
    codes = harness.codes()
    assert "RETRY_SCHEDULED" not in codes and "RETRY_DENIED" in codes and "OUTCOME_UNKNOWN" in codes


def test_falha_depois_do_despacho_declarada_idempotente_nao_vira_unknown(harness):  # type: ignore[no-untyped-def]
    _popup(harness)
    with pytest.raises(PageClosed):
        harness.actions.click("adv.fecha", timeout_ms=3_000, idempotent=True)


def test_poscondicao_nao_confirmada_e_outcome_unknown_sem_repeticao(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    _retry(harness, 3)
    with pytest.raises(OutcomeUnknown) as e:
        harness.actions.click("adv.salvar", timeout_ms=600, postcondition=lambda: False)
    assert e.value.detail == "POSTCONDITION_NOT_MET"
    assert harness.lab_counter("salvar") == 1


def test_poscondicao_confirmada(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.click("adv.contador", postcondition=lambda: harness.actions.read_text("adv.cliques") == "1")
    assert harness.lab_counter("cliques") == 1


def test_nova_aba(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with harness.actions.expect_new_page() as nova:
        harness.actions.click("adv.nova_aba", idempotent=True)
    assert nova.page is not None
    harness.actions.use_page(nova.page)
    assert harness.actions.read_text("adv.destino") == "Destino"


def test_rota_alterada_pelo_clique(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.click("adv.mudar_rota", idempotent=True)
    harness.actions.wait_visible("adv.destino")
    assert harness.page.url.endswith("/adversarial/destino.html")


# ------------------------------------------------------------------------------------------------ origem
def test_navegar_para_origem_nao_permitida_bloqueia_antes_da_requisicao(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(SecurityPolicyBlocked) as e:
        harness.actions.navigate(harness.lab.external_url + "/qualquer")
    assert e.value.detail == "ORIGIN_NOT_ALLOWED"
    with pytest.raises(SecurityPolicyBlocked):
        harness.actions.navigate("https://example.com/")
    assert harness.lab.oracle()["external_hits"] == 0
    assert "SECURITY_BLOCKED" in harness.codes()


def test_redirecionamento_para_outra_origem_e_bloqueado_na_rede(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(SecurityPolicyBlocked) as e:
        harness.actions.navigate("/redir/externo")
    assert e.value.detail == "REDIRECT_BLOCKED"
    assert harness.lab.oracle()["external_hits"] == 0


def test_redirecionamento_na_mesma_origem_funciona(harness):  # type: ignore[no-untyped-def]
    harness.actions.navigate("/redir/mesma-origem")
    assert harness.actions.read_text("adv.destino") == "Destino"


def test_clique_que_leva_a_outra_origem_e_barrado_e_a_proxima_acao_recusada(harness):  # type: ignore[no-untyped-def]
    harness.open_adv("?externo=" + harness.lab.external_url)
    harness.actions.click("adv.ir_externo", idempotent=True)
    harness.page.wait_for_timeout(500)
    with pytest.raises(SecurityPolicyBlocked):
        harness.actions.click("adv.salvar", timeout_ms=1_000)
    assert harness.lab.oracle()["external_hits"] == 0


def test_link_com_redirecionamento_externo(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.click("adv.link_redir", idempotent=True)
    harness.page.wait_for_timeout(500)
    with pytest.raises(SecurityPolicyBlocked):
        harness.actions.click("adv.salvar", timeout_ms=1_000)
    assert harness.lab.oracle()["external_hits"] == 0


def test_nova_aba_para_origem_externa_e_barrada(harness):  # type: ignore[no-untyped-def]
    harness.open_adv("?externo=" + harness.lab.external_url)
    with harness.actions.expect_new_page() as nova:
        harness.actions.click("adv.nova_aba_externa", idempotent=True)
    assert nova.page is not None
    with pytest.raises(SecurityPolicyBlocked):
        harness.actions.use_page(nova.page)
    assert harness.lab.oracle()["external_hits"] == 0


def test_status_http_de_erro_e_navigation_failed(harness):  # type: ignore[no-untyped-def]
    with pytest.raises(NavigationFailed) as e:
        harness.actions.navigate("/nao-existe.html")
    assert e.value.detail == "http_4xx"


# ------------------------------------------------------------------------------------------------ fill
def test_fill_e_conferencia_do_valor(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.fill("adv.campo_texto", "Valor Ficticio", step_id="F-01")
    assert harness.page.input_value("#campo-texto") == "Valor Ficticio"


def test_fill_com_segredo(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.fill("adv.campo_senha", Secret("senha_teste", "s3gr3do-SENTINELA"))
    assert harness.page.input_value("#campo-senha") == "s3gr3do-SENTINELA"
    assert "SENTINELA" not in repr([e.to_dict() for e in harness.events.events])


def test_fill_somente_leitura(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetNotReady) as e:
        harness.actions.fill("adv.campo_ro", "x", timeout_ms=700)
    assert e.value.detail == "readonly"
    assert harness.page.input_value("#campo-ro") == "fixo"


def test_fill_desabilitado(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetNotReady) as e:
        harness.actions.fill("adv.campo_desab", "x", timeout_ms=700)
    assert e.value.detail == "disabled"


def test_fill_valor_nao_aplicado_e_repetido_pela_politica_e_falha(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    _retry(harness, 3)
    with pytest.raises(TransientTechnicalFailure) as e:
        harness.actions.fill("adv.campo_maiusculo", "abc", timeout_ms=3_000)
    assert e.value.detail == "value_not_applied"
    assert harness.codes().count("RETRY_SCHEDULED") == 2
    harness.actions.fill("adv.campo_maiusculo", "abc", verify=False)
    assert harness.page.input_value("#campo-maiusculo") == "ABC"


def test_fill_valor_de_tipo_errado(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(InvalidArgument):
        harness.actions.fill("adv.campo_texto", 123)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ waits e prazos
def test_wait_visible_e_wait_hidden(harness):  # type: ignore[no-untyped-def]
    harness.open_adv("?tardio=400&capa=500")
    harness.actions.wait_visible("adv.tardio", timeout_ms=3_000)
    harness.actions.wait_hidden("adv.capa_temp", timeout_ms=3_000)
    with pytest.raises(ActionTimeout) as e:
        harness.actions.wait_hidden("adv.salvar", timeout_ms=400)
    assert e.value.detail == "still_visible"


def test_prazo_da_transacao_limita_a_acao(harness):  # type: ignore[no-untyped-def]
    from nekkora_rpa.core.context import TransactionScope

    harness.open_adv()
    harness.ctx.transaction = TransactionScope("tx-teste", Deadline.after_ms(400, harness.ctx.clock))
    t0 = harness.ctx.clock.monotonic()
    with pytest.raises(NekkoraRpaError):
        harness.actions.click("adv.inexistente", timeout_ms=10_000)
    assert harness.ctx.clock.monotonic() - t0 < 1.5


def test_cancelamento_durante_espera(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    threading.Timer(0.4, harness.ctx.cancel.cancel).start()
    t0 = harness.ctx.clock.monotonic()
    with pytest.raises(Cancelled):
        harness.actions.click("adv.inexistente", timeout_ms=10_000)
    assert harness.ctx.clock.monotonic() - t0 < 2.0
    assert harness.lab_counter("salvar") == 0
