# Homologação (F9)

Data: 2026-10-17/18. Operador: Claude (Claude Code), rotulado TEST_AGENT. Dados 100% sintéticos, laboratório local.

## Ambientes efetivamente usados

| Ambiente | Navegador | Resultado | Evidência |
|---|---|---|---|
| Windows 11 Pro 10.0.26200, Python 3.12.10 | Chromium 1243 do Playwright 1.63.0, headless | **196/196** | [windows-chromium.txt](../reports/evidence/windows-chromium.txt) |
| Windows 11 Pro 10.0.26200, Python 3.12.10 | **Google Chrome 155.0.8059.80** (canal `chrome`), janela visível | **196/196** | [windows-chrome.txt](../reports/evidence/windows-chrome.txt), artefatos em [e2e-chrome/](../reports/evidence/e2e-chrome) |
| Linux (contêiner `mcr.microsoft.com/playwright/python:v1.63.0-noble`, Python 3.12.3) | Chromium headless | **196/196** | [linux-pytest.txt](../reports/evidence/linux-pytest.txt) |
| Qualidade estática | — | ruff, formatação e mypy `--strict` sem achados | [qualidade.txt](../reports/evidence/qualidade.txt) |
| Controle negativo | Chromium | **13/13** defeitos injetados detectados | [controle-negativo.md](../reports/evidence/controle-negativo.md) |

Chrome de marca no Linux não foi exercitado (o contêiner traz só o Chromium do Playwright) — limite declarado.

## Como a homologação ponta a ponta é montada (`tests/e2e`)

1. `python -m build --wheel` do repositório → wheel `nekkora_rpa-0.1.0-py3-none-any.whl`;
2. venv NOVA numa pasta temporária fora do repositório; `pip install <wheel> -c constraints/lab.txt`;
3. os dois exemplos são COPIADOS para essa pasta e executados com o Python da venv, `cwd` fora do repositório e sem
   `PYTHONPATH` (o teste confirma que `nekkora_rpa` vem do `site-packages` da venv e que os exemplos só importam
   `nekkora_rpa` e seus próprios `pages`/`processes`);
4. laboratório com credenciais SENTINELA, entregues só por `NK_SECRET_*`;
5. cada cenário compara o desfecho com o **oráculo do servidor** (consultas registradas, pedidos gravados, duplicados,
   tentativas de gravação, logins, acessos à origem externa) — nunca só com o código de saída ou os eventos.

## Cenários e verificação pelo oráculo

| Cenário | Processo | Falha injetada | Verificado pelo oráculo (servidor) | Resultado do runtime |
|---|---|---|---|---|
| e1 lote misto | consulta | 503 na 1ª consulta | consultas registradas = exatamente as válidas, sem a que falhou; nome/situação entregues = cadastro do servidor | 3 SUCCEEDED, 2 BUSINESS_REJECTED (código inválido nunca consultado); retentativa da transação registrada |
| e7 credencial recusada | consulta | senha errada | 1 login recusado, 0 consultas | `INIT_FAILED` (`login_rejected`), sem insistir |
| e6 fora do laboratório | consulta | `--base-url` externo | 0 requisições | saída 5 (`allowed_origins_not_lab`) |
| e2 lote misto | pedidos | produto inexistente (422) e quantidade 0 | pedidos gravados = só os válidos, 1 vez cada; 3 tentativas de gravação (a quantidade inválida nem chega ao servidor); protocolos entregues = protocolos do servidor | 2 SUCCEEDED, 2 BUSINESS_REJECTED |
| e3 gravou e caiu | pedidos | servidor grava e derruba a conexão | **1** pedido por referência; **2** tentativas de gravação no total (o duplo clique não foi repetido) | desfecho desconhecido → `reconcile` (lista por referência) → `DONE` → SUCCEEDED com o protocolo lido |
| e4 indisponível | pedidos | 503 sem gravar | 1 pedido; 2 tentativas | `reconcile` → `NOT_DONE` → nova tentativa segura → SUCCEEDED |
| e5 interrupção real | pedidos | servidor demora 3 s na 3ª gravação; o processo é **morto** (kill) nesse intervalo e o servidor grava mesmo assim | após a 1ª execução: R1, R2, R3 gravados; checkpoint com R3 `IN_PROGRESS`. Retomada: cada referência gravada exatamente 1 vez, 0 duplicados, 5 tentativas no total. 3ª execução: nada feito | retomada: R1/R2 `SKIPPED`, R3 reconciliado como feito, R4/R5 processados |
| privacidade | ambos | sentinelas em credenciais, observação com CPF fictício, referências | nenhum valor em stdout, stderr, eventos, checkpoint ou resumo; resultados sem credenciais | — |
| contratos | ambos | — | todos os eventos, checkpoints, resumos e resultados reais validam nos esquemas | — |

## Achado decisivo da homologação (F9-A2)

Na 1ª versão, o cenário e3 produziu **2 pedidos** para a REF-A com **um** duplo clique e a página mostrou sucesso.
Investigação: o framework despachou o duplo clique uma vez (eventos) e a transação terminou SUCCEEDED sem reconciliação
(a página recebeu 201). Sonda isolada: o Chromium reenviou o POST cuja conexão keep-alive reutilizada caiu sem resposta.
Correção (D-F001-19): transporte de tentativa única para métodos não idempotentes. Reexecução: 1 pedido, 2 tentativas
no total, reconciliação `DONE`. Testes de causa raiz mantêm o comportamento documentado: no Windows a duplicidade sem
a guarda se reproduz sempre; no Linux (contêiner) o reenvio não se reproduziu — a guarda torna as duas plataformas
iguais.

## O que NÃO foi homologado

- Sistemas reais, dados reais, ambientes diferentes de LAB (proibidos nesta missão).
- iframe e shadow DOM (fora do contrato; recusados com código).
- Chrome de marca em Linux; macOS.
- Execução concorrente de duas instâncias na mesma pasta de execução.
