"""Dados tabulares (FRAMEWORK-002): leitura segura de XLSX e CSV como itens de transação.

Contrato:
- ``TabularSchema`` declara as colunas esperadas (nome do cabeçalho, obrigatoriedade, tipo e conversões PERMITIDAS).
  Nada é convertido em silêncio: um número numa coluna de texto só vira texto se a coluna declarar
  ``integer_as_text=True`` (e só se for inteiro exato).
- Cabeçalho obrigatório na 1ª linha; comparação após remover espaços nas pontas (``strip``), sem mudar maiúsculas.
  Cabeçalho duplicado, coluna exigida ausente → recusa do arquivo (``TABULAR_INVALID``).
- Linhas totalmente vazias no FINAL são ignoradas; no meio, recusadas.
- XLSX (``openpyxl``, extra opcional ``excel``): só ``.xlsx``; macros (``vbaProject.bin``), vínculos externos e
  fórmulas são recusados; cotas de tamanho do arquivo, do conteúdo descompactado (zip-bomb), linhas e colunas
  verificadas ANTES de abrir; aba escolhida explicitamente quando houver mais de uma.
- CSV (biblioteca padrão): UTF-8 com ou sem BOM; delimitador informado ou detectado só se exatamente um dos
  candidatos aparece no cabeçalho; toda linha precisa ter o número de campos do cabeçalho.
- Erros carregam só códigos (``detail``) e números (linha/coluna); nunca valores de célula.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Literal

from .core.contracts import TransactionItem
from .errors.codes import ErrorCode
from .errors.exceptions import InvalidConfiguration, NekkoraRpaError
from .observability.safety import require_token

PROBLEMS_KEY = "__row_problems__"
"""Chave reservada em ``TransactionItem.data``: tupla de ``(coluna, código)`` das células recusadas na linha."""


class TabularInvalid(NekkoraRpaError):
    """Arquivo tabular recusado (estrutura, cota, segurança). ``detail`` é um código; ``row``/``column`` são números."""

    code = ErrorCode.TABULAR_INVALID

    def __init__(self, detail: str, *, row: int | None = None, column: int | None = None) -> None:
        super().__init__(detail=require_token(detail, "detail"))
        self.row = row
        self.column = column


@dataclass(frozen=True)
class Column:
    header: str
    required: bool = True
    """Célula vazia é problema da linha."""
    kind: Literal["text"] = "text"
    integer_as_text: bool = False
    """Aceita número inteiro exato e o representa como texto (ex.: telefone gravado como número)."""


@dataclass(frozen=True)
class TabularSchema:
    columns: tuple[Column, ...]
    sheet: str | None = None
    """Aba do XLSX; obrigatória se o arquivo tiver mais de uma."""
    reject_extra_columns: bool = False

    def __post_init__(self) -> None:
        names = [c.header.strip() for c in self.columns]
        if not names or len(set(names)) != len(names) or any(not n for n in names):
            raise InvalidConfiguration(detail="tabular_schema")


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 10 * 1024 * 1024
    max_uncompressed_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: int = 200
    max_rows: int = 10_000
    max_columns: int = 100
    max_cell_chars: int = 10_000


@dataclass(frozen=True)
class TabularRow:
    number: int
    """Número da linha no arquivo (cabeçalho = 1)."""
    values: Mapping[str, str | None]
    problems: tuple[tuple[str, str], ...] = ()

    def __repr__(self) -> str:
        return f"TabularRow({self.number}, problems={len(self.problems)})"


@dataclass(frozen=True)
class TabularData:
    source_sha256: str
    headers: tuple[str, ...]
    rows: tuple[TabularRow, ...] = field(repr=False)

    def __repr__(self) -> str:
        return f"TabularData({self.source_sha256[:12]}, {len(self.rows)} linhas)"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ validação comum
def _cell(value: Any, col: Column, limits: Limits) -> tuple[str | None, str | None]:
    """(valor como texto, código do problema)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, ("EMPTY_REQUIRED" if col.required else None)
    if isinstance(value, bool):
        return None, "TYPE_BOOLEAN"
    if isinstance(value, str):
        if len(value) > limits.max_cell_chars:
            return None, "CELL_TOO_LONG"
        return value, None
    if isinstance(value, int):
        return (str(value), None) if col.integer_as_text else (None, "TYPE_NUMBER")
    if isinstance(value, float):
        if col.integer_as_text and value.is_integer() and abs(value) < 2**53:
            return str(int(value)), None
        return None, "TYPE_NUMBER"
    if isinstance(value, (datetime, date, time)):
        return None, "TYPE_DATE"
    return None, "TYPE_UNSUPPORTED"


