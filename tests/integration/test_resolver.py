"""F2 — Registro/Resolver em navegador real: identidade, ambiguidade, estratégias e "nunca o botão errado"."""

from __future__ import annotations

import pytest

from nekkora_rpa.errors import (
    ErrorCode,
    NekkoraRpaError,
    TargetAmbiguous,
    TargetIdentityMismatch,
    TargetNotFound,
)

pytestmark = pytest.mark.browser


def _all_counters(h) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return dict(h.page.evaluate("() => window.__lab"))


@pytest.mark.parametrize("key", ["adv.salvar", "adv.salvar_xpath", "adv.salvar_id", "adv.salvar_role"])
def test_estrategias_resolvem_o_mesmo_alvo_e_clicam(harness, key):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.click(key, step_id="S-01", idempotent=True)
    assert harness.lab_counter("salvar") == 1
    resolved = [e for e in harness.events.events if e.event_code == "TARGET_RESOLVED"]
    assert resolved[-1].strategy_index == 0


def test_name_strategy_preenche_o_campo(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.fill("adv.campo_por_name", "valor-de-teste")
    assert harness.page.input_value("#campo-texto") == "valor-de-teste"


def test_alternativo_so_com_identidade_verificada(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.click("adv.salvar_alt_ok", idempotent=True)
    assert harness.lab_counter("salvar") == 1
    resolved = [e for e in harness.events.events if e.event_code == "TARGET_RESOLVED"]
    assert resolved[-1].strategy_index == 1


def test_candidatos_que_discordam_sao_ambiguos_e_nada_e_clicado(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetAmbiguous) as e:
        harness.actions.click("adv.salvar_disagree")
    assert e.value.detail == "candidates_disagree"
    assert harness.lab_counter("salvar") == 0 and harness.lab_counter("cliques") == 0


def test_dois_elementos_sao_ambiguos_nunca_o_primeiro(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    before = _all_counters(harness)
    with pytest.raises(TargetAmbiguous):
        harness.actions.click("adv.duplicado")
    assert _all_counters(harness) == before
    assert "TARGET_REJECTED" in harness.codes()


def test_sosias_por_papel_e_nome_sao_ambiguos(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetAmbiguous):
        harness.actions.click("adv.enviar_por_papel")
    assert harness.lab_counter("enviarReal") == 0 and harness.lab_counter("enviarSosia") == 0


def test_alvo_preciso_entre_sosias_clica_so_o_real(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.actions.click("adv.enviar_real", idempotent=True)
    assert harness.lab_counter("enviarReal") == 1 and harness.lab_counter("enviarSosia") == 0


def test_alternativo_que_casa_sosia_bloqueia_mesmo_com_preferido_unico(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetAmbiguous):
        harness.actions.click("adv.enviar_real_alt_sosia")
    assert harness.lab_counter("enviarReal") == 0 and harness.lab_counter("enviarSosia") == 0


def test_nome_divergente_e_identity_mismatch_sem_clique(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetIdentityMismatch) as e:
        harness.actions.click("adv.excluir")
    assert e.value.detail == "name"
    assert harness.lab_counter("excluir") == 0


def test_tag_divergente_e_identity_mismatch(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetIdentityMismatch) as e:
        harness.actions.click("adv.link_como_botao")
    assert e.value.detail == "tag"


def test_tipo_divergente_bloqueia_preenchimento(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetIdentityMismatch) as e:
        harness.actions.fill("adv.campo_tipo_errado", "x")
    assert e.value.detail == "type"
    assert harness.page.input_value("#campo-texto") == ""


def test_shadow_root_nao_suportado_e_recusado(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetIdentityMismatch) as e:
        harness.actions.click("adv.sombra")
    assert e.value.detail == "scope"


def test_iframe_nao_suportado_nao_e_encontrado(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(TargetNotFound):
        harness.actions.click("adv.no_frame", timeout_ms=600)


def test_ausente_espera_ate_o_prazo_e_falha_sem_retentar_alem_dele(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    t0 = harness.ctx.clock.monotonic()
    with pytest.raises(TargetNotFound):
        harness.actions.click("adv.inexistente", timeout_ms=700)
    elapsed = harness.ctx.clock.monotonic() - t0
    assert 0.6 <= elapsed < 2.0


def test_alvo_tardio_e_aguardado_dentro_do_prazo(harness):  # type: ignore[no-untyped-def]
    harness.open_adv("?tardio=600")
    harness.actions.click("adv.tardio", timeout_ms=3_000, idempotent=True)
    assert harness.lab_counter("tardio") == 1


def test_dom_muda_entre_consultas_resolve_o_novo_no_com_identidade(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    harness.page.evaluate(
        """() => { const old = document.getElementById('salvar'); const b = old.cloneNode(true);
        b.addEventListener('click', () => window.__lab.salvar += 10); old.replaceWith(b); }"""
    )
    harness.actions.click("adv.salvar", idempotent=True)
    assert harness.lab_counter("salvar") == 10


def test_troca_do_alvo_por_outro_elemento_com_mesmo_id_e_recusada(harness):  # type: ignore[no-untyped-def]
    """O id #salvar passa a apontar para um botão 'Excluir': o seletor casa, mas a identidade não."""
    harness.open_adv()
    harness.page.evaluate(
        """() => { document.getElementById('salvar').id = 'salvar-velho';
        document.getElementById('excluir').id = 'salvar'; }"""
    )
    with pytest.raises(TargetIdentityMismatch):
        harness.actions.click("adv.salvar")
    assert harness.lab_counter("excluir") == 0 and harness.lab_counter("salvar") == 0


def test_exists_e_seguro(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    assert harness.actions.exists("adv.salvar") is True
    assert harness.actions.exists("adv.inexistente") is False
    with pytest.raises(TargetAmbiguous):
        harness.actions.exists("adv.duplicado")
    with pytest.raises(TargetIdentityMismatch):
        harness.actions.exists("adv.excluir")


def test_chave_desconhecida_e_erro_de_configuracao(harness):  # type: ignore[no-untyped-def]
    harness.open_adv()
    with pytest.raises(NekkoraRpaError) as e:
        harness.actions.click("adv.nao_registrada")
    assert e.value.code is ErrorCode.INVALID_CONFIGURATION
