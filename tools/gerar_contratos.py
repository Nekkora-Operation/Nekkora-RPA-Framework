"""Gera os JSON Schemas dos contratos públicos a partir dos enums do código (fonte única).

Uso: ``python tools/gerar_contratos.py`` (reescreve ``src/nekkora_rpa/contracts``). O teste de contrato falha se os
arquivos versionados divergirem do que este gerador produz.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from nekkora_rpa.core.contracts import DeliveryStatus, TransactionStatus
from nekkora_rpa.core.engine import RunStatus
from nekkora_rpa.errors import ErrorCode
from nekkora_rpa.observability.events import EventCode, Phase

OUT = Path(__file__).resolve().parents[1] / "src" / "nekkora_rpa" / "contracts"
TOKEN = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$"
KEY = "^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)+$"
TX = "^tx-[0-9a-f]{20}$"
SHA = "^sha256:[0-9a-f]{64}$"
DRAFT = "https://json-schema.org/draft/2020-12/schema"
ACTIONS = [
    "click",
    "double_click",
    "fill",
    "wait_visible",
    "wait_hidden",
    "exists",
    "is_visible",
    "read_text",
    "navigate",
    "download",
    "mark",
    "read_text_matching",
]


def tok() -> dict[str, Any]:
    return {"type": "string", "pattern": TOKEN}


def nullable(s: dict[str, Any]) -> dict[str, Any]:
    return {"oneOf": [{"type": "null"}, s]}


def enum(e: Any) -> dict[str, Any]:
    return {"enum": [m.value for m in e]}


def nonempty(limit: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": limit}


def schemas() -> dict[str, dict[str, Any]]:
    locator = {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["strategy", "expression"],
                "properties": {"strategy": {"enum": ["css", "xpath"]}, "expression": nonempty(1000)},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["strategy", "value"],
                "properties": {"strategy": {"enum": ["id", "name", "test_id"]}, "value": nonempty(200)},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["strategy", "role", "name"],
                "properties": {
                    "strategy": {"const": "role"},
                    "role": {"type": "string", "pattern": "^[A-Za-z]{1,40}$"},
                    "name": nonempty(200),
                },
            },
        ]
    }
    locators = {"type": "array", "maxItems": 5, "items": {"$ref": "#/$defs/locator"}}
    selectors = {
        "$schema": DRAFT,
        "$id": "nekkora-rpa/selectors/1.1.0",
        "title": "Registro de alvos por chave",
        "$comment": "Além do esquema, o leitor recusa: chave fora de '<system>.', chave JSON duplicada, alternativos "
        "sem expected.name e candidatos repetidos.",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "version", "system", "targets"],
        "properties": {
            "schema": {"const": "nekkora-rpa/selectors"},
            "version": {"const": "1.1.0"},
            "system": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_:-]{0,79}$"},
            "targets": {
                "type": "object",
                "minProperties": 1,
                "propertyNames": {"pattern": KEY},
                "additionalProperties": {"$ref": "#/$defs/target"},
            },
        },
        "$defs": {
            "locator": locator,
            "expected": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tag"],
                "properties": {
                    "tag": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9-]{0,39}$"},
                    "role": nonempty(40),
                    "name": nonempty(200),
                    "type": nonempty(40),
                },
                "dependentRequired": {"name": ["role"]},
            },
            "target": {
                "type": "object",
                "additionalProperties": False,
                "required": ["preferred", "expected"],
                "properties": {
                    "page": tok(),
                    "preferred": {"$ref": "#/$defs/locator"},
                    "alternatives": locators,
                    "expected": {"$ref": "#/$defs/expected"},
                    "variants": {
                        "type": "object",
                        "minProperties": 1,
                        "propertyNames": {"pattern": TOKEN},
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["preferred"],
                            "properties": {"preferred": {"$ref": "#/$defs/locator"}, "alternatives": locators},
                        },
                    },
                    "provenance": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"studioStepId": tok()},
                    },
                },
            },
        },
    }
    events = {
        "$schema": DRAFT,
        "$id": "nekkora-rpa/events/1.1.0",
        "title": "Evento de execução (uma linha JSON)",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "version", "timestamp_utc", "execution_id", "event_code", "framework_version"],
        "properties": {
            "schema": {"const": "nekkora-rpa/events"},
            "version": {"const": "1.1.0"},
            "timestamp_utc": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$"},
            "execution_id": tok(),
            "event_code": enum(EventCode),
            "framework_version": tok(),
            "phase": enum(Phase),
            "transaction_id": tok(),
            "step_id": tok(),
            "key": {"type": "string", "pattern": KEY},
            "action": {"enum": ACTIONS},
            "attempt": {"type": "integer", "minimum": 0},
            "elapsed_ms": {"type": "integer", "minimum": 0},
            "outcome": tok(),
            "error_code": enum(ErrorCode),
            "detail": tok(),
            "cause_type": tok(),
            "strategy_index": {"type": "integer", "minimum": 0, "maximum": 5},
            "delay_ms": {"type": "integer", "minimum": 0},
            "count": {"type": "integer", "minimum": 0},
            "selector_registry_revision": {"type": "string", "pattern": SHA},
        },
    }
    record = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "delivery", "side_effects", "attempts"],
        "properties": {
            "status": enum(TransactionStatus),
            "delivery": enum(DeliveryStatus),
            "side_effects": {"type": "integer", "minimum": 0},
            "attempts": {"type": "integer", "minimum": 0},
            "error_code": enum(ErrorCode),
            "detail": tok(),
            "execution_id": tok(),
            "updated_utc": tok(),
        },
    }
    checkpoint = {
        "$schema": DRAFT,
        "$id": "nekkora-rpa/checkpoint/1.1.0",
        "title": "Checkpoint local",
        "type": "object",
        "additionalProperties": False,
        "required": ["body", "integrity"],
        "properties": {
            "integrity": {"type": "string", "pattern": SHA},
            "body": {
                "type": "object",
                "additionalProperties": False,
                "required": ["schema", "version", "process_name", "salt", "transactions"],
                "properties": {
                    "schema": {"const": "nekkora-rpa/checkpoint"},
                    "version": {"const": "1.1.0"},
                    "process_name": tok(),
                    "salt": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "transactions": {
                        "type": "object",
                        "propertyNames": {"pattern": TX},
                        "additionalProperties": record,
                    },
                },
            },
        },
    }
    result = {
        "$schema": DRAFT,
        "$id": "nekkora-rpa/result/1.1.0",
        "title": "Resultado de transação (JsonDirectoryResultSink)",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "version", "transaction_id", "status", "error_code", "detail", "output"],
        "properties": {
            "schema": {"const": "nekkora-rpa/result"},
            "version": {"const": "1.1.0"},
            "transaction_id": {"type": "string", "pattern": TX},
            "status": enum(TransactionStatus),
            "error_code": nullable(enum(ErrorCode)),
            "detail": nullable(tok()),
            "output": nullable({"type": "object"}),
        },
    }
    summary = {
        "$schema": DRAFT,
        "$id": "nekkora-rpa/run-summary/1.1.0",
        "title": "Resumo da execução",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "version",
            "execution_id",
            "framework_version",
            "status",
            "stop_code",
            "stop_detail",
            "cleanup_ok",
            "counts",
            "transactions",
        ],
        "properties": {
            "schema": {"const": "nekkora-rpa/run-summary"},
            "version": {"const": "1.1.0"},
            "execution_id": tok(),
            "framework_version": tok(),
            "status": enum(RunStatus),
            "stop_code": nullable(enum(ErrorCode)),
            "stop_detail": nullable(tok()),
            "cleanup_ok": {"type": "boolean"},
            "counts": {
                "type": "object",
                "propertyNames": enum(TransactionStatus),
                "additionalProperties": {"type": "integer", "minimum": 1},
            },
            "transactions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["transaction_id", "status", "error_code", "detail", "attempts", "delivery"],
                    "properties": {
                        "transaction_id": {"type": "string", "pattern": TX},
                        "status": enum(TransactionStatus),
                        "error_code": nullable(enum(ErrorCode)),
                        "detail": nullable(tok()),
                        "attempts": {"type": "integer", "minimum": 0},
                        "delivery": enum(DeliveryStatus),
                    },
                },
            },
        },
    }
    return {
        "selectors-1.1.0.schema.json": selectors,
        "events-1.1.0.schema.json": events,
        "checkpoint-1.1.0.schema.json": checkpoint,
        "result-1.1.0.schema.json": result,
        "run-summary-1.1.0.schema.json": summary,
    }


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas().items():
        (OUT / name).write_text(render(schema), encoding="utf-8", newline="\n")
    print("\n".join(sorted(schemas())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
