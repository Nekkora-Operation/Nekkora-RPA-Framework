"""Hierarquia pública de exceções.

Regras:
- ``str(erro)`` é só o código (e o motivo enumerado, quando houver). Nunca valores, texto de página, URL ou mensagem
  de biblioteca externa.
- A exceção externa que originou a falha **não** é encadeada (``__cause__``/``__context__``): um traceback impresso
  pelo processo não pode carregar a mensagem do Playwright (que pode conter seletor, URL ou trecho do DOM). Fica só o
  nome do tipo externo em ``cause_type``.
- ``key`` (chave do registro de alvos) e ``step_id`` são identificadores escolhidos pelo desenvolvedor e validados por
  padrão; podem ir para eventos.
"""

from __future__ import annotations

from .codes import CATEGORY, ErrorCategory, ErrorCode, OutcomeUnknownReason


class NekkoraRpaError(Exception):
    """Base de todas as falhas do framework."""

    code: ErrorCode = ErrorCode.UNEXPECTED_ERROR

    def __init__(
        self,
        code: ErrorCode | None = None,
        *,
        key: str | None = None,
        step_id: str | None = None,
        cause_type: str | None = None,
        detail: str | None = None,
    ) -> None:
        if code is not None:
            self.code = code
        self.key = key
        self.step_id = step_id
        self.cause_type = cause_type
        # detalhe técnico ENUMERADO (ex.: campo de identidade que divergiu, "name"); nunca valor livre
        self.detail = detail
        super().__init__(self.code.value)
        self.__suppress_context__ = True

    @property
    def category(self) -> ErrorCategory:
        return CATEGORY[self.code]

    def __str__(self) -> str:
        return self.code.value if self.detail is None else f"{self.code.value}:{self.detail}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self})"


class TargetNotFound(NekkoraRpaError):
    code = ErrorCode.TARGET_NOT_FOUND


class TargetAmbiguous(NekkoraRpaError):
    code = ErrorCode.TARGET_AMBIGUOUS


class TargetIdentityMismatch(NekkoraRpaError):
    code = ErrorCode.TARGET_IDENTITY_MISMATCH


class TargetNotReady(NekkoraRpaError):
    code = ErrorCode.TARGET_NOT_READY


class TargetDetached(NekkoraRpaError):
    code = ErrorCode.TARGET_DETACHED


class ActionTimeout(NekkoraRpaError):
    code = ErrorCode.ACTION_TIMEOUT


class NavigationFailed(NekkoraRpaError):
    code = ErrorCode.NAVIGATION_FAILED


class PageClosed(NekkoraRpaError):
    code = ErrorCode.PAGE_CLOSED


class TransientTechnicalFailure(NekkoraRpaError):
    code = ErrorCode.TRANSIENT_TECHNICAL_FAILURE


class BusinessRuleRejected(NekkoraRpaError):
    """Lançada pelo processo quando uma regra de negócio recusa o item. ``reason`` deve ser um código do processo
    (ex.: ``CLIENTE_INEXISTENTE``), nunca um valor do item."""

    code = ErrorCode.BUSINESS_RULE_REJECTED

    def __init__(self, reason: str, *, step_id: str | None = None) -> None:
        from ..observability.safety import require_token

        super().__init__(step_id=step_id, detail=require_token(reason, "reason"))
        self.reason = reason


class OutcomeUnknown(NekkoraRpaError):
    code = ErrorCode.OUTCOME_UNKNOWN

    def __init__(
        self,
        reason: OutcomeUnknownReason,
        *,
        key: str | None = None,
        step_id: str | None = None,
        cause_type: str | None = None,
    ) -> None:
        super().__init__(key=key, step_id=step_id, cause_type=cause_type, detail=reason.value)
        self.reason = reason


class SecurityPolicyBlocked(NekkoraRpaError):
    code = ErrorCode.SECURITY_POLICY_BLOCKED


class InvalidConfiguration(NekkoraRpaError):
    code = ErrorCode.INVALID_CONFIGURATION


class InvalidArgument(NekkoraRpaError):
    code = ErrorCode.INVALID_ARGUMENT


class SecretUnavailable(NekkoraRpaError):
    code = ErrorCode.SECRET_UNAVAILABLE


class CheckpointCorrupted(NekkoraRpaError):
    code = ErrorCode.CHECKPOINT_CORRUPTED


class CheckpointWriteFailed(NekkoraRpaError):
    code = ErrorCode.CHECKPOINT_WRITE_FAILED


class InputProviderFailed(NekkoraRpaError):
    code = ErrorCode.INPUT_PROVIDER_FAILED


class TransactionDeadlineExceeded(NekkoraRpaError):
    code = ErrorCode.TRANSACTION_DEADLINE_EXCEEDED


class Cancelled(NekkoraRpaError):
    code = ErrorCode.CANCELLED


def external(
    code: ErrorCode, exc: BaseException, *, key: str | None = None, step_id: str | None = None
) -> NekkoraRpaError:
    """Encapsula uma exceção externa num erro do framework guardando só o nome do tipo."""
    cls = _BY_CODE.get(code)
    if cls is None:
        return NekkoraRpaError(code, key=key, step_id=step_id, cause_type=type(exc).__name__)
    return cls(key=key, step_id=step_id, cause_type=type(exc).__name__)


_BY_CODE: dict[ErrorCode, type[NekkoraRpaError]] = {
    ErrorCode.TARGET_NOT_FOUND: TargetNotFound,
    ErrorCode.TARGET_AMBIGUOUS: TargetAmbiguous,
    ErrorCode.TARGET_IDENTITY_MISMATCH: TargetIdentityMismatch,
    ErrorCode.TARGET_NOT_READY: TargetNotReady,
    ErrorCode.TARGET_DETACHED: TargetDetached,
    ErrorCode.ACTION_TIMEOUT: ActionTimeout,
    ErrorCode.NAVIGATION_FAILED: NavigationFailed,
    ErrorCode.PAGE_CLOSED: PageClosed,
    ErrorCode.TRANSIENT_TECHNICAL_FAILURE: TransientTechnicalFailure,
    ErrorCode.SECURITY_POLICY_BLOCKED: SecurityPolicyBlocked,
    ErrorCode.INVALID_CONFIGURATION: InvalidConfiguration,
    ErrorCode.INVALID_ARGUMENT: InvalidArgument,
    ErrorCode.CANCELLED: Cancelled,
}
