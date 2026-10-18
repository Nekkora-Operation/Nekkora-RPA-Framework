"""Tela de consulta de clientes: preenche o código, consulta e interpreta o resultado."""

from __future__ import annotations

from dataclasses import dataclass

from nekkora_rpa.errors import BusinessRuleRejected, TransientTechnicalFailure
from nekkora_rpa.pages import BasePage


@dataclass(frozen=True)
class Cliente:
    nome: str
    situacao: str


class ConsultaPage(BasePage):
    prefix = "clientes.consulta"
    identity = "titulo"
    FINS = ("resultado", "nao_encontrado", "erro_servico")

    def _concluiu(self) -> bool:
        return any(self.act.is_visible(self.k(f)) for f in self.FINS)

    def consultar(self, codigo: str) -> Cliente:
        self.act.fill(self.k("codigo"), codigo, step_id="CON-01")
        # consulta é só leitura: o clique pode ser repetido pela política sem efeito colateral
        self.act.click(self.k("consultar"), step_id="CON-02", idempotent=True, postcondition=self._concluiu)
        if self.act.is_visible(self.k("resultado"), step_id="CON-03"):
            return Cliente(
                nome=self.act.read_text(self.k("nome"), step_id="CON-04"),
                situacao=self.act.read_text(self.k("situacao"), step_id="CON-05"),
            )
        if self.act.is_visible(self.k("nao_encontrado"), step_id="CON-03"):
            raise BusinessRuleRejected("CLIENTE_INEXISTENTE", step_id="CON-03")
        raise TransientTechnicalFailure(step_id="CON-03", detail="servico_indisponivel")
