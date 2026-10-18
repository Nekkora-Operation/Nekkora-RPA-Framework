"""F2 — leitura estrita do registro ``nekkora-rpa/selectors`` 1.0.0."""

from __future__ import annotations

import json
from typing import Any

import pytest

from nekkora_rpa import SelectorRegistry
from nekkora_rpa.errors import InvalidConfiguration
from nekkora_rpa.selectors.schema import Strategy


def doc(targets: dict[str, Any] | None = None, **root: Any) -> str:
    base: dict[str, Any] = {
        "schema": "nekkora-rpa/selectors",
        "version": "1.0.0",
        "system": "clientes",
        "targets": targets
        if targets is not None
        else {
            "clientes.login.entrar": {
                "preferred": {"strategy": "css", "expression": "#login-button"},
                "alternatives": [{"strategy": "role", "role": "button", "name": "Entrar"}],
                "expected": {"tag": "button", "role": "button", "name": "Entrar"},
            }
        },
    }
    base.update(root)
    return json.dumps(base)


def load(text: str, env: str = "lab") -> SelectorRegistry:
    return SelectorRegistry.from_text(text, environment=env)


def detail(text: str) -> str | None:
    with pytest.raises(InvalidConfiguration) as e:
        load(text)
    return e.value.detail


def test_exemplo_da_missao_carrega():
    reg = load(doc())
    t = reg.get("clientes.login.entrar")
    assert t.preferred.strategy is Strategy.CSS
    assert t.alternatives[0].strategy is Strategy.ROLE
    assert reg.revision.startswith("sha256:") and len(reg.revision) == 71


def test_revisao_muda_com_o_conteudo_e_nao_com_a_formatacao():
    a = load(doc()).revision
    b = load(json.dumps(json.loads(doc()), indent=4)).revision
    t = json.loads(doc())
    t["targets"]["clientes.login.entrar"]["expected"]["name"] = "Acessar"
    t["targets"]["clientes.login.entrar"]["alternatives"][0]["name"] = "Acessar"
    assert a == b and load(json.dumps(t)).revision != a


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.update(extra=1), "selectors_root_unknown_field"),
        (lambda d: d.update(schema="outro"), "selectors_schema"),
        (lambda d: d.update(version="2.0.0"), "selectors_version"),
        (lambda d: d.update(system="cli entes"), "selectors_system"),
        (lambda d: d.update(targets={}), "selectors_targets"),
        (
            lambda d: d.update(
                targets={
                    "outro.login.x": {"preferred": {"strategy": "css", "expression": "#a"}, "expected": {"tag": "a"}}
                }
            ),
            "selectors_key",
        ),
        (
            lambda d: d.update(
                targets={
                    "clientes.x": {
                        "preferred": {"strategy": "css", "expression": "#a"},
                        "expected": {"tag": "a"},
                        "fallback": True,
                    }
                }
            ),
            "selectors_target_unknown_field",
        ),
        (
            lambda d: d.update(
                targets={
                    "clientes.x": {"preferred": {"strategy": "jquery", "expression": "#a"}, "expected": {"tag": "a"}}
                }
            ),
            "selectors_strategy_unsupported",
        ),
        (
            lambda d: d.update(
                targets={"clientes.x": {"preferred": {"strategy": "css", "expression": ""}, "expected": {"tag": "a"}}}
            ),
            "selectors_expression",
        ),
        (
            lambda d: d.update(
                targets={
                    "clientes.x": {
                        "preferred": {"strategy": "css", "expression": "#a", "frame": "f"},
                        "expected": {"tag": "a"},
                    }
                }
            ),
            "selectors_locator_unknown_field",
        ),
        (
            lambda d: d.update(targets={"clientes.x": {"preferred": {"strategy": "css", "expression": "#a"}}}),
            "selectors_target_missing_field",
        ),
        (
            lambda d: d.update(
                targets={
                    "clientes.x": {
                        "preferred": {"strategy": "css", "expression": "#a"},
                        "expected": {"tag": "a", "name": "Entrar"},
                    }
                }
            ),
            "selectors_expected_name_requires_role",
        ),
        (
            lambda d: d.update(
                targets={
                    "clientes.x": {
                        "preferred": {"strategy": "css", "expression": "#a"},
                        "alternatives": [{"strategy": "id", "value": "a"}],
                        "expected": {"tag": "a"},
                    }
                }
            ),
            "selectors_alternatives_require_strong_identity",
        ),
        (
            lambda d: d.update(
                targets={
                    "clientes.x": {
                        "preferred": {"strategy": "css", "expression": "#a"},
                        "alternatives": [{"strategy": "css", "expression": "#a"}],
                        "expected": {"tag": "a", "role": "link", "name": "A"},
                    }
                }
            ),
            "selectors_duplicate_locator",
        ),
        (
            lambda d: d.update(
                targets={
                    "clientes.x": {"preferred": {"strategy": "role", "role": "button"}, "expected": {"tag": "button"}}
                }
            ),
            "selectors_locator_missing_field",
        ),
    ],
)
def test_recusas_estritas(mutate, expected):  # type: ignore[no-untyped-def]
    d = json.loads(doc())
    mutate(d)
    assert detail(json.dumps(d)) == expected


