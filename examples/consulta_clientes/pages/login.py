"""Tela de login do sistema de clientes (laboratório)."""

from __future__ import annotations

from nekkora_rpa import Secret
from nekkora_rpa.modules import LoginKeys, LoginModule
from nekkora_rpa.pages import BasePage


class LoginPage(BasePage):
    prefix = "clientes.login"
    identity = "entrar"

    def entrar(self, usuario: Secret, senha: Secret) -> None:
        LoginModule(
            self.act,
            LoginKeys(
                user=self.k("usuario"),
                password=self.k("senha"),
                submit=self.k("entrar"),
                success="clientes.consulta.titulo",
                failure=self.k("erro"),
            ),
            step_prefix="CLI-LOGIN",
        ).login(usuario, senha)
