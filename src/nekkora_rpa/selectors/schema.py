"""Modelo tipado do registro de alvos ``nekkora-rpa/selectors`` 1.0.0 e leitura estrita.

Leitura estrita = campo desconhecido, chave JSON duplicada, versão diferente, estratégia fora da lista, tipo errado ou
identidade insuficiente → ``InvalidConfiguration`` com um detalhe enumerado (o conteúdo do arquivo nunca entra no erro).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..errors.exceptions import InvalidConfiguration
from ..observability.safety import KEY, TOKEN

SCHEMA = "nekkora-rpa/selectors"
VERSION = "1.0.0"
MAX_EXPRESSION = 1000


class Strategy(StrEnum):
    CSS = "css"
    XPATH = "xpath"
    ID = "id"
    NAME = "name"
    TEST_ID = "test_id"
    ROLE = "role"


@dataclass(frozen=True)
class Locator:
    """Referência técnica. ``expression`` (css/xpath), ``value`` (id/name/test_id) ou ``role`` + ``name`` (role).
    Nunca vai para log: pode conter informação de negócio."""

    strategy: Strategy
    expression: str | None = None
    value: str | None = None
    role: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class Expected:
    """Evidência de identidade permitida. ``tag`` é obrigatória; ``name`` (nome acessível exato) exige ``role``."""

    tag: str
    role: str | None = None
    name: str | None = None
    type: str | None = None

    @property
    def strong(self) -> bool:
        return self.name is not None


@dataclass(frozen=True)
class Target:
    key: str
    preferred: Locator
    alternatives: tuple[Locator, ...]
    expected: Expected
    page: str | None = None
    studio_step_id: str | None = None

    @property
    def candidates(self) -> tuple[Locator, ...]:
        return (self.preferred, *self.alternatives)


def _fail(detail: str) -> InvalidConfiguration:
    return InvalidConfiguration(detail=detail)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise _fail("selectors_duplicate_key")
        out[k] = v
    return out


def _obj(v: Any, allowed: set[str], required: set[str], what: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise _fail(f"selectors_{what}_type")
    if not set(v) <= allowed:
        raise _fail(f"selectors_{what}_unknown_field")
    if not required <= set(v):
        raise _fail(f"selectors_{what}_missing_field")
    return v


def _str(v: Any, what: str, limit: int = 200) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > limit:
        raise _fail(f"selectors_{what}")
    return v


def _locator(raw: Any) -> Locator:
    if not isinstance(raw, dict) or "strategy" not in raw:
        raise _fail("selectors_locator")
    try:
        strategy = Strategy(raw["strategy"])
    except ValueError:
        raise _fail("selectors_strategy_unsupported") from None
    if strategy in (Strategy.CSS, Strategy.XPATH):
        d = _obj(raw, {"strategy", "expression"}, {"strategy", "expression"}, "locator")
        return Locator(strategy, expression=_str(d["expression"], "expression", MAX_EXPRESSION))
    if strategy is Strategy.ROLE:
        d = _obj(raw, {"strategy", "role", "name"}, {"strategy", "role", "name"}, "locator")
        role = _str(d["role"], "role", 40)
        if not role.isalpha():
            raise _fail("selectors_role")
        return Locator(strategy, role=role, name=_str(d["name"], "name"))
    d = _obj(raw, {"strategy", "value"}, {"strategy", "value"}, "locator")
    return Locator(strategy, value=_str(d["value"], "value"))


def _expected(raw: Any) -> Expected:
    d = _obj(raw, {"tag", "role", "name", "type"}, {"tag"}, "expected")
    tag = _str(d["tag"], "expected_tag", 40).lower()
    if not tag.replace("-", "").isalnum():
        raise _fail("selectors_expected_tag")
    role = _str(d["role"], "expected_role", 40) if "role" in d else None
    name = _str(d["name"], "expected_name") if "name" in d else None
    typ = _str(d["type"], "expected_type", 40).lower() if "type" in d else None
    if name is not None and role is None:
        raise _fail("selectors_expected_name_requires_role")
    return Expected(tag=tag, role=role, name=" ".join(name.split()) if name else None, type=typ)


def parse(text: str, *, environment: str) -> tuple[str, str, dict[str, Target]]:
    """Devolve ``(system, revision, targets)``. ``revision`` = sha-256 do conteúdo canônico."""
    try:
        raw = json.loads(text, object_pairs_hook=_no_duplicates)
    except InvalidConfiguration:
        raise
    except ValueError:
        raise _fail("selectors_json") from None
    doc = _obj(raw, {"schema", "version", "system", "targets"}, {"schema", "version", "system", "targets"}, "root")
    if doc["schema"] != SCHEMA:
        raise _fail("selectors_schema")
    if doc["version"] != VERSION:
        raise _fail("selectors_version")
    system = doc["system"]
    if not isinstance(system, str) or not TOKEN.fullmatch(system) or "." in system:
        raise _fail("selectors_system")
    if not isinstance(doc["targets"], dict) or not doc["targets"]:
        raise _fail("selectors_targets")
    targets: dict[str, Target] = {}
    for key, rawt in doc["targets"].items():
        if not KEY.fullmatch(key) or not key.startswith(system + "."):
            raise _fail("selectors_key")
        t = _obj(
            rawt,
            {"page", "preferred", "alternatives", "expected", "variants", "provenance"},
            {"preferred", "expected"},
            "target",
        )
        preferred_raw, alternatives_raw = t["preferred"], t.get("alternatives", [])
        if "variants" in t:
            variants = t["variants"]
            if not isinstance(variants, dict) or not variants:
                raise _fail("selectors_variants")
            for env, var in variants.items():
                v = _obj(var, {"preferred", "alternatives"}, {"preferred"}, "variant")
                if not isinstance(env, str) or not TOKEN.fullmatch(env):
                    raise _fail("selectors_variants")
                _locator(v["preferred"])  # valida todas as variantes, não só a usada
                for a in v.get("alternatives", []):
                    _locator(a)
                if env == environment:
                    preferred_raw, alternatives_raw = v["preferred"], v.get("alternatives", [])
        if not isinstance(alternatives_raw, list) or len(alternatives_raw) > 5:
            raise _fail("selectors_alternatives")
        expected = _expected(t["expected"])
        alternatives = tuple(_locator(a) for a in alternatives_raw)
        if alternatives and not expected.strong:
            # usar outra estratégia só é aceitável se a identidade do MESMO alvo puder ser verificada com nome
            raise _fail("selectors_alternatives_require_strong_identity")
        preferred = _locator(preferred_raw)
        if len({c for c in (preferred, *alternatives)}) != 1 + len(alternatives):
            raise _fail("selectors_duplicate_locator")
        page = t.get("page")
        if page is not None and (not isinstance(page, str) or not TOKEN.fullmatch(page)):
            raise _fail("selectors_page")
        studio_step_id = None
        if "provenance" in t:
            prov = _obj(t["provenance"], {"studioStepId"}, set(), "provenance")
            sid = prov.get("studioStepId")
            if sid is not None and (not isinstance(sid, str) or not TOKEN.fullmatch(sid)):
                raise _fail("selectors_provenance")
            studio_step_id = sid
        targets[key] = Target(key, preferred, alternatives, expected, page, studio_step_id)
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    revision = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return system, revision, targets
