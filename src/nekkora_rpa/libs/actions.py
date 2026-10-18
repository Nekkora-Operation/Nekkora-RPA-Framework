"""API pública de ações: ``click``, ``double_click``, ``fill``, ``wait_visible``, ``wait_hidden``, ``exists``,
``is_visible``, ``read_text``, ``navigate`` e ``expect_new_page``.

Toda ação que depende de elemento recebe a CHAVE do registro (nunca um seletor) e, opcionalmente, ``step_id`` para
rastreabilidade. Cada chamada:
1. valida argumentos (valores inválidos → ``INVALID_ARGUMENT``, nada é feito);
2. calcula um prazo TOTAL (``timeout_ms`` ou o padrão da configuração, limitado pelo que resta da transação);
3. confere a origem da página atual (fora do laboratório → ``SECURITY_POLICY_BLOCKED``, nada é feito);
4. resolve o alvo com identidade (ver ``Resolver``) e age sobre o nó verificado;
5. classifica a falha e só repete o que a política e a classificação permitem;
6. emite eventos ``ACTION_*``/``TARGET_*``/``RETRY_*`` sem valores, textos de página, URLs nem seletores.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, TypeVar
from urllib.parse import urljoin

from playwright.sync_api import ElementHandle, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ..adapters.playwright import interactions
from ..adapters.playwright.browser import BrowserSession
from ..adapters.playwright.resolver import Resolver, build_locator
from ..core.context import ExecutionContext
from ..errors.codes import ErrorCategory, ErrorCode, OutcomeUnknownReason
from ..errors.exceptions import (
    ActionTimeout,
    InvalidArgument,
    NavigationFailed,
    NekkoraRpaError,
    OutcomeUnknown,
    PageClosed,
    SecurityPolicyBlocked,
    TransientTechnicalFailure,
    external,
)
from ..observability.events import EventCode
from ..observability.safety import is_token
from ..resilience.retry import NO_RETRY, RetryDenial, RetryPolicy, run_with_retry
from ..resilience.timing import Deadline, check_timeout_ms
from ..security.secrets import Secret
from ..selectors.registry import SelectorRegistry
from ..selectors.schema import Target

T = TypeVar("T")
Postcondition = Callable[[], bool]
WaitUntil = Literal["load", "domcontentloaded", "networkidle", "commit"]


@dataclass
class NewPage:
    page: Page | None = None


def _remaining(deadline: Deadline, key: str | None, step_id: str | None) -> int:
    """Milissegundos restantes, nunca 0 (no Playwright, 0 = sem prazo)."""
    ms = deadline.remaining_ms()
    if ms <= 0:
        raise ActionTimeout(key=key, step_id=step_id, detail="deadline")
    return ms


class Actions:
    def __init__(
        self,
        ctx: ExecutionContext,
        session: BrowserSession,
        registry: SelectorRegistry,
        *,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.ctx = ctx
        self.session = session
        self.registry = registry
        self.retry = retry if retry is not None else ctx.config.retry
        self._page: Page | None = None
        self._quiet = 0

    # ------------------------------------------------------------------ página corrente
    @property
    def page(self) -> Page:
        page = self._page or self.session.page
        if page is None or page.is_closed():
            raise PageClosed()
        return page

    def use_page(self, page: Page) -> None:
        """Passa a agir em outra aba (p. ex. a aberta por ``expect_new_page``) depois de conferir a origem."""
        if not self.ctx.config.origins.is_allowed(page.url):
            raise SecurityPolicyBlocked(detail="ORIGIN_NOT_ALLOWED")
        self._page = page

    # ------------------------------------------------------------------ infraestrutura comum
    def _emit(self, code: EventCode, **fields: str | int | None) -> None:
        if not self._quiet:
            self.ctx.emit(code, **fields)

    def _check_step(self, step_id: str | None) -> None:
        if step_id is not None and not is_token(step_id):
            raise InvalidArgument(detail="step_id")

    def _timeout(self, timeout_ms: int | None, default: int) -> int:
        return check_timeout_ms(default if timeout_ms is None else timeout_ms)

    def _require_origin(self, page: Page, key: str | None, step_id: str | None) -> None:
        url = page.url
        if self.ctx.config.origins.is_allowed(url):
            return
        if url.startswith(("http://", "https://")):
            raise SecurityPolicyBlocked(key=key, step_id=step_id, detail="ORIGIN_NOT_ALLOWED")
        if page in self.session.blocked_pages:
            # a aba tentou sair do laboratório e foi barrada: o que está nela é a página de erro do navegador
            raise SecurityPolicyBlocked(key=key, step_id=step_id, detail="NAVIGATION_BLOCKED")
        raise NavigationFailed(key=key, step_id=step_id, detail="no_lab_page")

    def _run(
        self,
        action: str,
        key: str | None,
        step_id: str | None,
        deadline: Deadline,
        body: Callable[[int], T],
        *,
        retry: RetryPolicy,
    ) -> T:
        t0 = self.ctx.clock.monotonic()
        last_attempt = 1

        def elapsed() -> int:
            return int((self.ctx.clock.monotonic() - t0) * 1000)

        def attempt(n: int) -> T:
            nonlocal last_attempt
            last_attempt = n
            self.ctx.cancel.raise_if_cancelled(step_id)
            return body(n)

        def scheduled(err: NekkoraRpaError, n: int, delay: int) -> None:
            self._emit(
                EventCode.RETRY_SCHEDULED,
                action=action,
                key=key,
                step_id=step_id,
                attempt=n,
                error_code=err.code.value,
                detail=err.detail,
                delay_ms=delay,
            )

        def denied(err: NekkoraRpaError, n: int, denial: RetryDenial) -> None:
            if retry.max_attempts > 1 or denial is RetryDenial.OUTCOME_UNKNOWN:
                self._emit(
                    EventCode.RETRY_DENIED,
                    action=action,
                    key=key,
                    step_id=step_id,
                    attempt=n,
                    error_code=err.code.value,
                    detail=denial.value,
                )

        self._emit(EventCode.ACTION_STARTED, action=action, key=key, step_id=step_id)
        try:
            result = run_with_retry(
                attempt,
                policy=retry,
                deadline=deadline,
                cancel=self.ctx.cancel,
                clock=self.ctx.clock,
                on_scheduled=scheduled,
                on_denied=denied,
                step_id=step_id,
            )
        except NekkoraRpaError as err:
            if err.key is None:
                err.key = key
            if err.step_id is None:
                err.step_id = step_id
            if err.code in (ErrorCode.TARGET_AMBIGUOUS, ErrorCode.TARGET_IDENTITY_MISMATCH):
                self._emit(
                    EventCode.TARGET_REJECTED, key=key, step_id=step_id, error_code=err.code.value, detail=err.detail
                )
            if err.category is ErrorCategory.SECURITY:
                self._emit(EventCode.SECURITY_BLOCKED, action=action, key=key, step_id=step_id, detail=err.detail)
            self._emit(
                EventCode.ACTION_FAILED,
                action=action,
                key=key,
                step_id=step_id,
                attempt=last_attempt,
                error_code=err.code.value,
                detail=err.detail,
                cause_type=err.cause_type,
                elapsed_ms=elapsed(),
            )
            if err.category is ErrorCategory.UNKNOWN_OUTCOME:
                self._emit(EventCode.OUTCOME_UNKNOWN, action=action, key=key, step_id=step_id, detail=err.detail)
            raise
        self._emit(
            EventCode.ACTION_COMPLETED,
            action=action,
            key=key,
            step_id=step_id,
            attempt=last_attempt,
            elapsed_ms=elapsed(),
            outcome="OK",
        )
        return result

    def _resolve(
        self, page: Page, target: Target, deadline: Deadline, step_id: str | None, *, wait: bool = True
    ) -> ElementHandle | None:
        resolver = Resolver(self.ctx.clock, self.ctx.cancel)
        res = resolver.resolve(page, target, deadline, wait=wait)
        if res is None:
            return None
        self._emit(EventCode.TARGET_RESOLVED, key=target.key, step_id=step_id, strategy_index=res.strategy_index)
        return res.handle

    # ------------------------------------------------------------------ ações sobre elemento
    def click(
        self,
        key: str,
        *,
        timeout_ms: int | None = None,
        mode: str = "pointer",
        click_count: int = 1,
        step_id: str | None = None,
        postcondition: Postcondition | None = None,
        idempotent: bool = False,
    ) -> None:
        """Clique do Playwright na página (``mode="pointer"``; não é o mouse do sistema operacional).

        ``click_count``: 1 (simples) ou 2 (duplo, um único ``dblclick`` efetivo). Não idempotente por padrão: falha
        depois do despacho → ``OUTCOME_UNKNOWN`` e nenhuma repetição. ``postcondition``: verificação objetiva do
        efeito, consultada até o prazo; não confirmada → ``OUTCOME_UNKNOWN`` (``POSTCONDITION_NOT_MET``)."""
        if mode != "pointer":
            raise InvalidArgument(key=key, step_id=step_id, detail="mode")
        if isinstance(click_count, bool) or click_count not in (1, 2):
            raise InvalidArgument(key=key, step_id=step_id, detail="click_count")
        self._element_click(
            "double_click" if click_count == 2 else "click",
            key,
            timeout_ms,
            click_count,
            step_id,
            postcondition,
            idempotent,
        )

    def double_click(
        self,
        key: str,
        *,
        timeout_ms: int | None = None,
        step_id: str | None = None,
        postcondition: Postcondition | None = None,
        idempotent: bool = False,
    ) -> None:
        self._element_click("double_click", key, timeout_ms, 2, step_id, postcondition, idempotent)

    def _element_click(
        self,
        action: str,
        key: str,
        timeout_ms: int | None,
        click_count: int,
        step_id: str | None,
        postcondition: Postcondition | None,
        idempotent: bool,
    ) -> None:
        self._check_step(step_id)
        target = self.registry.get(key)
        if postcondition is not None and not callable(postcondition):
            raise InvalidArgument(key=key, step_id=step_id, detail="postcondition")
        deadline = self.ctx.action_deadline(self._timeout(timeout_ms, self.ctx.config.timeouts.action_ms))

        def body(_: int) -> None:
            page = self.page
            self._require_origin(page, key, step_id)
            handle = self._resolve(page, target, deadline, step_id)
            assert handle is not None
            try:
                try:
                    interactions.click(
                        handle, click_count=click_count, timeout_ms=_remaining(deadline, key, step_id), trial=True
                    )
                except PlaywrightError as exc:
                    raise interactions.not_performed(page, handle, exc, key, step_id) from None
                self._require_origin(page, key, step_id)
                remaining = _remaining(deadline, key, step_id)
                if not idempotent:
                    self.ctx.mark_side_effect()  # daqui em diante o efeito pode ter acontecido
                try:
                    interactions.click(handle, click_count=click_count, timeout_ms=remaining, trial=False)
                except PlaywrightError as exc:
                    raise interactions.after_dispatch(page, handle, exc, key, step_id, idempotent) from None
                if page.is_closed():
                    # achado F3-A1: o Playwright devolve o clique como concluído mesmo se a aba fechou no meio dele
                    raise interactions.after_dispatch(page, handle, PageClosed(), key, step_id, idempotent)
            finally:
                _dispose(handle)
            if postcondition is not None:
                self._await_postcondition(postcondition, deadline, key, step_id, idempotent)

        self._run(action, key, step_id, deadline, body, retry=self.retry)

    def _await_postcondition(
        self, check: Postcondition, deadline: Deadline, key: str, step_id: str | None, idempotent: bool
    ) -> None:
        interval = 0.05
        while True:
            self.ctx.cancel.raise_if_cancelled(step_id)
            self._quiet += 1
            try:
                ok = bool(check())
            except NekkoraRpaError as err:
                if err.category in (ErrorCategory.SECURITY, ErrorCategory.CANCELLED, ErrorCategory.CONFIGURATION):
                    raise
                ok = False
            finally:
                self._quiet -= 1
            if ok:
                return
            if deadline.remaining_ms() <= 0:
                if idempotent:
                    raise ActionTimeout(key=key, step_id=step_id, detail="postcondition_not_met")
                raise OutcomeUnknown(OutcomeUnknownReason.POSTCONDITION_NOT_MET, key=key, step_id=step_id)
            self.ctx.clock.sleep(min(interval, deadline.remaining_ms() / 1000.0), self.ctx.cancel)
            interval = min(interval * 2, 0.25)

    def fill(
        self,
        key: str,
        value: str | Secret,
        *,
        timeout_ms: int | None = None,
        step_id: str | None = None,
        verify: bool = True,
    ) -> None:
        """Preenche o campo verificado. Idempotente (pode ser repetido pela política). Com ``verify``, confere que
        o campo ficou com o valor pedido (a comparação acontece aqui; o valor nunca é registrado)."""
        self._check_step(step_id)
        target = self.registry.get(key)
        if not isinstance(value, (str, Secret)):
            raise InvalidArgument(key=key, step_id=step_id, detail="value_type")
        deadline = self.ctx.action_deadline(self._timeout(timeout_ms, self.ctx.config.timeouts.action_ms))

        def body(_: int) -> None:
            page = self.page
            self._require_origin(page, key, step_id)
            handle = self._resolve(page, target, deadline, step_id)
            assert handle is not None
            try:
                try:
                    interactions.fill(
                        handle,
                        value.reveal() if isinstance(value, Secret) else value,
                        timeout_ms=_remaining(deadline, key, step_id),
                    )
                except PlaywrightError as exc:
                    raise interactions.not_performed(page, handle, exc, key, step_id) from None
                if verify:
                    try:
                        applied = interactions.read_value(handle, timeout_ms=_remaining(deadline, key, step_id)) == (
                            value.reveal() if isinstance(value, Secret) else value
                        )
                    except PlaywrightError as exc:
                        raise interactions.not_performed(page, handle, exc, key, step_id) from None
                    if not applied:
                        raise TransientTechnicalFailure(key=key, step_id=step_id, detail="value_not_applied")
            finally:
                _dispose(handle)

        self._run("fill", key, step_id, deadline, body, retry=self.retry)

    def wait_visible(self, key: str, *, timeout_ms: int | None = None, step_id: str | None = None) -> None:
        """Espera o alvo (com identidade verificada) ficar visível."""
        self._check_step(step_id)
        target = self.registry.get(key)
        deadline = self.ctx.action_deadline(self._timeout(timeout_ms, self.ctx.config.timeouts.action_ms))

        def body(_: int) -> None:
            page = self.page
            self._require_origin(page, key, step_id)
            handle = self._resolve(page, target, deadline, step_id)
            assert handle is not None
            try:
                handle.wait_for_element_state("visible", timeout=_remaining(deadline, key, step_id))
            except PlaywrightTimeout:
                raise ActionTimeout(key=key, step_id=step_id, detail="not_visible", cause_type="TimeoutError") from None
            except PlaywrightError as exc:
                raise interactions.not_performed(page, handle, exc, key, step_id) from None
            finally:
                _dispose(handle)

        self._run("wait_visible", key, step_id, deadline, body, retry=NO_RETRY)

    def wait_hidden(self, key: str, *, timeout_ms: int | None = None, step_id: str | None = None) -> None:
        """Espera não haver nenhum elemento VISÍVEL para nenhum candidato do alvo (ausência não exige identidade)."""
        self._check_step(step_id)
        target = self.registry.get(key)
        deadline = self.ctx.action_deadline(self._timeout(timeout_ms, self.ctx.config.timeouts.action_ms))

        def body(_: int) -> None:
            interval = 0.05
            while True:
                page = self.page
                self._require_origin(page, key, step_id)
                try:
                    visible = sum(build_locator(page, ref).filter(visible=True).count() for ref in target.candidates)
                except PlaywrightError:
                    visible = -1  # página em transição: consulta de novo
                if visible == 0:
                    return
                if deadline.remaining_ms() <= 0:
                    raise ActionTimeout(key=key, step_id=step_id, detail="still_visible")
                self.ctx.clock.sleep(min(interval, deadline.remaining_ms() / 1000.0), self.ctx.cancel)
                interval = min(interval * 2, 0.25)

        self._run("wait_hidden", key, step_id, deadline, body, retry=NO_RETRY)

    def exists(self, key: str, *, step_id: str | None = None) -> bool:
        """Consulta sem espera: ``True`` só com exatamente um elemento de identidade verificada; ``False`` se não
        há nenhum. Ambiguidade e identidade divergente são ERROS (nunca "existe")."""
        self._check_step(step_id)
        target = self.registry.get(key)
        deadline = self.ctx.action_deadline(self.ctx.config.timeouts.action_ms)

        def body(_: int) -> bool:
            page = self.page
            self._require_origin(page, key, step_id)
            handle = self._resolve(page, target, deadline, step_id, wait=False)
            if handle is None:
                return False
            _dispose(handle)
            return True

        return self._run("exists", key, step_id, deadline, body, retry=NO_RETRY)

    def is_visible(self, key: str, *, step_id: str | None = None) -> bool:
        """Consulta sem espera: ``True`` só se o alvo existe, tem identidade verificada e está visível agora.
        Ausente → ``False``; ambíguo ou identidade divergente → erro (nunca "visível")."""
        self._check_step(step_id)
        target = self.registry.get(key)
        deadline = self.ctx.action_deadline(self.ctx.config.timeouts.action_ms)

        def body(_: int) -> bool:
            page = self.page
            self._require_origin(page, key, step_id)
            handle = self._resolve(page, target, deadline, step_id, wait=False)
            if handle is None:
                return False
            try:
                return handle.is_visible()
            except PlaywrightError:
                return False
            finally:
                _dispose(handle)

        return self._run("is_visible", key, step_id, deadline, body, retry=NO_RETRY)

    def read_text(self, key: str, *, timeout_ms: int | None = None, step_id: str | None = None) -> str:
        """Lê o texto (ou o valor, em campos) do alvo verificado. O retorno é do processo: nunca é registrado."""
        self._check_step(step_id)
        target = self.registry.get(key)
        deadline = self.ctx.action_deadline(self._timeout(timeout_ms, self.ctx.config.timeouts.action_ms))

        def body(_: int) -> str:
            page = self.page
            self._require_origin(page, key, step_id)
            handle = self._resolve(page, target, deadline, step_id)
            assert handle is not None
            try:
                return interactions.read_value(handle, timeout_ms=_remaining(deadline, key, step_id))
            except PlaywrightError as exc:
                raise interactions.not_performed(page, handle, exc, key, step_id) from None
            finally:
                _dispose(handle)

        return self._run("read_text", key, step_id, deadline, body, retry=self.retry)

    # ------------------------------------------------------------------ navegação
    def navigate(
        self,
        url: str,
        *,
        timeout_ms: int | None = None,
        step_id: str | None = None,
        wait_until: WaitUntil = "load",
        idempotent: bool = True,
    ) -> None:
        """Navega para ``url`` (absoluta ou relativa à ``base_url``). O destino é conferido ANTES de qualquer
        requisição; redirecionamento para fora da allowlist é bloqueado na rede e vira ``SECURITY_POLICY_BLOCKED``.
        GET é tratado como idempotente; ``idempotent=False`` faz falha depois do despacho virar ``OUTCOME_UNKNOWN``.
        A URL nunca é registrada (pode conter dados)."""
        self._check_step(step_id)
        if not isinstance(url, str) or wait_until not in ("load", "domcontentloaded", "networkidle", "commit"):
            raise InvalidArgument(step_id=step_id, detail="url" if not isinstance(url, str) else "wait_until")
        absolute = urljoin(self.ctx.config.base_url, url)
        deadline = self.ctx.action_deadline(self._timeout(timeout_ms, self.ctx.config.timeouts.navigation_ms))

        def body(_: int) -> None:
            if not self.ctx.config.origins.is_allowed(absolute):
                raise SecurityPolicyBlocked(step_id=step_id, detail="ORIGIN_NOT_ALLOWED")
            page = self.page
            before = self.session.blocked_navigations
            if not idempotent:
                self.ctx.mark_side_effect()
            try:
                response = page.goto(absolute, timeout=_remaining(deadline, None, step_id), wait_until=wait_until)
            except PlaywrightError as exc:
                if self.session.blocked_navigations > before:
                    raise SecurityPolicyBlocked(
                        step_id=step_id, detail="REDIRECT_BLOCKED", cause_type=type(exc).__name__
                    ) from None
                if page.is_closed():
                    raise external(ErrorCode.PAGE_CLOSED, exc, step_id=step_id) from None
                if not idempotent:
                    raise OutcomeUnknown(
                        OutcomeUnknownReason.ACTION_INTERRUPTED, step_id=step_id, cause_type=type(exc).__name__
                    ) from None
                raise external(ErrorCode.NAVIGATION_FAILED, exc, step_id=step_id) from None
            if self.session.blocked_navigations > before or not self.ctx.config.origins.is_allowed(page.url):
                raise SecurityPolicyBlocked(step_id=step_id, detail="REDIRECT_BLOCKED")
            if response is not None and response.status >= 400:
                raise NavigationFailed(step_id=step_id, detail="http_5xx" if response.status >= 500 else "http_4xx")

        self._run("navigate", None, step_id, deadline, body, retry=self.retry if idempotent else NO_RETRY)

    @contextmanager
    def expect_new_page(self, *, timeout_ms: int | None = None, step_id: str | None = None) -> Iterator[NewPage]:
        """``with actions.expect_new_page() as nova: actions.click(...)`` → ``nova.page`` é a aba aberta pelo clique
        (ainda NÃO usada: chame ``use_page``, que confere a origem)."""
        self._check_step(step_id)
        ms = self._timeout(timeout_ms, self.ctx.config.timeouts.action_ms)
        holder = NewPage()
        with self.session.context.expect_page(timeout=ms) as info:
            yield holder
        try:
            page = info.value
            page.wait_for_load_state("domcontentloaded", timeout=ms)
        except PlaywrightError as exc:
            raise external(ErrorCode.ACTION_TIMEOUT, exc, step_id=step_id) from None
        holder.page = page


def _dispose(handle: object) -> None:
    try:
        handle.dispose()  # type: ignore[attr-defined]
    except PlaywrightError:
        pass
