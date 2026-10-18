"""Consulta de clientes (laboratório): ``python main.py --config config/lab.toml --entrada itens.jsonl --saida out``."""

from nekkora_rpa.cli import run_cli
from processes.consulta import ConsultaClientes

if __name__ == "__main__":
    raise SystemExit(run_cli(ConsultaClientes(), reference_field="codigo", description="Consulta de clientes (LAB)"))
