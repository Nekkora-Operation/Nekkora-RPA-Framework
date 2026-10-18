"""Configuração estrita, política de origens (LAB = loopback), segredos e eventos fechados."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from nekkora_rpa import EnvSecretProvider, OriginPolicy, Secret, load_config
from nekkora_rpa.core.config import from_mapping
from nekkora_rpa.errors import InvalidConfiguration, NekkoraRpaError, SecretUnavailable
from nekkora_rpa.observability.events import Event, EventCode
from nekkora_rpa.security.origins import origin_of

BASE = {
    "runtime": {
        "environment": "lab",
        "allowed_origins": ["http://127.0.0.1:18080"],
        "base_url": "http://127.0.0.1:18080",
        "process_name": "p",
    }
}


def cfg(**over: dict[str, object]) -> object:
    data = {k: dict(v) for k, v in BASE.items()}
    for k, v in over.items():
        data.setdefault(k, {}).update(v)
    return from_mapping(data, base_dir=Path.cwd())


@pytest.mark.parametrize(
    ("over", "detail"),
    [
        ({"runtime": {"environment": "prod"}}, "environment"),
        ({"runtime": {"allowed_origins": ["https://erp.cliente.com.br"]}}, "allowed_origins_not_lab"),
        ({"runtime": {"allowed_origins": ["http://10.0.0.5:80"]}}, "allowed_origins_not_lab"),
        ({"runtime": {"allowed_origins": ["http://127.0.0.1:18080/caminho"]}}, "allowed_origins"),
        ({"runtime": {"allowed_origins": ["http://user:pw@127.0.0.1:1"]}}, "allowed_origins"),
        ({"runtime": {"allowed_origins": []}}, "allowed_origins"),
        ({"runtime": {"base_url": "http://127.0.0.1:9999"}}, "config_base_url_not_allowed"),
        ({"runtime": {"process_name": "meu processo"}}, "config_process_name"),
        ({"runtime": {"senha": "x"}}, "config_unknown_field"),
        ({"credenciais": {"usuario": "x"}}, "config_unknown_section"),
        ({"timeouts": {"action_ms": 0}}, "config_timeouts_action_ms"),
        ({"timeouts": {"action_ms": True}}, "config_timeouts_action_ms"),
        ({"timeouts": {"action_ms": "8000"}}, "config_timeouts_action_ms"),
        ({"retry": {"max_attempts": 50}}, "retry"),
        ({"browser": {"channel": "firefox"}}, "config_browser_channel"),
        ({"batch": {"max_transaction_attempts": 9}}, "config_batch"),
    ],
)
def test_configuracao_invalida(over, detail):  # type: ignore[no-untyped-def]
    with pytest.raises(InvalidConfiguration) as e:
        cfg(**over)
    assert e.value.detail == detail


def test_toml_com_caminhos_relativos_a_pasta_do_arquivo(tmp_path: Path):
    (tmp_path / "conf").mkdir()
    f = tmp_path / "conf" / "lab.toml"
    f.write_text(
        '[runtime]\nenvironment = "lab"\nallowed_origins = ["http://localhost:8080"]\n'
        'base_url = "http://localhost:8080"\nprocess_name = "p"\n[paths]\nselectors = "sel.json"\nrun_dir = "../runs"\n',
        encoding="utf-8",
    )
    c = load_config(f, {"retry.max_attempts": 3})
    assert c.selectors_path == (tmp_path / "conf" / "sel.json").resolve()
    assert c.run_dir == (tmp_path / "runs").resolve()
    assert c.retry.max_attempts == 3
    with pytest.raises(InvalidConfiguration):
        load_config(f, {"runtime.senha": "x"})


def test_origens():
    p = OriginPolicy(["http://127.0.0.1:18080", "http://localhost:3000/"])
    assert p.is_allowed("http://127.0.0.1:18080/clientes/consulta.html?codigo=1")
    assert p.is_allowed("http://localhost:3000/")
    assert not p.is_allowed("http://127.0.0.1:18081/")
    assert not p.is_allowed("https://127.0.0.1:18080/")
    assert not p.is_allowed("http://user@127.0.0.1:18080/")
    assert not p.is_allowed("javascript:alert(1)")
    assert not p.is_allowed("file:///c:/x")
    assert not p.is_allowed("http://127.0.0.1.evil.com:18080/")
    assert origin_of("http://[::1]:80/") == "http://[::1]:80"
    assert origin_of("http://127.0.0.1:99999/") is None


def test_segredo_nao_se_revela():
    s = Secret("senha_lab", "SENTINELA-123")
    assert "SENTINELA" not in str(s) + repr(s) + f"{s}" + f"{s!r}" + "%s" % s
    assert s.reveal() == "SENTINELA-123"
    with pytest.raises(TypeError):
        pickle.dumps(s)
    assert s != Secret("senha_lab", "SENTINELA-123")


def test_provedor_de_ambiente():
    env = {"NK_SECRET_LAB_SENHA": "valor-SENTINELA"}
    p = EnvSecretProvider(["lab.senha", "lab.usuario"], environ=env)
    assert p.get("lab.senha").reveal() == "valor-SENTINELA"
    with pytest.raises(SecretUnavailable) as e:
        p.get("lab.usuario")
    assert e.value.detail == "missing"
    with pytest.raises(SecretUnavailable):
        p.get("outro")
    with pytest.raises(SecretUnavailable):
        p.require_all()


@pytest.mark.parametrize(
    "field",
    [
        {"step_id": "passo 1"},
        {"key": "#cpf"},
        {"detail": "http://127.0.0.1/x?cpf=123"},
        {"cause_type": "Error: locator('#x') resolved to 2"},
        {"error_code": "senha=abc def"},
        {"attempt": True},
        {"count": 3.5},
    ],
)
def test_evento_fechado_recusa_texto_livre(field):  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        Event("2026-10-17T10:00:00.000Z", "ex-1", EventCode.ACTION_STARTED, "0.1.0", **field)


def test_erro_de_configuracao_nao_ecoa_valor(tmp_path: Path):
    f = tmp_path / "x.toml"
    f.write_text('[runtime]\nsenha = "SENTINELA"\n', encoding="utf-8")
    with pytest.raises(NekkoraRpaError) as e:
        load_config(f)
    assert "SENTINELA" not in str(e.value) + repr(e.value)
