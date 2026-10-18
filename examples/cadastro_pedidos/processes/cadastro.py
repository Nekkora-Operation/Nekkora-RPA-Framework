"""Processo: registrar pedidos (efeito colateral) a partir de uma lista, sem duplicar.

- Validação de negócio ANTES de qualquer ação (quantidade, campos obrigatórios).
- A confirmação (duplo clique) é a única ação não idempotente; se o desfecho ficar desconhecido (queda de
  comunicação, página que não confirma), o engine NÃO repete: chama ``reconcile``, que lê a lista de pedidos pela
  referência — 1 pedido → feito (devolve o protocolo); nenhum → não feito (pode tentar de novo); outro caso → revisão.
"""

from __future__ import annotations

from pages.acesso import AcessoPage
from pages.lista_pedidos import ListaPedidosPage
from pages.novo_pedido import NovoPedidoPage

from nekkora_rpa import ProcessResult, Reconciliation, ReconciliationVerdict, RpaProcess, Runtime, TransactionItem
from nekkora_rpa.errors import BusinessRuleRejected, InvalidConfiguration


class CadastroPedidos(RpaProcess):
    name = "cadastro_pedidos"
    required_secrets = ("pedidos.usuario", "pedidos.senha")

    def init(self, rt: Runtime) -> None:
        if rt.secrets is None:
            raise InvalidConfiguration(detail="secret_provider_missing")
        rt.act.navigate("/pedidos/login.html", step_id="INIT-01")
        AcessoPage(rt.act).acessar(rt.secrets.get("pedidos.usuario"), rt.secrets.get("pedidos.senha"))
        self.novo = NovoPedidoPage(rt.act)
        self.lista = ListaPedidosPage(rt.act)
        self.novo.wait_loaded(step_id="INIT-02")

    def process(self, rt: Runtime, item: TransactionItem) -> ProcessResult:
        d = item.data
        produto, quantidade, observacao = d.get("produto"), d.get("quantidade"), d.get("observacao", "")
        if not isinstance(produto, str) or not produto.strip():
            raise BusinessRuleRejected("PRODUTO_AUSENTE")
        if isinstance(quantidade, bool) or not isinstance(quantidade, int) or not 1 <= quantidade <= 99:
            raise BusinessRuleRejected("QUANTIDADE_INVALIDA")
        if not isinstance(observacao, str):
            raise BusinessRuleRejected("OBSERVACAO_INVALIDA")
        self.novo.preparar()
        protocolo = self.novo.registrar(item.reference, produto, quantidade, observacao)
        return ProcessResult({"referencia": item.reference, "protocolo": protocolo})

    def recover(self, rt: Runtime) -> None:
        rt.act.navigate("/pedidos/novo.html", step_id="REC-01")
        self.novo.wait_loaded(step_id="REC-02")

    def reconcile(self, rt: Runtime, item: TransactionItem) -> Reconciliation:
        self.lista.abrir()
        protocolos = self.lista.protocolos(item.reference)
        if protocolos == []:
            return Reconciliation(ReconciliationVerdict.NOT_DONE)
        if protocolos is not None and len(protocolos) == 1:
            return Reconciliation(
                ReconciliationVerdict.DONE,
                ProcessResult({"referencia": item.reference, "protocolo": protocolos[0], "reconciliado": True}),
            )
        return Reconciliation(ReconciliationVerdict.UNKNOWN)  # lista ilegível ou mais de um pedido: revisão humana
