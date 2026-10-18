"""Tela "Novo pedido": formulário, revisão e confirmação por DUPLO clique (ação com efeito colateral)."""

from __future__ import annotations

from nekkora_rpa.errors import BusinessRuleRejected, TransientTechnicalFailure
from nekkora_rpa.modules import FormModule
from nekkora_rpa.observability.safety import is_token
from nekkora_rpa.pages import BasePage

FINS = ("protocolo", "erro_negocio", "erro_servico", "erro_comunicacao")


class NovoPedidoPage(BasePage):
    prefix = "pedidos.novo"
    identity = "titulo"

    def preparar(self) -> None:
        """Garante o formulário vazio na tela de novo pedido."""
        if not self.is_current():
            self.act.navigate("/pedidos/novo.html", step_id="NOV-00")
            self.wait_loaded(step_id="NOV-00")
        elif self.act.is_visible(self.k("novo")):
            self.act.click(self.k("novo"), step_id="NOV-00", idempotent=True)

    def registrar(self, referencia: str, produto: str, quantidade: int, observacao: str) -> str:
        FormModule(self.act, step_prefix="NOV-F").fill(
            [
                (self.k("referencia"), referencia),
                (self.k("produto"), produto),
                (self.k("quantidade"), str(quantidade)),
                (self.k("observacao"), observacao),
            ]
        )
        self.act.click(
            self.k("revisar"), step_id="NOV-01", idempotent=True,
            postcondition=lambda: self.act.is_visible(self.k("revisao")),
        )
        # efeito colateral: cria o pedido. NÃO idempotente → nunca repetido automaticamente
        self.act.double_click(
            self.k("confirmar"), step_id="NOV-02", timeout_ms=10_000,
            postcondition=lambda: any(self.act.is_visible(self.k(f)) for f in FINS),
        )
        if self.act.is_visible(self.k("protocolo"), step_id="NOV-03"):
            return self.act.read_text(self.k("protocolo"), step_id="NOV-03")
        if self.act.is_visible(self.k("erro_negocio"), step_id="NOV-03"):
            codigo = self.act.read_text(self.k("erro_negocio"), step_id="NOV-03")
            raise BusinessRuleRejected(codigo if is_token(codigo) else "PEDIDO_RECUSADO", step_id="NOV-03")
        if self.act.is_visible(self.k("erro_servico"), step_id="NOV-03"):
            raise TransientTechnicalFailure(step_id="NOV-03", detail="servico_indisponivel")
        raise TransientTechnicalFailure(step_id="NOV-03", detail="comunicacao")
