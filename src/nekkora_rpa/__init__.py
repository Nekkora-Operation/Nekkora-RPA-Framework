"""Nekkora Python RPA Framework — runtime reutilizável para automações RPA com Playwright.

API pública estável desta versão: o que está em ``__all__`` (e os subpacotes ``errors``, ``modules``, ``pages``).
"""

from ._version import __version__
from .adapters.playwright.browser import BrowserSession
from .core.checkpoints import CheckpointStore
from .core.config import BatchPolicy, BrowserConfig, RuntimeConfig, Timeouts, load_config
from .core.context import ExecutionContext
from .core.contracts import (
    DeliveryStatus,
    InMemoryInputProvider,
    InMemoryResultSink,
    InputProvider,
    ProcessResult,
    Reconciliation,
    ReconciliationVerdict,
    ResultSink,
    RpaProcess,
    Runtime,
    SingleInputProvider,
    SinkRejected,
    TransactionItem,
    TransactionOutcome,
    TransactionStatus,
)
from .core.engine import Engine, RunStatus, RunSummary, TransactionReport
from .libs.actions import Actions
from .observability.events import Event, EventCode, Phase
from .observability.logger import ConsoleEventSink, EventLogger, JsonlEventSink, MemoryEventSink
from .resilience.retry import RetryPolicy
from .resilience.timing import CancelToken
from .security.origins import OriginPolicy
from .security.secrets import EnvSecretProvider, Secret, SecretProvider
from .selectors.registry import SelectorRegistry

__all__ = [
    "Actions",
    "BatchPolicy",
    "BrowserConfig",
    "BrowserSession",
    "CancelToken",
    "CheckpointStore",
    "ConsoleEventSink",
    "DeliveryStatus",
    "Engine",
    "EnvSecretProvider",
    "Event",
    "EventCode",
    "EventLogger",
    "ExecutionContext",
    "InMemoryInputProvider",
    "InMemoryResultSink",
    "InputProvider",
    "JsonlEventSink",
    "MemoryEventSink",
    "OriginPolicy",
    "Phase",
    "ProcessResult",
    "Reconciliation",
    "ReconciliationVerdict",
    "ResultSink",
    "RetryPolicy",
    "RpaProcess",
    "RunStatus",
    "RunSummary",
    "Runtime",
    "RuntimeConfig",
    "Secret",
    "SecretProvider",
    "SelectorRegistry",
    "SingleInputProvider",
    "SinkRejected",
    "Timeouts",
    "TransactionItem",
    "TransactionOutcome",
    "TransactionReport",
    "TransactionStatus",
    "__version__",
    "load_config",
]
