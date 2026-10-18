# NEKKORA-RPA-FRAMEWORK-001 — Relatório final

Data: 2026-10-18. Executor: Claude (Claude Code), operando como TEST_AGENT. Repositório
`Nekkora-Operation/Nekkora-RPA-Framework` (público, todos os direitos reservados), branch `feat/rpa-framework-001`,
PR aberto **sem merge**.

## 1. Respostas diretas

**O que exatamente funciona?** O pacote `nekkora_rpa` 0.1.0, instalável por wheel/sdist, com:
- registro de alvos por chave (`nekkora-rpa/selectors` 1.0.0) com leitura estrita e identidade obrigatória;
- ações `click`, `double_click`, `fill`, `wait_visible`, `wait_hidden`, `exists`, `is_visible`, `read_text`,
  `navigate`, `expect_new_page`/`use_page`, com prazo total, conferência de origem, resolução fail-closed presa ao
  nó verificado, classificação despachado × não despachado e retentativa governada;
- engine `INIT → TRANSFER_DATA_IN → PROCESS → TRANSFER_DATA_OUT → END` com estados terminais e monotônicos, lote,
  nova tentativa da transação só sem efeito colateral, reconciliação controlada, parada por categorias, END sempre;
- checkpoint atômico com integridade e ids pseudônimos; retomada que não repete o confirmado nem reprocessa o incerto;
- eventos JSONL fechados (`nekkora-rpa/events` 1.0.0) e projeção legível; zero valores sensíveis provado com sentinelas;
- guardas de rede: nada sai do laboratório (nem por redirecionamento) e gravações não são reenviadas pelo navegador;
- dois processos independentes (consulta somente leitura; cadastro com efeito colateral, duplo clique e reconciliação)
  consumindo o MESMO pacote instalado, mais `LoginModule`/`FormModule`, `BasePage`, provider/sink de arquivo e CLI.

**Quais condições reais foram verificadas?** Playwright 1.63.0 com: Google Chrome 155.0.8059.80 real com janela
visível (Windows 11), Chromium 1243 headless (Windows 11) e Chromium headless em Linux (contêiner oficial). Em cada
um, a suíte completa de 196 testes, incluindo a homologação ponta a ponta com o wheel instalado numa venv limpa fora do
repositório, falhas injetadas no servidor, morte real do processo no meio de uma gravação e retomada — com o resultado
de negócio conferido pelo oráculo do laboratório.

**O que está fora do escopo?** Sistemas e dados reais; ambientes além de LAB; iframe/shadow DOM; Windows/UIA, SAP, API,
Excel; geração de código (STUDIO-011); SDD; orquestração/Platform/Agent; exactly-once. Lista completa em
[known-limitations.md](../docs/known-limitations.md).

## 2. Gates

| Gate | Situação | Evidência |
|---|---|---|
| F0 Auditoria e contrato | concluído | [f0-auditoria.md](../docs/f0-auditoria.md) — 9 achados no caso Python da STUDIO-009; achado F0-A10 (roteamento não vê redirecionamento) |
| F1 Empacotamento e qualidade | concluído | `pyproject.toml` (src/), wheel + sdist, venv limpa, ruff + formatação + mypy `--strict` sem achados, `constraints/` |
| F2 Registry/Resolver | concluído | 22 testes de integração + 24 unitários de schema; "nunca o botão errado" (sósias, mesmo id trocado, candidatos que discordam) |
| F3 Libs e adapter | concluído | 44 testes de integração (ações, origem, transporte); achado F3-A1 |
| F4 Erros e retry | concluído | 26 testes unitários (contagem de tentativas, prazo total, backoff, cancelamento, bloqueios, traceback) |
| F5 Engine | concluído | testes unitários de lote misto, recuperação transitória, parada global, INIT/END, sink |
| F6 Pages e Modules | concluído | 5 Pages em 2 projetos; `LoginModule` reutilizado com chaves diferentes; `FormModule`; `BasePage` |
| F7 Logs e privacidade | concluído | `test_privacidade.py` (navegador real) + e2e varrendo todos os artefatos; eventos fechados por construção |
| F8 Checkpoint e retomada | concluído | unitários (interrupção, corrompido, ilegível, outro processo, disco cheio) + e2e com kill real |
| F9 Homologação real | concluído | [homologation.md](../docs/homologation.md); achados F9-A1 e F9-A2 |
| F10 Documentação e PR | concluído | README, docs/, este relatório; PR sem merge |

## 3. Resultados

