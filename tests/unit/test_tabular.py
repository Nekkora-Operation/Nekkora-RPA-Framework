"""FRAMEWORK-002 — leitura tabular segura (XLSX/CSV): esquema, cotas, fórmulas, macros, zip-bomb, CSV quebrado."""

from __future__ import annotations

import zipfile
from pathlib import Path

import openpyxl
import pytest

from nekkora_rpa.errors import ErrorCategory
from nekkora_rpa.tabular import (
    PROBLEMS_KEY,
    Column,
    Limits,
    TabularInputProvider,
    TabularInvalid,
    TabularSchema,
    read_csv,
    read_tabular,
    read_xlsx,
)

SENT = "SENTINELA-CELULA-123.456.789-09"
SCHEMA = TabularSchema((Column("Nome"), Column("Email"), Column("Telefone", integer_as_text=True)))


def xlsx(path: Path, rows: list[list[object]], sheets: int = 1) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    for i in range(1, sheets):
        wb.create_sheet(f"Extra{i}")
    wb.save(path)
    return path


def detail(fn) -> str:  # type: ignore[no-untyped-def]
    with pytest.raises(TabularInvalid) as e:
        fn()
    assert SENT not in str(e.value) + repr(e.value)
    return str(e.value.detail)


def test_xlsx_valido_com_cabecalho_com_espacos_e_telefone_numerico(tmp_path: Path):
    p = xlsx(
        tmp_path / "a.xlsx",
        [
            ["Nome ", "Email", "Telefone"],
            ["Ana", "a@x.test", 11987654321],
            ["Bia", "b@x.test", "011987"],
            [None, None, None],
        ],
    )
    data = read_xlsx(p, SCHEMA)
    assert data.headers == ("Nome", "Email", "Telefone")
    assert [r.values for r in data.rows] == [
        {"Nome": "Ana", "Email": "a@x.test", "Telefone": "11987654321"},
        {"Nome": "Bia", "Email": "b@x.test", "Telefone": "011987"},  # texto preserva o zero à esquerda
    ]
    assert len(data.source_sha256) == 64 and "linhas" in repr(data) and "Ana" not in repr(data)


def test_numero_em_coluna_texto_sem_permissao_e_problema_da_linha(tmp_path: Path):
    p = xlsx(tmp_path / "a.xlsx", [["Nome", "Email", "Telefone"], [123, "a@x.test", 1.5], ["Ana", None, "1"]])
    rows = read_xlsx(p, SCHEMA).rows
    assert rows[0].problems == (("Nome", "TYPE_NUMBER"), ("Telefone", "TYPE_NUMBER"))
    assert rows[1].problems == (("Email", "EMPTY_REQUIRED"),)


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([["Nome", "Email"], ["a", "b"]], "TABULAR_COLUMN_MISSING"),
        ([["Nome", "Email", "Telefone", "Nome"], ["a", "b", "c", "d"]], "TABULAR_HEADER_DUPLICATE"),
        ([["Nome", None, "Email", "Telefone"]], "TABULAR_HEADER_EMPTY"),
        ([["Nome", "Email", "Telefone"], ["a", "b", "c"], [None, None, None], ["d", "e", "f"]], "TABULAR_EMPTY_ROW"),
        ([["Nome", "Email", "Telefone"], ["a", "b", "c", SENT]], "TABULAR_VALUE_OUTSIDE_HEADER"),
    ],
)
def test_estrutura_recusada(tmp_path: Path, rows, code):  # type: ignore[no-untyped-def]
    p = xlsx(tmp_path / "a.xlsx", rows)
    assert detail(lambda: read_xlsx(p, SCHEMA)) == code


def test_formula_recusada(tmp_path: Path):
    p = xlsx(tmp_path / "a.xlsx", [["Nome", "Email", "Telefone"], ["a", '=HYPERLINK("http://x")', "1"]])
    with pytest.raises(TabularInvalid) as e:
        read_xlsx(p, SCHEMA)
    assert e.value.detail == "TABULAR_FORMULA" and (e.value.row, e.value.column) == (2, 2)
    assert e.value.category is ErrorCategory.CONFIGURATION