def test_chave_json_duplicada_e_recusada():
    text = doc().replace('"system": "clientes"', '"system": "clientes", "system": "clientes"')
    assert detail(text) == "selectors_duplicate_key"


def test_alvo_duplicado_no_mesmo_arquivo_e_recusado():
    t = '"clientes.a": {"preferred": {"strategy": "css", "expression": "#a"}, "expected": {"tag": "a"}}'
    text = doc().replace('"targets": {', '"targets": {' + t + ", " + t + ", ", 1)
    assert detail(text) == "selectors_duplicate_key"


def test_json_invalido_e_erro_sem_conteudo():
    with pytest.raises(InvalidConfiguration) as e:
        load("{ isto nao e json com-SENTINELA")
    assert "SENTINELA" not in str(e.value) and "SENTINELA" not in repr(e.value)


def test_variante_de_ambiente_explicita():
    d = json.loads(doc())
    t = d["targets"]["clientes.login.entrar"]
    t["variants"] = {"homolog": {"preferred": {"strategy": "id", "value": "entrar-h"}}}
    assert load(json.dumps(d), "homolog").get("clientes.login.entrar").preferred.value == "entrar-h"
    assert load(json.dumps(d), "lab").get("clientes.login.entrar").preferred.expression == "#login-button"


def test_variante_invalida_e_recusada_mesmo_se_nao_usada():
    d = json.loads(doc())
    d["targets"]["clientes.login.entrar"]["variants"] = {"prod": {"preferred": {"strategy": "x"}}}
    assert detail(json.dumps(d)) == "selectors_strategy_unsupported"


def test_chave_desconhecida_e_chave_malformada():
    reg = load(doc())
    with pytest.raises(InvalidConfiguration):
        reg.get("clientes.login.sair")
    with pytest.raises(Exception) as e:
        reg.get("#login-button")
    assert getattr(e.value, "detail", None) == "key"


def test_procedencia_opcional():
    d = json.loads(doc())
    d["targets"]["clientes.login.entrar"]["provenance"] = {"studioStepId": "a44a73a5-7733-4745-8140-7442cde06414"}
    assert load(json.dumps(d)).get("clientes.login.entrar").studio_step_id.startswith("a44a")


# ------------------------------------------------------------------------------------------------ 1.1.0: rótulo visível
def test_estrategia_e_evidencia_de_rotulo_na_1_1_0():
    d = json.loads(doc())
    d["version"] = "1.1.0"
    d["targets"]["clientes.form.email"] = {
        "preferred": {"strategy": "label", "text": "  Email "},
        "expected": {"tag": "input", "label": "Email"},
    }
    t = load(json.dumps(d)).get("clientes.form.email")
    assert t.preferred.text == "Email" and t.expected.label == "Email" and t.expected.strong


def test_rotulo_e_recusado_na_1_0_0():
    d = json.loads(doc())
    d["targets"]["clientes.form.email"] = {
        "preferred": {"strategy": "label", "text": "Email"},
        "expected": {"tag": "input"},
    }
    assert detail(json.dumps(d)) == "selectors_strategy_unsupported"
    d["targets"]["clientes.form.email"] = {
        "preferred": {"strategy": "id", "value": "e"},
        "expected": {"tag": "input", "label": "Email"},
    }
    assert detail(json.dumps(d)) == "selectors_expected_unknown_field"


def test_alternativo_permitido_com_rotulo_como_identidade_forte():
    d = json.loads(doc())
    d["version"] = "1.1.0"
    d["targets"]["clientes.form.email"] = {
        "preferred": {"strategy": "label", "text": "Email"},
        "alternatives": [{"strategy": "css", "expression": "[ng-reflect-name=labelEmail]"}],
        "expected": {"tag": "input", "label": "Email"},
    }
    assert len(load(json.dumps(d)).get("clientes.form.email").alternatives) == 1
