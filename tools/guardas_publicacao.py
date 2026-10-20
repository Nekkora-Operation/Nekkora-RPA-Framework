"""Guardas da publicação (job "guardas" de .github/workflows/release.yml). Falham FECHADO.

Publicar exige, TODAS ao mesmo tempo:
- disparo a partir de uma TAG ``v<versão>`` igual a ``src/nekkora_rpa/_version.py``;
- classifier ``Private :: Do Not Upload`` REMOVIDO do pyproject (só depois da decisão de distribuição da titular);
- variável do repositório ``NEKKORA_LICENCA_APROVADA`` igual à versão (a titular aprovou a licença PARA esta versão);
- a versão ainda NÃO existe no índice de destino (nunca sobrescrever/republicar);
- para o PyPI de produção: a mesma versão já está no TestPyPI (staging feito antes).

Entrada pelo ambiente: DESTINO, REF_TYPE, REF_NAME, LICENCA_APROVADA. Saída: ``versao=<v>`` em $GITHUB_OUTPUT.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEXES = {"testpypi": "https://test.pypi.org", "pypi": "https://pypi.org"}
PRIVATE = "Private :: Do Not Upload"


def published(index: str, version: str) -> bool:
    """A versão existe no índice? 404 = não; qualquer outra falha de rede/servidor = erro (não presume nada)."""
    url = f"{INDEXES[index]}/pypi/nekkora-rpa/{version}/json"  # host fixo da tabela INDEXES
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nekkora-guardas"}), timeout=30):  # noqa: S310
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def avaliar(
    *,
    versao: str,
    pyproject: str,
    destino: str,
    ref_type: str,
    ref_name: str,
    licenca_aprovada: str,
    no_destino: bool,
    no_testpypi: bool,
) -> list[str]:
    erros = []
    if destino not in INDEXES:
        erros.append(f"destino desconhecido: {destino!r}")
    if ref_type != "tag" or ref_name != f"v{versao}":
        erros.append(f"o disparo precisa ser da tag v{versao} (recebido {ref_type}:{ref_name})")
    if PRIVATE in pyproject:
        erros.append(
            f"BLOQUEADO (P1): o pyproject ainda declara '{PRIVATE}' — decisão de distribuição da titular pendente"
        )
    if licenca_aprovada.strip() != versao:
        erros.append(f"BLOQUEADO (P1): licença não aprovada para {versao} (variável NEKKORA_LICENCA_APROVADA)")
    if no_destino:
        erros.append(f"{versao} já existe em {destino}: nunca republicar; outra versão exige decisão da titular")
    if destino == "pypi" and not no_testpypi:
        erros.append(f"BLOQUEADO (P3): {versao} ainda não passou pelo TestPyPI (staging antes da produção)")
    return erros


def main() -> int:
    m = re.search(
        r'__version__\s*=\s*"([^"]+)"', (ROOT / "src" / "nekkora_rpa" / "_version.py").read_text(encoding="utf-8")
    )
    if not m:
        print("versão não encontrada em _version.py")
        return 1
    versao = m.group(1)
    destino = os.environ.get("DESTINO", "")
    erros = avaliar(
        versao=versao,
        pyproject=(ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        destino=destino,
        ref_type=os.environ.get("REF_TYPE", ""),
        ref_name=os.environ.get("REF_NAME", ""),
        licenca_aprovada=os.environ.get("LICENCA_APROVADA", ""),
        no_destino=destino in INDEXES and published(destino, versao),
        no_testpypi=published("testpypi", versao),
    )
    for e in erros:
        print("GUARDA:", e)
    if erros:
        return 1
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"versao={versao}\n")
    print(f"guardas OK: {versao} → {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