def test_aba_ambigua_e_aba_escolhida(tmp_path: Path):
    p = xlsx(tmp_path / "a.xlsx", [["Nome", "Email", "Telefone"], ["a", "b", "c"]], sheets=2)
    assert detail(lambda: read_xlsx(p, SCHEMA)) == "TABULAR_SHEET_AMBIGUOUS"
    ok = TabularSchema(SCHEMA.columns, sheet="Sheet")
    assert len(read_xlsx(p, ok).rows) == 1
    assert detail(lambda: read_xlsx(p, TabularSchema(SCHEMA.columns, sheet="Nao"))) == "TABULAR_SHEET_MISSING"


def test_arquivos_invalidos(tmp_path: Path):
    (tmp_path / "vazio.xlsx").write_bytes(b"")
    assert detail(lambda: read_xlsx(tmp_path / "vazio.xlsx", SCHEMA)) == "TABULAR_EMPTY"
    (tmp_path / "texto.xlsx").write_bytes(b"isto nao e zip " + SENT.encode())
    assert detail(lambda: read_xlsx(tmp_path / "texto.xlsx", SCHEMA)) == "TABULAR_CORRUPTED"
    good = xlsx(tmp_path / "bom.xlsx", [["Nome", "Email", "Telefone"]])
    (tmp_path / "truncado.xlsx").write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    assert detail(lambda: read_xlsx(tmp_path / "truncado.xlsx", SCHEMA)) == "TABULAR_CORRUPTED"
    (tmp_path / "planilha.xlsm").write_bytes(good.read_bytes())
    assert detail(lambda: read_xlsx(tmp_path / "planilha.xlsm", SCHEMA)) == "TABULAR_NOT_XLSX"
    assert detail(lambda: read_tabular(tmp_path / "planilha.xlsm", SCHEMA)) == "TABULAR_UNSUPPORTED_FORMAT"
    big = tmp_path / "grande.xlsx"
    big.write_bytes(good.read_bytes())
    assert detail(lambda: read_xlsx(big, SCHEMA, Limits(max_file_bytes=100))) == "TABULAR_FILE_TOO_LARGE"


def _repack(src: Path, dst: Path, extra: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        for name, data in extra.items():
            zout.writestr(name, data)
    return dst


def test_macros_vinculos_externos_e_zip_bomb(tmp_path: Path):
    good = xlsx(tmp_path / "bom.xlsx", [["Nome", "Email", "Telefone"], ["a", "b", "c"]])
    assert (
        detail(lambda: read_xlsx(_repack(good, tmp_path / "m.xlsx", {"xl/vbaProject.bin": b"x"}), SCHEMA))
        == "TABULAR_MACROS"
    )
    assert (
        detail(
            lambda: read_xlsx(
                _repack(good, tmp_path / "l.xlsx", {"xl/externalLinks/externalLink1.xml": b"<x/>"}), SCHEMA
            )
        )
        == "TABULAR_EXTERNAL_LINKS"
    )
    bomb = _repack(good, tmp_path / "b.xlsx", {"xl/media/zeros.bin": b"\0" * 30_000_000})
    assert bomb.stat().st_size < 1_000_000
    assert detail(lambda: read_xlsx(bomb, SCHEMA)) == "TABULAR_ZIP_QUOTA"


def test_cota_de_linhas_e_colunas(tmp_path: Path):
    p = xlsx(tmp_path / "a.xlsx", [["Nome", "Email", "Telefone"]] + [["a", "b", "c"]] * 20)
    assert detail(lambda: read_xlsx(p, SCHEMA, Limits(max_rows=5))) == "TABULAR_TOO_MANY_ROWS"
    assert detail(lambda: read_xlsx(p, SCHEMA, Limits(max_columns=2))) == "TABULAR_TOO_MANY_COLUMNS"


# ------------------------------------------------------------------------------------------------ CSV
def test_csv_utf8_bom_e_delimitador_detectado(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_bytes("﻿Nome;Email;Telefone\r\nJoão;j@x.test;0119\r\n\r\n".encode())
    data = read_csv(p, SCHEMA)
    assert data.rows[0].values == {"Nome": "João", "Email": "j@x.test", "Telefone": "0119"}


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"Nome,Email;Telefone\n", "TABULAR_DELIMITER_AMBIGUOUS"),
        (b"NomeEmailTelefone\n", "TABULAR_DELIMITER_AMBIGUOUS"),
        (b"Nome,Email,Telefone\na,b\n", "TABULAR_CSV_FIELD_COUNT"),
        (b'Nome,Email,Telefone\n"a,b,c\n', "TABULAR_CSV_MALFORMED"),
        ("Nome,Email,Telefone\n\xe9".encode("latin-1"), "TABULAR_ENCODING"),
        (b"", "TABULAR_EMPTY"),
    ],
)
def test_csv_recusado(tmp_path: Path, content: bytes, code: str):
    p = tmp_path / "a.csv"
    p.write_bytes(content)
    assert detail(lambda: read_csv(p, SCHEMA)) == code


