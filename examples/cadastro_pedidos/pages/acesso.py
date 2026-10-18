"""Tela de acesso do operador (sistema de pedidos). Mesmo Module de login do framework, chaves diferentes."""

from __future__ import annotations

from nekkora_rpa import Secret
from nekkora_rpa.modules import LoginKeys, LoginModule
from nekkora_rpa.pages import BasePage


class AcessoPage(BasePage):
    prefix = "pedidos.login"
    identity = "acessar"

    def acessar(self, usuario: Secret, senha: Secret) -> None:
        LoginModule(
            self.act,
            LoginKeys(
                user=self.k("usuario"),
                password=self.k("senha"),
                submit=self.k("acessar"),
                success="pedidos.novo.titulo",
                failure=self.k("erro"),
            ),
            step_prefix="PED-LOGIN",
        ).login(usuario, senha)
