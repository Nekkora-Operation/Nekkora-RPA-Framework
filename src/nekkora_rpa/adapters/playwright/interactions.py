"""Interações Playwright com classificação de desfecho.

A pergunta que decide a classificação é: **a operação pode ter sido despachada?**
- Clique: antes do clique real roda o *trial* do Playwright (mesmas verificações de actionability, sem clicar). Falha
  no trial = comprovadamente não clicou → falha transitória (``TARGET_NOT_READY``/``TARGET_DETACHED``...). Falha
  DEPOIS de iniciado o clique real → ``OUTCOME_UNKNOWN`` (o efeito pode ter acontecido), salvo se o chamador declarou a
  operação idempotente.
- Preenchimento: idempotente por natureza (repetir grava o mesmo valor); o valor é conferido depois.
A classificação usa só o ESTADO observado (página fechada? nó conectado? visível? habilitado? editável?), nunca o texto
da mensagem do Playwright.
"""

from __future__ import annotations

from playwright.sync_api import ElementHandle, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ...errors.codes import ErrorCode, OutcomeUnknownReason
from ...errors.exceptions import NekkoraRpaError, OutcomeUnknown, external


def _state(handle: ElementHandle) -> dict[str, bool] | None:
    try:
        st: dict[str, bool] = handle.evaluate(
            """e => ({connected: e.isConnected,
                     visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)
                              && getComputedStyle(e).visibility !== 'hidden',
                     disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true',
                     readonly: !!e.readOnly})"""
        )
        return st
    except PlaywrightError:
        return None


def not_performed(
    page: Page, handle: ElementHandle, exc: BaseException, key: str, step_id: str | None
) -> NekkoraRpaError:
    """Erro para uma falha ocorrida ANTES do despacho (o efeito comprovadamente não aconteceu)."""
    if page.is_closed():
        return external(ErrorCode.PAGE_CLOSED, exc, key=key, step_id=step_id)
    st = _state(handle)
    if st is None or not st["connected"]:
        return external(ErrorCode.TARGET_DETACHED, exc, key=key, step_id=step_id)
    if isinstance(exc, PlaywrightTimeout):
        detail = (
            "not_visible"
            if not st["visible"]
            else "disabled"
            if st["disabled"]
            else ("readonly" if st["readonly"] else "not_actionable")
        )
        err = external(ErrorCode.TARGET_NOT_READY, exc, key=key, step_id=step_id)
        err.detail = detail
        return err
    return external(ErrorCode.TRANSIENT_TECHNICAL_FAILURE, exc, key=key, step_id=step_id)


def after_dispatch(
    page: Page, handle: ElementHandle, exc: BaseException, key: str, step_id: str | None, idempotent: bool
) -> NekkoraRpaError:
    """Erro para uma falha ocorrida depois de iniciado o despacho."""
    if idempotent:
        return not_performed(page, handle, exc, key, step_id)
    return OutcomeUnknown(
        OutcomeUnknownReason.ACTION_INTERRUPTED, key=key, step_id=step_id, cause_type=type(exc).__name__
    )


def click(handle: ElementHandle, *, click_count: int, timeout_ms: int, trial: bool) -> None:
    if click_count == 2:
        handle.dblclick(timeout=timeout_ms, trial=trial)
    else:
        handle.click(timeout=timeout_ms, trial=trial)


def fill(handle: ElementHandle, value: str, *, timeout_ms: int) -> None:
    handle.fill(value, timeout=timeout_ms)


def read_value(handle: ElementHandle, *, timeout_ms: int) -> str:
    tag = handle.evaluate("e => e.tagName.toLowerCase()")
    if tag in ("input", "textarea", "select"):
        return handle.input_value(timeout=timeout_ms)
    return handle.inner_text()