def test_csv_delimitador_informado(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text("Nome|Email|Telefone\na|b|c\n", encoding="utf-8")
    assert read_csv(p, SCHEMA, delimiter="|").rows[0].values["Email"] == "b"


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize(
    ("body", "row"),
    [
        (["a,b,c", "", "d,e,f"], 3),
        (["a,b,c", "d,e,f", "", "g,h,i"], 4),
        (["a,b,c", "", "", "d,e,f"], 3),
        (["a,b,c", ",,", "d,e,f"], 3),
        (['"linha 1{eol}linha 2",b,c', "", "d,e,f"], 3),  # o registro multilinha conta como um só
    ],
)
def test_csv_linha_vazia_entre_registros_recusada(tmp_path: Path, eol: str, body: list[str], row: int):
    p = tmp_path / "a.csv"
    p.write_bytes(eol.join(["Nome,Email,Telefone", *(b.format(eol=eol) for b in body)]).encode() + eol.encode())
    with pytest.raises(TabularInvalid) as e:
        read_csv(p, SCHEMA)
    assert (e.value.detail, e.value.row) == ("TABULAR_EMPTY_ROW", row)
    assert detail(lambda: TabularInputProvider.from_file(p, SCHEMA)) == "TABULAR_EMPTY_ROW"


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("final", ["", "{eol}", "{eol}{eol}", "{eol}{eol}{eol}", "{eol},,{eol}"])
def test_csv_linhas_vazias_no_fim_aceitas_com_posicoes_preservadas(tmp_path: Path, eol: str, final: str):
    p = tmp_path / "a.csv"
    texto = eol.join(["Nome,Email,Telefone", "a,b,c", f'"x{eol}y",e,f', "g,h,i"]) + final.format(eol=eol)
    p.write_bytes(texto.encode())
    data = read_csv(p, SCHEMA)
    assert [r.number for r in data.rows] == [2, 3, 4]
    # o campo multilinha é preservado e não vira registro vazio
    assert [r.values["Nome"] for r in data.rows] == ["a", f"x{eol}y", "g"]
    prov = TabularInputProvider(data)
    refs = [item.reference.split(":")[1] for item in iter(prov.next_item, None)]
    assert refs == ["2", "3", "4"]


# ------------------------------------------------------------------------------------------------ provider
def test_provider_referencia_estavel_e_problemas(tmp_path: Path):
    p = xlsx(tmp_path / "a.xlsx", [["Nome", "Email", "Telefone"], [SENT, "b", "1"], ["c", None, "2"]])
    prov = TabularInputProvider.from_file(p, SCHEMA)
    a, b = prov.next_item(), prov.next_item()
    assert prov.next_item() is None
    assert a is not None and b is not None
    assert (
        a.reference.endswith(":2")
        and b.reference.endswith(":3")
        and a.reference.split(":")[0] == read_xlsx(p, SCHEMA).source_sha256
    )
    assert a.data[PROBLEMS_KEY] == () and b.data[PROBLEMS_KEY] == (("Email", "EMPTY_REQUIRED"),)
    assert SENT not in repr(a) + str(a)


def test_esquema_invalido():
    from nekkora_rpa.errors import InvalidConfiguration

    with pytest.raises(InvalidConfiguration):
        TabularSchema((Column("A"), Column("A ")))


def test_provider_adiado_le_so_no_primeiro_item(tmp_path: Path):
    from nekkora_rpa.tabular import DeferredTabularInputProvider

    alvo = tmp_path / "baixado.xlsx"
    caminho: list[Path] = []
    prov = DeferredTabularInputProvider(lambda: caminho[0] if caminho else None, SCHEMA)
    assert prov.data is None
    xlsx(alvo, [["Nome", "Email", "Telefone"], ["a", "b", "1"]])
    caminho.append(alvo)
    item = prov.next_item()
    assert item is not None and prov.next_item() is None and prov.data is not None
    vazio = DeferredTabularInputProvider(lambda: None, SCHEMA)
    with pytest.raises(TabularInvalid) as e:
        vazio.next_item()
    assert e.value.detail == "TABULAR_SOURCE_MISSING"
