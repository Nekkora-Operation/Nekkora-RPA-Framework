"""NEKKORA-PACKAGING-001: guardas da publicação e inspeção da distribuição (sem rede, sem publicar)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import guardas_publicacao as g  # noqa: E402
import verificar_distribuicao as v  # noqa: E402

PYPROJECT_LIBERADO = '[project]\nname = "nekkora-rpa"\nclassifiers = ["Programming Language :: Python :: 3.12"]\n'
OK = dict(
    versao="0.3.0",
    pyproject=PYPROJECT_LIBERADO,
    destino="testpypi",
    ref_type="tag",
    ref_name="v0.3.0",
    licenca_aprovada="0.3.0",
    no_destino=False,
    no_testpypi=False,
)


def test_tudo_autorizado_para_staging_passa() -> None:
    assert g.avaliar(**OK) == []


@pytest.mark.parametrize(
    ("mudanca", "trecho"),
    [
        ({"pyproject": PYPROJECT_LIBERADO + '# "Private :: Do Not Upload"\n'}, "P1"),
        ({"licenca_aprovada": ""}, "licença não aprovada"),
        ({"licenca_aprovada": "0.2.0"}, "licença não aprovada"),
        ({"ref_type": "branch", "ref_name": "main"}, "tag v0.3.0"),
        ({"ref_name": "v0.3.1"}, "tag v0.3.0"),
        ({"no_destino": True}, "nunca republicar"),
        ({"destino": "pypi"}, "P3"),
        ({"destino": "outro"}, "destino desconhecido"),
    ],
)
def test_cada_guarda_falha_fechado(mudanca: dict[str, object], trecho: str) -> None:
    erros = g.avaliar(**{**OK, **mudanca})  # type: ignore[arg-type]
    assert any(trecho in e for e in erros), erros


def test_producao_so_depois_do_staging() -> None:
    assert g.avaliar(**{**OK, "destino": "pypi", "no_testpypi": True}) == []  # type: ignore[arg-type]


def test_o_pyproject_atual_continua_bloqueado() -> None:
    """Enquanto a titular não decidir a distribuição (P1), o próprio repositório bloqueia a publicação."""
    atual = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert any("P1" in e for e in g.avaliar(**{**OK, "pyproject": atual}))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "intruso",
    [
        "nekkora_rpa/.env",
        "nekkora_rpa/dados.xlsx",
        "nekkora_rpa/projeto.nekkora",
        "reports/x.json",
        "nekkora_rpa/__pycache__/a.pyc",
        "lab/app.py",
        "tests/test_a.py",
        "nekkora_rpa/chave.pem",
        "nekkora_rpa/api_token.txt",
    ],
)
def test_conteudo_proibido_e_recusado(intruso: str) -> None:
    nomes = [*_nomes_minimos(), intruso]
    assert any("proibido" in p for p in v.check_names("wheel", nomes, "0.3.0")), intruso


def test_conteudo_minimo_aceito_e_falta_detectada() -> None:
    nomes = _nomes_minimos()
    assert v.check_names("wheel", nomes, "0.3.0") == []
    sem_tipos = [n for n in nomes if not n.endswith("py.typed")]
    assert any("py.typed" in p for p in v.check_names("wheel", sem_tipos, "0.3.0"))


def test_metadados_conferidos() -> None:
    meta = (
        "Metadata-Version: 2.4\nName: nekkora-rpa\nVersion: 0.3.0\nRequires-Python: >=3.12\nProvides-Extra: excel\n"
        'Requires-Dist: playwright<2,>=1.63\nRequires-Dist: openpyxl<4,>=3.1.5; extra == "excel"\n\ncorpo'
    )
    assert v.check_metadata(meta, "0.3.0") == []
    assert any("Version" in p for p in v.check_metadata(meta, "0.3.1"))
    assert any("Requires-Python" in p for p in v.check_metadata(meta.replace(">=3.12", ">=3.11"), "0.3.0"))
    assert any("excel" in p for p in v.check_metadata(meta.replace("Provides-Extra: excel\n", ""), "0.3.0"))


def _nomes_minimos() -> list[str]:
    src = v.ROOT / "src" / "nekkora_rpa"
    nomes = [f"nekkora_rpa/{p.relative_to(src).as_posix()}" for p in src.rglob("*.py")]
    nomes += [f"nekkora_rpa/contracts/{p.name}" for p in (src / "contracts").glob("*.json")]
    return [*nomes, "nekkora_rpa/py.typed", "nekkora_rpa-0.3.0.dist-info/licenses/LICENSE"]