def _build(rows: Sequence[Sequence[Any]], schema: TabularSchema, limits: Limits, sha: str) -> TabularData:
    if not rows:
        raise TabularInvalid("TABULAR_EMPTY")
    raw_headers = rows[0]
    headers = tuple("" if h is None else str(h).strip() for h in raw_headers)
    while headers and headers[-1] == "":
        headers = headers[:-1]
    if not headers:
        raise TabularInvalid("TABULAR_HEADER_MISSING", row=1)
    if len(headers) > limits.max_columns:
        raise TabularInvalid("TABULAR_TOO_MANY_COLUMNS")
    seen: set[str] = set()
    for i, h in enumerate(headers, start=1):
        if h == "":
            raise TabularInvalid("TABULAR_HEADER_EMPTY", row=1, column=i)
        if h in seen:
            raise TabularInvalid("TABULAR_HEADER_DUPLICATE", row=1, column=i)
        seen.add(h)
    position = {h: i for i, h in enumerate(headers)}
    for n, col in enumerate(schema.columns, start=1):
        if col.header.strip() not in position:
            raise TabularInvalid("TABULAR_COLUMN_MISSING", column=n)
    if schema.reject_extra_columns and len(headers) != len(schema.columns):
        raise TabularInvalid("TABULAR_EXTRA_COLUMNS")
    body = list(rows[1:])
    while body and all(v is None or (isinstance(v, str) and not v.strip()) for v in body[-1]):
        body.pop()
    if len(body) > limits.max_rows:
        raise TabularInvalid("TABULAR_TOO_MANY_ROWS")
    out: list[TabularRow] = []
    for offset, raw in enumerate(body, start=2):
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in raw):
            raise TabularInvalid("TABULAR_EMPTY_ROW", row=offset)
        if len([v for v in raw[len(headers) :] if v not in (None, "")]):
            raise TabularInvalid("TABULAR_VALUE_OUTSIDE_HEADER", row=offset)
        values: dict[str, str | None] = {}
        problems: list[tuple[str, str]] = []
        for col in schema.columns:
            idx = position[col.header.strip()]
            value = raw[idx] if idx < len(raw) else None
            text, problem = _cell(value, col, limits)
            values[col.header.strip()] = text
            if problem:
                problems.append((col.header.strip(), problem))
        out.append(TabularRow(offset, values, tuple(problems)))
    return TabularData(sha, headers, tuple(out))


# ------------------------------------------------------------------------------------------------ XLSX
def read_xlsx(path: Path | str, schema: TabularSchema, limits: Limits | None = None) -> TabularData:
    limits = limits or Limits()
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise TabularInvalid("TABULAR_NOT_XLSX")
    try:
        size = path.stat().st_size
    except OSError:
        raise TabularInvalid("TABULAR_UNREADABLE") from None
    if size == 0:
        raise TabularInvalid("TABULAR_EMPTY")
    if size > limits.max_file_bytes:
        raise TabularInvalid("TABULAR_FILE_TOO_LARGE")
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = {i.filename.lower() for i in infos}
            total = sum(i.file_size for i in infos)
            if "[content_types].xml" not in names or "xl/workbook.xml" not in names:
                raise TabularInvalid("TABULAR_NOT_XLSX")
            if any(n.endswith("vbaproject.bin") for n in names):
                raise TabularInvalid("TABULAR_MACROS")
            if any(n.startswith("xl/externallinks/") for n in names):
                raise TabularInvalid("TABULAR_EXTERNAL_LINKS")
            if total > limits.max_uncompressed_bytes or total > max(size, 1) * limits.max_compression_ratio:
                raise TabularInvalid("TABULAR_ZIP_QUOTA")
            if z.testzip() is not None:
                raise TabularInvalid("TABULAR_CORRUPTED")
    except TabularInvalid:
        raise
    except (zipfile.BadZipFile, OSError, EOFError, ValueError):
        raise TabularInvalid("TABULAR_CORRUPTED") from None
    try:
        import openpyxl  # type: ignore[import-untyped]
    except ImportError:
        raise InvalidConfiguration(detail="excel_extra_not_installed") from None
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False, keep_vba=False)
    except Exception:  # noqa: BLE001 — qualquer falha do leitor externo: arquivo recusado, sem mensagem
        raise TabularInvalid("TABULAR_CORRUPTED") from None
    try:
        names_ws = wb.sheetnames
        if schema.sheet is not None:
            if schema.sheet not in names_ws:
                raise TabularInvalid("TABULAR_SHEET_MISSING")
            ws = wb[schema.sheet]
        elif len(names_ws) == 1:
            ws = wb[names_ws[0]]
        else:
            raise TabularInvalid("TABULAR_SHEET_AMBIGUOUS")
        rows: list[tuple[Any, ...]] = []
        for r_idx, row in enumerate(ws.iter_rows(), start=1):
            if r_idx > limits.max_rows + 1:
                raise TabularInvalid("TABULAR_TOO_MANY_ROWS")
            if len(row) > limits.max_columns:
                raise TabularInvalid("TABULAR_TOO_MANY_COLUMNS")
            values = []
            for c_idx, cell in enumerate(row, start=1):
                formula = getattr(cell, "data_type", None) == "f"
                if formula or (isinstance(cell.value, str) and cell.value.startswith("=")):
                    raise TabularInvalid("TABULAR_FORMULA", row=r_idx, column=c_idx)
                values.append(cell.value)
            rows.append(tuple(values))
    finally:
        wb.close()
    return _build(rows, schema, limits, sha256_file(path))


