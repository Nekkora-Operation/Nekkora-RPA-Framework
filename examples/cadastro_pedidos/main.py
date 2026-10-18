"""Cadastro de pedidos (laboratório): ``python main.py --config config/lab.toml --entrada itens.jsonl --saida out``."""

from processes.cadastro import CadastroPedidos

from nekkora_rpa.cli import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli(CadastroPedidos(), reference_field="ref", description="Cadastro de pedidos (LAB)"))