| Execução | Resultado |
|---|---|
| Windows 11 · Chromium 1243 headless | **196/196** ([evidência](evidence/windows-chromium.txt)) |
| Windows 11 · Google Chrome 155 real, janela visível | **196/196** ([evidência](evidence/windows-chrome.txt), artefatos e2e sanitizados em [evidence/e2e-chrome](evidence/e2e-chrome)) |
| Linux · contêiner Playwright 1.63.0 · Chromium headless | **196/196** ([evidência](evidence/linux-pytest.txt)) |
| Qualidade estática | ruff, formatação e mypy `--strict` limpos ([evidência](evidence/qualidade.txt)) |
| Controle negativo (13 defeitos injetados) | **13/13 detectados**, código restaurado ([evidência](evidence/controle-negativo.md)) |
| Distribuição | wheel (46 arquivos, contratos + `py.typed`, sem lab/tests/exemplos) e sdist instalados em venvs limpas |

Composição: 112 unitários, 7 de contrato, 67 de integração (navegador), 10 ponta a ponta. Código do pacote: 36
módulos, ~3 700 linhas; código específico dos dois exemplos somado: ~290 linhas.

## 4. Achados (problema → causa → correção → prova)

| # | Problema | Causa | Correção | Prova |
|---|---|---|---|---|
| F0-A10 | redirecionamento 302 para outra origem chegava ao destino | `route` do Playwright só vê o 1º URL | camada de rede com proxy sumidouro (D-F001-18) | 0 acessos externos; teste de causa raiz |
| F3-A1 | clique "concluído" com a aba fechada no meio | o Playwright não lança erro nesse caso | aba fechada após o despacho → `OUTCOME_UNKNOWN` (D-F001-20) | controle negativo M07 |
| F9-A1 | `INIT_FAILED` na venv limpa | pip instalou Playwright 1.64.0 (sem navegador) | `constraints/lab.txt`; piso `>=1.63` | e2e |
| F9-A2 | **pedido duplicado** com um único duplo clique | Chromium (Windows) reenvia POST em conexão keep-alive derrubada | transporte de tentativa única (D-F001-19) | oráculo: 1 pedido, 2 tentativas; controle negativo M04 |
| T-01..03 | testes fracos ou travando | teste usava `from None`; `window.close` em aba não-script; PIPE não lido | corrigidos | M12; Chrome real; e2e kill |

## 5. Comandos e versões

```sh
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]" -c constraints/dev.txt
.venv/Scripts/ruff check src tests lab tools examples && .venv/Scripts/ruff format --check src tests lab tools examples
.venv/Scripts/mypy
.venv/Scripts/python -m pytest -rA                                             # Chromium headless
NK_BROWSER_CHANNEL=chrome NK_HEADLESS=0 NK_EVIDENCE_DIR=reports/evidence/e2e-chrome .venv/Scripts/python -m pytest -rA
sh tools/linux.sh
.venv/Scripts/python tools/controle_negativo.py --saida reports/evidence/controle-negativo.md
```

Versões travadas (homologação): Python 3.12.10 (Windows) / 3.12.3 (Linux), playwright 1.63.0, greenlet 3.5.6,
pyee 13.0.1, typing_extensions 4.16.0; desenvolvimento: pytest 9.1.1, ruff 0.17.1, mypy 2.4.0, build 1.6.1,
jsonschema (ver `constraints/dev.txt`). Navegadores: Chromium 1243 (Playwright), Google Chrome 155.0.8059.80.

## 6. Matriz realizado × não realizado

| Item da missão | Situação |
|---|---|
| Pacote instalável, layout src/, wheel/sdist, venv limpa, execução fora da raiz | realizado |
| Registro por chave, estratégias css/xpath/id/name/role(+test_id), identidade, ambiguidade, variantes | realizado |
| click, double_click, fill, wait, navigate (+ exists, is_visible, read_text, nova aba) | realizado |
| Clique `dom_event`/`force`/JS/mouse do SO | não realizado por decisão (fora do MVP; recusado com `INVALID_ARGUMENT`) |
| Ciclo INIT → … → END, entrada única e em memória/arquivo, lote, estados, cleanup | realizado |
| Retry tipado, backoff limitado, jitter, prazo total, não-retry em desconhecido/ambíguo/segurança/negócio | realizado |
| Checkpoint atômico, retomada, reconciliação, checkpoint corrompido, falha de disco | realizado |
| Logs JSONL, correlação, zero vazamento com sentinelas | realizado |
| Dois processos independentes no mesmo pacote, Chrome real, oráculo independente, falhas e recuperação | realizado |
| Windows e Linux | realizado (Chrome de marca só no Windows; Linux com Chromium headless) |
| iframe/shadow DOM | não realizado (fora do contrato, recusado com código) |
| Publicação em índice de pacotes / release | não realizado (fora da missão) |

## 7. Decisões que dependem da usuária

1. Revisar e fazer o merge do PR (nenhum merge foi feito).
2. Licenciamento do repositório público.
3. Política de publicação/versão do pacote.
