"""Gera arquivos de requisitos TRAVADOS COM HASH a partir das versões homologadas.

Para cada `nome==versão` de um arquivo de restrições, consulta a API JSON do PyPI oficial e lista o SHA-256 de TODOS
os arquivos publicados daquela versão (wheels de todas as plataformas + sdist): o mesmo arquivo serve ao Windows e ao
Linux e o pip, com `--require-hashes`, recusa qualquer artefato diferente do registrado (troca de pacote no índice,
espelho adulterado, confusão de dependência).

Uso (rede necessária; rodar quando as versões homologadas mudarem e commitar o resultado):

    python tools/travar_hashes.py constraints/lab.txt constraints/lab.lock
    python tools/travar_hashes.py constraints/verificacao.txt constraints/verificacao.lock
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

INDEX = "https://pypi.org/pypi/{name}/{version}/json"
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+_-]+)$")


def hashes(name: str, version: str) -> list[str]:
    url = INDEX.format(name=name, version=version)  # sempre https://pypi.org (constante)
    req = urllib.request.Request(url, headers={"User-Agent": "nekkora-travar-hashes"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - URL fixa do PyPI oficial
        doc = json.load(r)
    out = sorted({u["digests"]["sha256"] for u in doc["urls"] if not u.get("yanked")})
    if not out:
        raise SystemExit(f"{name}=={version}: nenhum arquivo publicado")
    return out


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    lines = [
        f"# GERADO por tools/travar_hashes.py a partir de {src.as_posix()} — não editar à mão.",
        "# Instalar com: pip install --require-hashes --only-binary=:all: -r <este arquivo>",
    ]
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = PIN.match(line)
        if not m:
            raise SystemExit(f"linha sem versão exata: {raw!r}")
        name, version = m.groups()
        hs = hashes(name, version)
        lines.append(f"{name}=={version} \\")
        lines += [f"    --hash=sha256:{h} \\" for h in hs[:-1]] + [f"    --hash=sha256:{hs[-1]}"]
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(dst, "·", sum(1 for x in lines if "==" in x), "pacotes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
