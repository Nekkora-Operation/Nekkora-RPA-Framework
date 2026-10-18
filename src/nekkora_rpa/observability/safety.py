"""Validação de identificadores que podem aparecer em eventos, checkpoints e erros.

Tudo o que é texto e vai para um artefato persistido passa por aqui: chave de alvo, step_id, nome de processo, motivo
de negócio. São identificadores escolhidos pelo desenvolvedor, nunca dados do item. O padrão é estreito de propósito
(sem espaços, sem ``/``, ``?``, ``=``, ``@``) para que uma URL, um seletor CSS, um e-mail ou uma frase não passem.
"""

from __future__ import annotations

import re

from ..errors.codes import ErrorCode

TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


def is_token(value: object) -> bool:
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def require_token(value: str, what: str) -> str:
    """Devolve ``value`` se for um identificador seguro; senão recusa (o valor recusado não entra na mensagem)."""
    if not is_token(value):
        from ..errors.exceptions import InvalidArgument

        raise InvalidArgument(ErrorCode.INVALID_ARGUMENT, detail=_detail(what))
    return value


def require_key(value: str) -> str:
    if not isinstance(value, str) or KEY.fullmatch(value) is None or len(value) > 120:
        from ..errors.exceptions import InvalidArgument

        raise InvalidArgument(ErrorCode.INVALID_ARGUMENT, detail="key")
    return value


def _detail(what: str) -> str:
    return what if TOKEN.fullmatch(what) else "value"