# ------------------------------------------------------------------------------------------------ CSV
_CANDIDATES = (",", ";", "\t", "|")


def read_csv(
    path: Path | str, schema: TabularSchema, limits: Limits | None = None, delimiter: str | None = None
) -> TabularData:
    limits = limits or Limits()
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise TabularInvalid("TABULAR_UNREADABLE") from None
    if not raw:
        raise TabularInvalid("TABULAR_EMPTY")
    if len(raw) > limits.max_file_bytes:
        raise TabularInvalid("TABULAR_FILE_TOO_LARGE")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TabularInvalid("TABULAR_ENCODING") from None
    first = text.splitlines()[0] if text.splitlines() else ""
    if delimiter is None:
        present = [d for d in _CANDIDATES if d in first]
        if len(present) != 1:
            raise TabularInvalid("TABULAR_DELIMITER_AMBIGUOUS")
        delimiter = present[0]
    elif delimiter not in _CANDIDATES:
        raise InvalidConfiguration(detail="tabular_delimiter")
    rows: list[list[str]] = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        for n, row in enumerate(reader, start=1):
            if n > limits.max_rows + 1:
                raise TabularInvalid("TABULAR_TOO_MANY_ROWS")
            rows.append(row)
    except csv.Error:
        raise TabularInvalid("TABULAR_CSV_MALFORMED") from None
    if rows:
        width = len(rows[0])
        for n, row in enumerate(rows[1:], start=2):
            if row and len(row) != width:
                raise TabularInvalid("TABULAR_CSV_FIELD_COUNT", row=n)
    cells: list[tuple[Any, ...]] = [tuple(v if v != "" else None for v in row) for row in rows if row != []]
    return _build(cells, schema, limits, hashlib.sha256(raw).hexdigest())


def read_tabular(path: Path | str, schema: TabularSchema, limits: Limits | None = None) -> TabularData:
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        return read_xlsx(path, schema, limits)
    if suffix == ".csv":
        return read_csv(path, schema, limits)
    raise TabularInvalid("TABULAR_UNSUPPORTED_FORMAT")


# ------------------------------------------------------------------------------------------------ provider
class TabularInputProvider:
    """Uma linha = um item. Referência estável para retomada: ``<sha256 do arquivo>:<número da linha>`` (o framework
    só registra o ``transaction_id`` pseudônimo derivado dela). Problemas de célula vão em ``data[PROBLEMS_KEY]``: o
    processo decide (tipicamente ``BusinessRuleRejected``)."""

    def __init__(self, data: TabularData) -> None:
        self.data = data
        self._it: Iterator[TabularRow] = iter(data.rows)

    @classmethod
    def from_file(cls, path: Path | str, schema: TabularSchema, limits: Limits | None = None) -> TabularInputProvider:
        return cls(read_tabular(path, schema, limits))

    def next_item(self) -> TransactionItem | None:
        row = next(self._it, None)
        if row is None:
            return None
        payload: dict[str, object] = dict(row.values)
        payload[PROBLEMS_KEY] = row.problems
        return TransactionItem(f"{self.data.source_sha256}:{row.number}", payload)


class DeferredTabularInputProvider:
    """Lê o arquivo só no primeiro ``next_item`` (ex.: planilha baixada pelo próprio processo no INIT). ``source`` é
    chamado nesse momento e devolve o caminho; até lá, nada é lido."""

    def __init__(
        self, source: Callable[[], Path | str | None], schema: TabularSchema, limits: Limits | None = None
    ) -> None:
        self._source = source
        self._schema = schema
        self._limits = limits
        self._inner: TabularInputProvider | None = None

    @property
    def data(self) -> TabularData | None:
        return self._inner.data if self._inner is not None else None

    def next_item(self) -> TransactionItem | None:
        if self._inner is None:
            path = self._source()
            if path is None:
                raise TabularInvalid("TABULAR_SOURCE_MISSING")
            self._inner = TabularInputProvider.from_file(path, self._schema, self._limits)
        return self._inner.next_item()


__all__ = [
    "PROBLEMS_KEY",
    "Column",
    "DeferredTabularInputProvider",
    "Limits",
    "TabularData",
    "TabularInputProvider",
    "TabularInvalid",
    "TabularRow",
    "TabularSchema",
    "read_csv",
    "read_tabular",
    "read_xlsx",
    "sha256_file",
]
