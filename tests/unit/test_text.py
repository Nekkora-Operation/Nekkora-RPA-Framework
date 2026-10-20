"""0.3.0 — normalização genérica de texto lido (sem navegador)."""

from __future__ import annotations

import pytest

from nekkora_rpa.text import join_items, normalize_address, normalize_text, parse_long_date, same_address


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("21 de junho de 1839", "1839-06-21"),
        ("21 de junho de 1839 Rio de Janeiro, MN, Império do Brasil", "1839-06-21"),
        ("29 de setembro de 1908\u00a0(69\u00a0anos) Rio de Janeiro", "1908-09-29"),
        ("1º de maio de 1990", "1990-05-01"),
        ("1° de maio de 1990", "1990-05-01"),
        ("2 de Março de 2001", "2001-03-02"),
        ("2 de marco de 2001", "2001-03-02"),
        ("14 de março de 1879 Ulm", "1879-03-14"),
        ("5 de maio de 845", "0845-05-05"),
        ("nasceu em 7 de novembro de 1867 e foi 7 de novembro de 1867", "1867-11-07"),  # a MESMA data repetida
    ],
)
def test_data_por_extenso_completa(text: str, iso: str) -> None:
    assert parse_long_date(text) == iso


@pytest.mark.parametrize(
    "text",
    [
        "junho de 1839",  # sem dia: nunca completa
        "21 de junho",  # sem ano
        "1839",
        "",
        "31 de fevereiro de 1900",  # inexistente: não "corrige"
        "21 de junhoo de 1839",  # mês fora do idioma
        "1 de maio de 1990 — 2 de maio de 1990",  # duas datas distintas: ambíguo
        "121 de maio de 1990",
        "21 de junho de 18390",
        "0 de maio de 1990",
    ],
)
def test_data_incompleta_inexistente_ou_ambigua_e_none(text: str) -> None:
    assert parse_long_date(text) is None


def test_idioma_desconhecido_e_recusado() -> None:
    with pytest.raises(ValueError, match="language"):
        parse_long_date("21 de junho de 1839", language="xx")


def test_normalizacao_preserva_letras_e_colapsa_espacos() -> None:
    assert normalize_text("  Skłodowska-\u00a0Curie \n\t ") == "Skłodowska- Curie"
    assert normalize_text("Cafe\u0301") == "Café"  # NFC
    assert normalize_text("日本  😀") == "日本 😀"


def test_itens_juntados_sem_vazios() -> None:
    assert join_items(["alemão", " ", "suíço", "norte-americano"]) == "alemão; suíço; norte-americano"
    assert join_items(["a"], ", ") == "a"
    with pytest.raises(ValueError, match="separator"):
        join_items(["a"], "\n")


def test_mesmo_endereco() -> None:
    assert same_address("https://pt.wikipedia.org/wiki/S%C3%A3o_Paulo", "https://PT.wikipedia.org:443/wiki/São_Paulo#x")
    assert same_address("http://127.0.0.1:8000/a", "http://127.0.0.1:8000/a")
    assert not same_address("https://exemplo.test/a", "https://exemplo.test/b")
    assert not same_address("https://exemplo.test/a", "https://exemplo.test/a?x=1")
    assert not same_address("javascript:alert(1)", "javascript:alert(1)")
    with pytest.raises(ValueError, match="url"):
        normalize_address("file:///c:/x")
