"""Contratos versionados: esquemas atualizados com o código, artefatos reais válidos e exemplos conformes."""

from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path

import jsonschema
import pytest

from nekkora_rpa import (
    Engine,
    InMemoryInputProvider,
    InMemoryResultSink,
    ProcessResult,
    RpaProcess,
    Runtime,
    SelectorRegistry,
    TransactionItem,
)
from nekkora_rpa.core.config import from_mapping
from nekkora_rpa.data import JsonDirectoryResultSink
from nekkora_rpa.errors import BusinessRuleRejected, InvalidConfiguration, TransientTechnicalFailure

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gerar_contratos  # noqa: E402


def schema(name: str) -> dict[str, object]:
    text = resources.files("nekkora_rpa").joinpath("contracts", name).read_text(encoding="utf-8")
    return json.loads(text)


def validate(instance: object, name: str) -> None:
    jsonschema.Draft202012Validator(schema(name)).validate(instance)


FROZEN_1_0_0 = ["checkpoint", "events", "result", "run-summary", "selectors"]


def test_esquemas_1_0_0_continuam_publicados_e_validos():
    for name in FROZEN_1_0_0:
        jsonschema.Draft202012Validator.check_schema(schema(f"{name}-1.0.0.schema.json"))


def test_esquemas_versionados_batem_com_o_gerador():
    for name, s in gerar_contratos.schemas().items():
        assert resources.files("nekkora_rpa").joinpath("contracts", name).read_text(
            encoding="utf-8"
        ) == gerar_contratos.render(s), f"{name} desatualizado: rode tools/gerar_contratos.py"
        jsonschema.Draft202012Validator.check_schema(s)


@pytest.mark.parametrize(
    "path",
    [
        ROOT / "examples" / "consulta_clientes" / "selectors.json",
        ROOT / "examples" / "cadastro_pedidos" / "selectors.json",
        ROOT / "tests" / "fixtures" / "adv-selectors.json",
        ROOT / "tests" / "fixtures" / "desafio-selectors.json",  # 1.1.0: estratégia label e expected.label
    ],
)
def test_registros_dos_exemplos_seguem_o_esquema_e_o_leitor(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    validate(doc, f"selectors-{doc['version']}.schema.json")
    SelectorRegistry.load(path, environment="lab")


def test_esquema_e_leitor_concordam_nas_recusas():
    bad = {
        "schema": "nekkora-rpa/selectors",
        "version": "1.0.0",
        "system": "s",
        "targets": {
            "s.x": {"preferred": {"strategy": "css", "expression": "#a", "frame": "f"}, "expected": {"tag": "a"}}
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        validate(bad, "selectors-1.0.0.schema.json")
    with pytest.raises(InvalidConfiguration):
        SelectorRegistry.from_text(json.dumps(bad), environment="lab")


class Misto(RpaProcess):
    name = "contrato"
    requires_browser = False

    def process(self, rt: Runtime, item: TransactionItem) -> ProcessResult:
        if item.reference == "b":
            raise BusinessRuleRejected("REGRA")
        if item.reference == "c":
            rt.ctx.mark_side_effect()
            raise TransientTechnicalFailure()
        return ProcessResult({"valor": item.reference})


def test_artefatos_reais_seguem_os_esquemas(tmp_path: Path):
    config = from_mapping(
        {
            "runtime": {
                "environment": "lab",
                "allowed_origins": ["http://127.0.0.1:1"],
                "base_url": "http://127.0.0.1:1",
                "process_name": "contrato",
            }
        },
        base_dir=ROOT,
    )
    sink = JsonDirectoryResultSink(tmp_path / "resultados")
    Engine(
        Misto(), InMemoryInputProvider([TransactionItem(r) for r in "abc"]), sink, config, run_dir=tmp_path / "run"
    ).run()
    lines = (tmp_path / "run" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) > 20
    for line in lines:
        validate(json.loads(line), "events-1.1.0.schema.json")
    validate(
        json.loads((tmp_path / "run" / "checkpoint.json").read_text(encoding="utf-8")), "checkpoint-1.1.0.schema.json"
    )
    validate(
        json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8")), "run-summary-1.1.0.schema.json"
    )
    files = list((tmp_path / "resultados").glob("*.json"))
    assert len(files) == 3
    for f in files:
        validate(json.loads(f.read_text(encoding="utf-8")), "result-1.1.0.schema.json")


def test_destino_em_memoria_e_idempotente_por_transacao():
    sink = InMemoryResultSink()
    config = from_mapping(
        {
            "runtime": {
                "environment": "lab",
                "allowed_origins": ["http://127.0.0.1:1"],
                "base_url": "http://127.0.0.1:1",
                "process_name": "contrato",
            }
        },
        base_dir=ROOT,
    )
    Engine(Misto(), InMemoryInputProvider([TransactionItem("a")]), sink, config).run()
    assert len(sink.delivered) == 1
