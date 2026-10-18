"""Sessão de navegador controlada pelo framework.

- Lança Chromium do Playwright (``channel="chromium"``) ou o Chrome instalado (``channel="chrome"``).
- Contexto novo e isolado (sem perfil do usuário, sem downloads aceitos).
- Guarda de origem em DUAS camadas, ambas antes de a requisição sair:
  1. rede: o navegador recebe um proxy "sumidouro" (porta reservada por este processo, que recusa conexões) e só as
     origens permitidas ficam fora do proxy (``<-loopback>`` primeiro, para o loopback também passar pelo proxy).
     É esta camada que pega REDIRECIONAMENTOS: o roteamento do Playwright só vê o primeiro URL de um redirecionamento
     (achado F0-A10: um 302 para outra origem chegava ao destino);
  2. roteamento do contexto: navegação, recurso e aba nova para origem fora da lista são abortados com contagem.
  Toda requisição observada para fora da lista (inclusive saltos de redirecionamento) é contada em
  ``blocked_navigations``/``blocked_requests`` para ``navigate`` distinguir "bloqueado" de "falha de rede".
- Transporte de TENTATIVA ÚNICA para métodos não idempotentes (POST, PUT, PATCH, DELETE...): a requisição é feita
  uma vez por um cliente HTTP do Playwright SEM proxy (só para origens permitidas, sem seguir redirecionamento, com
  os cookies do contexto) e a resposta — inclusive ``Set-Cookie`` — é entregue à página. Achado F9-A2: o
  Chromium reenvia, sem avisar a página, um POST cuja conexão keep-alive reutilizada caiu sem resposta — o servidor
  recebe DUAS vezes e a página vê sucesso. Com a guarda, a queda chega à página como erro de rede (desfecho
  desconhecido → reconciliação), nunca como uma segunda gravação. GET/HEAD/OPTIONS seguem pela pilha do navegador.
- Prazos padrão finitos no contexto (nenhuma operação do Playwright fica sem timeout).
- ``close()`` é idempotente e relata falha de limpeza sem esconder a falha original de quem chamou.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from types import TracebackType
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import (
    APIRequestContext,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Request,
    Route,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError

from ...core.config import BrowserConfig, Timeouts
from ...security.origins import OriginPolicy

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class BrowserSession:
    def __init__(self, browser_config: BrowserConfig, origins: OriginPolicy, timeouts: Timeouts) -> None:
        self.browser_config = browser_config
        self.origins = origins
        self.timeouts = timeouts
        self.blocked_requests = 0
        self.blocked_navigations = 0
        self.transport_failures = 0
        """Requisições não idempotentes cuja conexão falhou (entregues à página como erro, nunca repetidas)."""
        self.blocked_pages: list[Page] = []
        """Abas cuja navegação foi bloqueada (a aba fica numa página de erro do navegador, fora do laboratório)."""
        self._pw_cm: object | None = None
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._api: APIRequestContext | None = None
        self.page: Page | None = None
        self._sink: socket.socket | None = None

    def _proxy(self) -> dict[str, str]:
        # porta reservada sem listen(): conexões ao "proxy" são recusadas enquanto a sessão existir
        sink = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sink.bind(("127.0.0.1", 0))
        self._sink = sink
        bypass = ["<-loopback>"]
        for origin in sorted(self.origins.allowed):
            parts = urlsplit(origin)
            bypass.append(f"{parts.scheme}://{parts.netloc}")
        return {"server": f"http://127.0.0.1:{sink.getsockname()[1]}", "bypass": ",".join(bypass)}

    def start(self) -> Page:
        cm = sync_playwright()
        self._pw_cm = cm
        self._pw = cm.start()
        kwargs: dict[str, object] = {"headless": self.browser_config.headless, "proxy": self._proxy()}
        if self.browser_config.channel == "chrome":
            kwargs["channel"] = "chrome"
        self._browser = self._pw.chromium.launch(**kwargs)  # type: ignore[arg-type]
        self._context = self._browser.new_context(
            accept_downloads=self.browser_config.accept_downloads, service_workers="block"
        )
        self._context.set_default_timeout(self.timeouts.action_ms)
        self._context.set_default_navigation_timeout(self.timeouts.navigation_ms)
        self._context.route("**/*", self._guard)
        self._context.on("request", self._observe)
        # cliente da guarda de transporte: sem proxy e sem cookie próprio (os do contexto são enviados a cada chamada)
        self._api = self._pw.request.new_context()
        self.page = self._context.new_page()
        return self.page

    def _guard(self, route: Route) -> None:
        request = route.request
        if not self.origins.is_allowed(request.url):
            self._count_blocked(request)
            route.abort("blockedbyclient")
            return
        if request.method.upper() in SAFE_METHODS:
            route.continue_()
            return
        assert self._api is not None and self._context is not None
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("cookie", "host", "content-length")}
        cookies = "; ".join(f"{c['name']}={c['value']}" for c in self._context.cookies(request.url))
        if cookies:
            headers["cookie"] = cookies
        try:
            response = self._api.fetch(
                request.url,
                method=request.method,
                headers=headers,
                data=request.post_data_buffer,
                max_redirects=0,
                fail_on_status_code=False,
                timeout=self.timeouts.navigation_ms,
            )
            body = response.body()
        except PlaywrightError:
            # uma única tentativa: a página recebe erro de rede (desfecho desconhecido), nunca uma 2ª gravação
            self.transport_failures += 1
            route.abort("connectionfailed")
            return
        location = response.headers.get("location")
        if 300 <= response.status < 400 and location and not self.origins.is_allowed(urljoin(request.url, location)):
            self._count_blocked(request)
            route.abort("blockedbyclient")
            return
        route.fulfill(status=response.status, headers=response.headers, body=body)

    def _observe(self, request: Request) -> None:
        # vê também os saltos de redirecionamento (que o roteamento não vê); a camada de rede já os impediu de sair
        if request.redirected_from is not None and not self.origins.is_allowed(request.url):
            self._count_blocked(request)

    def _count_blocked(self, request: Request) -> None:
        self.blocked_requests += 1
        if request.is_navigation_request():
            self.blocked_navigations += 1
            try:
                page = request.frame.page
            except PlaywrightError:
                return
            if page not in self.blocked_pages:
                self.blocked_pages.append(page)

    @property
    def context(self) -> BrowserContext:
        assert self._context is not None
        return self._context

    def close(self) -> bool:
        """Fecha tudo o que esta sessão abriu. Devolve ``False`` se alguma parte falhou ao fechar."""
        ok = True
        closers: list[Callable[[], None]] = []
        if self._api is not None:
            closers.append(self._api.dispose)
        if self._context is not None:
            closers.append(self._context.close)
        if self._browser is not None:
            closers.append(self._browser.close)
        if self._pw is not None:
            closers.append(self._pw.stop)
        for closer in closers:
            try:
                closer()
            except (PlaywrightError, OSError, RuntimeError):
                ok = False
        if self._sink is not None:
            self._sink.close()
            self._sink = None
        self._api = None
        self._context = None
        self._browser = None
        self._pw = None
        self.page = None
        return ok

    def __enter__(self) -> BrowserSession:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
