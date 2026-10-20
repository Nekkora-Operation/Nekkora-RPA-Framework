"""Prova a instalação a partir do ÍNDICE (depois de uma publicação aprovada): venv limpa fora do checkout, sem token.

- dependências: ``constraints/lab.lock`` do PyPI OFICIAL com ``--require-hashes`` (nunca do índice de staging: evita
  confusão de dependência);
- o pacote ``nekkora-rpa==<versão>`` do índice de destino com ``--no-deps`` e ``--require-hashes`` contra os SHA-256 dos
  artefatos construídos e verificados no próprio workflow (o índice tem de servir EXATAMENTE aqueles bytes);
- ``pip check``, ``importlib.metadata``, import, esquemas e planilha sintética (a mesma sonda de verificar_distribuicao).

Uso: ``python tools/verificar_indice.py --destino testpypi|pypi --versao 0.3.0 --sha256sums <arquivo>``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verificar_distribuicao import ROOT, SYNTHETIC, clean_env, run

SIMPLE = {"testpypi": "https://test.pypi.org/simple/", "pypi": "https://pypi.org/simple/"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", choices=sorted(SIMPLE), required=True)
    ap.add_argument("--versao", required=True)
    ap.add_argument("--sha256sums", required=True)
    a = ap.parse_args()
    hashes = [line.split()[0] for line in Path(a.sha256sums).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not hashes:
        print("SHA256SUMS vazio")
        return 1
    env = clean_env()
    with tempfile.TemporaryDirectory(prefix="nk-indice-") as d:
        tmp = Path(d)
        venv = tmp / "venv índice"
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        req = tmp / "nekkora.txt"
        req.write_text(
            f"nekkora-rpa=={a.versao} " + " ".join(f"--hash=sha256:{h}" for h in hashes) + "\n", encoding="utf-8"
        )
        steps = {
            "venv": run([sys.executable, "-m", "venv", str(venv)], env=env).returncode == 0,
            "deps_pypi_por_hash": run(
                [
                    str(py),
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "--only-binary=:all:",
                    "--index-url",
                    SIMPLE["pypi"],
                    "-r",
                    str(ROOT / "constraints" / "lab.lock"),
                ],
                env=env,
            ).returncode
            == 0,
        }
        r = run(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--require-hashes",
                "--no-cache-dir",
                "--index-url",
                SIMPLE[a.destino],
                "-r",
                str(req),
            ],
            env=env,
        )
        steps["pacote_do_indice_com_hash"] = r.returncode == 0
        if r.returncode != 0:
            steps["erro"] = (r.stdout + r.stderr)[-2000:]
        steps["pip_check"] = run([str(py), "-m", "pip", "check"], env=env).returncode == 0
        work = tmp / "fora"
        work.mkdir()
        r = run([str(py), "-I", "-c", SYNTHETIC], cwd=work, env=env)
        try:
            probe = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            probe = {"erro": (r.stdout + r.stderr)[-1500:]}
        steps["sonda"] = probe
    ok = (
        all(v is True for k, v in steps.items() if k not in ("sonda", "erro"))
        and steps["sonda"].get("version") == a.versao
    )
    print(
        json.dumps(
            {"destino": a.destino, "versao": a.versao, "resultado": "OK" if ok else "FALHOU", **steps},
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
