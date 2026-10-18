"""Tela "Pedidos por referência": usada só para LER o estado do sistema na reconciliação."""

from __future__ import annotations

from nekkora_rpa.pages import BasePage


class ListaPedidosPage(BasePage):
    prefix = "pedidos.lista"
    identity = "titulo"
    FINS = ("resultado", "vazia", "erro")

    def abrir(self) -> None:
        self.act.navigate("/pedidos/lista.html", step_id="LIS-00")
        self.wait_loaded(step_id="LIS-00")

    def protocolos(self, referencia: str) -> list[str] | None:
        """Protocolos registrados para a referência; ``None`` se a lista não pôde ser lida."""
        self.act.fill(self.k("referencia"), referencia, step_id="LIS-01")
        self.act.click(
            self.k("buscar"), step_id="LIS-02", idempotent=True,
            postcondition=lambda: any(self.act.is_visible(self.k(f)) for f in self.FINS),
        )
        if self.act.is_visible(self.k("vazia"), step_id="LIS-03"):
            return []
        if self.act.is_visible(self.k("resultado"), step_id="LIS-03"):
            return [p for p in self.act.read_text(self.k("protocolos"), step_id="LIS-04").split() if p]
        return None
