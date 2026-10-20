# Distribuição do nekkora-rpa (NEKKORA-PACKAGING-001)

## Estado

| Item | Estado |
|---|---|
| Wheel + sdist construídos e verificados (conteúdo, metadados, instalação limpa de cada um, `twine check --strict`) | **IMPLEMENTED_LOCAL** — local e no CI de cada PR (Windows + Linux); 1ª execução verde: run `39489164509` (commit `e402d50`, 4 jobs) |
| TestPyPI | **BLOQUEADO — aguardando a titular** (P1, P2, P3) |
| PyPI | **BLOQUEADO — aguardando a titular** (P1, P2, P3) |

Nada foi publicado. Nenhuma versão está em índice até haver URL do índice E prova de instalação a partir dele.

## O que roda em cada PR (`.github/workflows/ci.yml`, sem publicar)

- **qualidade** (Windows e Linux, Python 3.12): ruff, ruff format, mypy estrito, pytest (unidade, contrato, integração
  com Chromium headless e o e2e com o wheel). Testes `chrome` (Google Chrome com janela) só na homologação local.
- **distribuição** (Windows e Linux): `constraints/build.lock` → `tools/verificar_distribuicao.py --sem-isolamento`
  (constrói com `SOURCE_DATE_EPOCH` = data do commit; confere conteúdo e metadados; instala o wheel e o sdist, cada um
  numa venv nova fora do checkout, num caminho com espaço e acento, dependências de `constraints/lab.lock` com
  `--require-hashes`, `pip check`, versão, import, 12 esquemas, planilha sintética) → `twine check --strict` →
  `SHA256SUMS`. Os artefatos ficam só como artefato do CI (14 dias).

## Dependências travadas por hash

| Arquivo | Para quê | Gerado por |
|---|---|---|
| `constraints/lab.lock` | runtime + extra `excel` (playwright 1.63.0, openpyxl 3.1.5 e o fechamento) | `tools/travar_hashes.py constraints/lab.txt constraints/lab.lock` |
| `constraints/verificacao.lock` | ferramentas de verificação usadas pelo Studio (ruff 0.17.1, mypy 2.4.0 e o fechamento) | idem com `verificacao.txt` |
| `constraints/build.lock` | construção reprodutível (build 1.6.1, setuptools 84.2.1, wheel 0.48.0…) | idem com `build.txt` |

Cada linha lista o SHA-256 de TODOS os arquivos daquela versão no PyPI oficial (todas as plataformas): o mesmo arquivo
serve ao Windows e ao Linux, e o pip recusa qualquer artefato diferente.

## Reprodutibilidade

O **wheel** é idêntico byte a byte entre construções da mesma árvore de fontes (`--sem-isolamento` com `build.lock`;
conferido no Windows em três construções seguidas; o README entra no `METADATA`, então mudar o README muda o hash). O **sdist** não é: o `tar.gz` leva carimbos de tempo do sistema de
arquivos (limitação do setuptools); o conteúdo é o mesmo e é verificado instalando.

## Publicação: `.github/workflows/release.yml`

Só por **Run workflow** a partir de uma **tag `v<versão>`**, escolhendo `testpypi` ou `pypi`:

1. **guardas** (sem `id-token`): `tools/guardas_publicacao.py` exige tag = `_version.py`; classifier
   `Private :: Do Not Upload` REMOVIDO; variável `NEKKORA_LICENCA_APROVADA` = versão; versão inédita no destino; para o
   PyPI, a versão já no TestPyPI. Hoje **falha fechado** (classifier presente, licença não aprovada).
2. **construir** (sem `id-token`): mesma verificação do CI + `twine check --strict` + `SHA256SUMS`.
3. **publicar-testpypi** / **publicar-pypi**: environment `testpypi` / `pypi` (aprovação humana), `id-token: write`
   SÓ aqui, confere os SHA-256 e publica com `pypa/gh-action-pypi-publish` (Trusted Publishing; nenhum token guardado).
4. **verificar-instalacao** (Windows e Linux): `tools/verificar_indice.py` instala DO ÍNDICE numa venv limpa — pacote com
   `--no-deps --require-hashes` contra os SHA-256 verificados; dependências do PyPI OFICIAL travadas por hash (nunca do
   TestPyPI: evita confusão de dependência) — e roda a mesma sonda.

Actions fixadas por SHA de commit (a tag fica no comentário).

## Ações da titular (nada disso pode ser feito pelo agente)

1. **P1 — licença e regime de distribuição.** Decidir se o `nekkora-rpa` será publicado e com quais direitos (instalar,
   executar, uso comercial, redistribuição). O `LICENSE` atual não concede uso. Publicar não torna o código aberto, mas
   o pacote no PyPI pode ser baixado e inspecionado por qualquer pessoa. Depois da decisão: texto de licença aprovado,
   metadados (PEP 639: `license = "<expressão SPDX ou LicenseRef-…>"`, `license-files = ["LICENSE"]`) e remoção do
   classifier `Private :: Do Not Upload`, num PR próprio.
2. **P2 — nome e conta.** Hoje a API JSON e o índice `simple` respondem 404 para `nekkora-rpa` no PyPI e no TestPyPI —
   **isso não prova que o nome está livre** (projeto sem versões ou nome proibido também dão 404). Confirmar com a conta
   titular; se o nome for de terceiro, não publicar e escolher outro.
3. **Trusted Publisher** (em cada índice, conta titular): *Publishing → Add a new pending publisher* com
   PyPI project name `nekkora-rpa`, owner `Nekkora-Operation`, repository `Nekkora-RPA-Framework`,
   workflow `release.yml`, environment `testpypi` (no TestPyPI) / `pypi` (no PyPI). Um pending publisher **não reserva**
   o nome.
4. **GitHub Environments** `testpypi` e `pypi`: revisores obrigatórios (a titular), deployment só de tags `v*`;
   **ruleset** protegendo tags `v*` (criação só por quem aprova releases). Variável de repositório
   `NEKKORA_LICENCA_APROVADA` = versão aprovada.
5. **P3 — aprovação**: aprovar explicitamente o staging (TestPyPI) da versão; depois, em separado, a produção (PyPI) e a
   tag.

## Limitações

- O aviso de depreciação do setuptools sobre a tabela `license` permanece até a decisão P1 (migrar para PEP 639 muda a
  declaração de licença).
- `twine` não é travado por hash (o fechamento dele depende do sistema operacional); é só verificador — a construção e
  a publicação usam artefatos travados.
- SBOM/provenance: a action de publicação gera atestações PEP 740 por padrão quando publica com Trusted Publishing; não
  há SBOM separado nesta versão.
