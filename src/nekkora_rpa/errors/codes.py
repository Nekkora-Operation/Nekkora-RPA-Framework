"""Códigos de erro estáveis e sua classificação.

O código é o contrato público de uma falha: é o que vai para eventos, checkpoints e resultados. Mensagens de
bibliotecas externas nunca são usadas no lugar dele.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    """Natureza da falha. É a categoria (e não o tipo Python) que governa retentativa e continuidade do lote."""

    TRANSIENT_TECHNICAL = "TRANSIENT_TECHNICAL"
    """Falha técnica que pode passar sozinha; a operação comprovadamente não foi executada (ou é idempotente)."""
    PERMANENT_TECHNICAL = "PERMANENT_TECHNICAL"
    """Falha técnica que não passa com o tempo (alvo errado, ambíguo, página fechada)."""
    BUSINESS = "BUSINESS"
    """Regra de negócio recusou o item. Nunca repetir."""
    SECURITY = "SECURITY"
    """Política de segurança bloqueou. Nunca repetir; interrompe a execução."""
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    """Não se sabe se o efeito aconteceu. Nunca repetir automaticamente; exige reconciliação."""
    CONFIGURATION = "CONFIGURATION"
    """Configuração, contrato ou argumento inválido. Nunca repetir; interrompe a execução."""
    CANCELLED = "CANCELLED"
    """Cancelamento pedido. Nunca repetir."""


class ErrorCode(StrEnum):
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    TARGET_IDENTITY_MISMATCH = "TARGET_IDENTITY_MISMATCH"
    TARGET_NOT_READY = "TARGET_NOT_READY"
    TARGET_DETACHED = "TARGET_DETACHED"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    NAVIGATION_FAILED = "NAVIGATION_FAILED"
    PAGE_CLOSED = "PAGE_CLOSED"
    TRANSIENT_TECHNICAL_FAILURE = "TRANSIENT_TECHNICAL_FAILURE"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
    BUSINESS_RULE_REJECTED = "BUSINESS_RULE_REJECTED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    SECURITY_POLICY_BLOCKED = "SECURITY_POLICY_BLOCKED"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SECRET_UNAVAILABLE = "SECRET_UNAVAILABLE"
    CHECKPOINT_CORRUPTED = "CHECKPOINT_CORRUPTED"
    CHECKPOINT_WRITE_FAILED = "CHECKPOINT_WRITE_FAILED"
    INPUT_PROVIDER_FAILED = "INPUT_PROVIDER_FAILED"
    TRANSACTION_DEADLINE_EXCEEDED = "TRANSACTION_DEADLINE_EXCEEDED"
    CANCELLED = "CANCELLED"


CATEGORY: dict[ErrorCode, ErrorCategory] = {
    ErrorCode.TARGET_NOT_FOUND: ErrorCategory.TRANSIENT_TECHNICAL,
    ErrorCode.TARGET_AMBIGUOUS: ErrorCategory.PERMANENT_TECHNICAL,
    ErrorCode.TARGET_IDENTITY_MISMATCH: ErrorCategory.PERMANENT_TECHNICAL,
    ErrorCode.TARGET_NOT_READY: ErrorCategory.TRANSIENT_TECHNICAL,
    ErrorCode.TARGET_DETACHED: ErrorCategory.TRANSIENT_TECHNICAL,
    ErrorCode.ACTION_TIMEOUT: ErrorCategory.TRANSIENT_TECHNICAL,
    ErrorCode.NAVIGATION_FAILED: ErrorCategory.TRANSIENT_TECHNICAL,
    ErrorCode.PAGE_CLOSED: ErrorCategory.PERMANENT_TECHNICAL,
    ErrorCode.TRANSIENT_TECHNICAL_FAILURE: ErrorCategory.TRANSIENT_TECHNICAL,
    ErrorCode.UNEXPECTED_ERROR: ErrorCategory.PERMANENT_TECHNICAL,
    ErrorCode.BUSINESS_RULE_REJECTED: ErrorCategory.BUSINESS,
    ErrorCode.OUTCOME_UNKNOWN: ErrorCategory.UNKNOWN_OUTCOME,
    ErrorCode.SECURITY_POLICY_BLOCKED: ErrorCategory.SECURITY,
    ErrorCode.INVALID_CONFIGURATION: ErrorCategory.CONFIGURATION,
    ErrorCode.INVALID_ARGUMENT: ErrorCategory.CONFIGURATION,
    ErrorCode.SECRET_UNAVAILABLE: ErrorCategory.CONFIGURATION,
    ErrorCode.CHECKPOINT_CORRUPTED: ErrorCategory.CONFIGURATION,
    ErrorCode.CHECKPOINT_WRITE_FAILED: ErrorCategory.PERMANENT_TECHNICAL,
    ErrorCode.INPUT_PROVIDER_FAILED: ErrorCategory.PERMANENT_TECHNICAL,
    ErrorCode.TRANSACTION_DEADLINE_EXCEEDED: ErrorCategory.PERMANENT_TECHNICAL,
    ErrorCode.CANCELLED: ErrorCategory.CANCELLED,
}


class OutcomeUnknownReason(StrEnum):
    """Por que o desfecho é desconhecido (detalhe seguro, enumerado)."""

    ACTION_INTERRUPTED = "ACTION_INTERRUPTED"
    """A ação foi despachada (ou pode ter sido) e terminou com erro: o efeito pode ter acontecido."""
    POSTCONDITION_NOT_MET = "POSTCONDITION_NOT_MET"
    """A ação retornou, mas a pós-condição objetiva não se confirmou no prazo."""
    SINK_UNCERTAIN = "SINK_UNCERTAIN"
    """O destino do resultado falhou depois de receber a entrega."""
    INTERRUPTED_RUN = "INTERRUPTED_RUN"
    """A execução anterior parou com a transação em andamento e a reconciliação não comprovou o estado."""
    DECLARED_BY_PROCESS = "DECLARED_BY_PROCESS"
    """O próprio processo declarou o desfecho como desconhecido."""
