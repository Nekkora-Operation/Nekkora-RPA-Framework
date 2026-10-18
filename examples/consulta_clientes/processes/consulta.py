"""Processo: consultar uma lista de clientes por código e registrar nome e situação.

Somente leitura (nenhuma ação com efeito colateral): falhas técnicas podem ser tentadas de novo pelo engine e a
reconciliação de uma execução interrompida é sempre "não feito" (repetir a consulta não muda nada no sistema).
"""

from __future__ import annotations

import re

from pages.consulta import ConsultaPage
from pages.login import LoginPage

from nekkora_rpa import ProcessResult, Reconciliation, ReconciliationVerdict, RpaProcess, Runtime, TransactionItem
from nekkora_rpa.errors import BusinessRuleRejected, InvalidConfiguration

CODIGO = re.compile(r"^C-\d{4}$")


class ConsultaClientes(RpaProcess):
    name = "consulta_clientes"
    required_secrets = ("clientes.usuario", "clientes.senha")

    def init(self, rt: Runtime) -> None:
        if rt.secrets is None:
            raise InvalidConfiguration(detail="secret_provider_missing")
        rt.act.navigate("/clientes/login.html", step_id="INIT-01")
        LoginPage(rt.act).entrar(rt.secrets.get("clientes.usuario"), rt.secrets.get("clientes.senha"))
        self.consulta = ConsultaPage(rt.act)
        self.consulta.wait_loaded(step_id="INIT-02")

    def process(self, rt: Runtime, item: TransactionItem) -> ProcessResult:
        codigo = item.data.get("codigo")
        if not isinstance(codigo, str) or not CODIGO.fullmatch(codigo):
            raise BusinessRuleRejected("CODIGO_INVALIDO")
        cliente = self.consulta.consultar(codigo)
        return ProcessResult({"codigo": codigo, "nome": cliente.nome, "situacao": cliente.situacao})

    def recover(self, rt: Runtime) -> None:
        rt.act.navigate("/clientes/consulta.html", step_id="REC-01")
        self.consulta.wait_loaded(step_id="REC-02")

    def reconcile(self, rt: Runtime, item: TransactionItem) -> Reconciliation:
        return Reconciliation(ReconciliationVerdict.NOT_DONE)
