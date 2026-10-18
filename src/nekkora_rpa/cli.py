"""Runner de linha de comando reutilizável para processos.

Uso típico no ``main.py`` de um projeto::

    from nekkora_rpa.cli import run_cli
    from processes.consulta import ConsultaClientes

    raise SystemExit(run_cli(ConsultaClientes(), reference_field="codigo"))

Parâmetros: ``--config`` (TOML), ``--entrada`` (JSON Lines), ``--saida`` (pasta de resultados), ``--run-dir``
(eventos, checkpoint e resumo), ``--base-url`` (laboratório; vira também a única origem permitida), ``--channel``,
``--visivel``, ``--console``. Credenciais: variáveis ``NK_SECRET_<NOME>`` para os nomes em ``required_secrets``.
A saída padrão recebe só o resumo (códigos), nunca valores.

Códigos de saída: 0 concluído; 1 concluído com falhas; 2 parado; 3 INIT falhou; 4 cancelado; 5 argumentos inválidos.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from .core.config import load_config
from .core.contracts import RpaProcess
from .core.engine import Engine, RunStatus
from .data import JsonDirectoryResultSink, JsonLinesInputProvider
from .errors.exceptions import NekkoraRpaError
from .resilience.timing import CancelToken
from .security.secrets import EnvSecretProvider

EXIT = {
    RunStatus.COMPLETED: 0,
    RunStatus.COMPLETED_WITH_FAILURES: 1,
    RunStatus.STOPPED: 2,
    RunStatus.INIT_FAILED: 3,
    RunStatus.CANCELLED: 4,
}


def build_parser(description: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--entrada", required=True, type=Path, help="itens em JSON Lines")
    ap.add_argument("--saida", required=True, type=Path, help="pasta dos resultados (um arquivo por transação)")
    ap.add_argument("--run-dir", type=Path, help="eventos, checkpoint e resumo (padrão: paths.run_dir)")
    ap.add_argument("--base-url", help="URL do laboratório; passa a ser a única origem permitida")
    ap.add_argument("--channel", choices=["chromium", "chrome"])
    ap.add_argument("--visivel", action="store_true", help="janela do navegador visível")
    ap.add_argument("--console", action="store_true", help="projeção legível dos eventos no stderr")
    return ap


def run_cli(
    process: RpaProcess,
    *,
    reference_field: str,
    description: str | None = None,
    argv: Sequence[str] | None = None,
) -> int:
    args = build_parser(description or process.name).parse_args(argv)
    overrides: dict[str, object] = {}
    if args.base_url:
        overrides["runtime.base_url"] = args.base_url
        overrides["runtime.allowed_origins"] = [args.base_url]
    if args.channel:
        overrides["browser.channel"] = args.channel
    if args.visivel:
        overrides["browser.headless"] = False
    try:
        config = load_config(args.config, overrides)
        cancel = CancelToken()
        signal.signal(signal.SIGINT, lambda *_: cancel.cancel())
        engine = Engine(
            process,
            JsonLinesInputProvider(args.entrada, reference_field=reference_field),
            JsonDirectoryResultSink(args.saida),
            config,
            secrets=EnvSecretProvider(process.required_secrets),
            run_dir=args.run_dir.resolve() if args.run_dir else None,
            console=args.console,
            cancel=cancel,
        )
    except NekkoraRpaError as err:
        print(json.dumps({"status": "INVALID_ARGUMENTS", "error_code": err.code.value, "detail": err.detail}))
        return 5
    summary = engine.run()
    d = summary.to_dict()
    print(json.dumps({k: d[k] for k in ("execution_id", "status", "stop_code", "stop_detail", "counts")}))
    sys.stdout.flush()
    return EXIT[summary.status]
