"""Consulta de clientes (laboratório): ``python main.py --config config/lab.toml --entrada itens.jsonl --saida out``."""

from processes.consulta import ConsultaClientes

from nekkora_rpa.cli import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli(ConsultaClientes(), reference_field="codigo", description="Consulta de clientes (LAB)"))
