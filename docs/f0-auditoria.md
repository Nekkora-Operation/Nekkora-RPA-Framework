# F0 — Auditoria e contrato do projeto

Data: 2026-10-17. Executor: Claude (Claude Code), conduzindo a missão NEKKORA-RPA-FRAMEWORK-001.

## 1. O que foi auditado

| Fonte | O que importa para o framework |
|---|---|
| STUDIO-009, caso Python (`Nekkora-Studio/docs/studio-009/python`) | script gerado com localizador estrito (0 → `NOT_FOUND`, 2+ → `AMBIGUOUS`), conferência mínima de identidade, `StepId` por etapa, origem permitida, entradas por variável de ambiente, parada limpa na 1ª falha |
| STUDIO-010 (limitações de captura) | a política `nekkora-visual/1` vale para o Studio/extensão; **não** se aplica automaticamente a Python. Conclusão: o framework não produz capturas de tela |
| Playwright Python 1.63.0 (o mesmo da STUDIO-009) | auto-wait/actionability de `click`/`fill`/`dblclick`; `trial=True`; motor ARIA (`get_by_role`); `route`; `APIRequestContext` |
| Laboratório existente (extensão, `LabServer` Java) | acoplado ao repositório da extensão. Decisão D-F001-03: laboratório próprio em Python (biblioteca padrão) |
| Ambiente | Windows 11, Python 3.12.10, Google Chrome 155 instalado, Chromium 1243 do Playwright, Docker 29 (para Linux) |

## 2. Achados no caso Python da STUDIO-009 (e o que o framework faz diferente)

| # | Achado | No framework |
|---|---|---|
| A1 | Localizador estrito e "nunca o primeiro" | mantido e ampliado: todos os candidatos são contados; candidatos que discordam também bloqueiam |
| A2 | Identidade por `textContent`/`labels[0]` (aproximação) | identidade pelo motor ARIA do Playwright, conferida contra o MESMO nó (`ElementHandle`) |
| A3 | Classificação por texto da mensagem (`'strict mode violation' in str(ex)`) | proibido: classificação só por estado observado (página fechada, nó conectado, visível, habilitado) |
| A4 | Capturas de tela no modo debug | nenhuma captura; eventos estruturados |
| A5 | `depuracao.jsonl` registrava o localizador (seletor cru) | eventos fechados: só chave, códigos e números |
| A6 | Erro genérico depois do clique (`PLAYWRIGHT_ERROR`) | distinção despachado × não despachado; `OUTCOME_UNKNOWN` |
| A7 | Sem transação, retentativa, checkpoint nem lote | engine transacional, retentativa governada, checkpoint, reconciliação |
| A8 | Origem conferida só no início | conferida antes de navegar, na rede (inclusive redirecionamento) e antes de cada ação |
| A9 | Conexão por CDP a um Chrome aberto pelo usuário | o framework lança e controla o próprio navegador/contexto (CDP fica fora do escopo) |

## 3. Achados na verificação do próprio Playwright (antes de codificar)

- **F0-A10 — o roteamento não vê redirecionamentos.** Com `context.route` liberando só o laboratório, `goto` em uma
  URL que responde 302 para outra origem **chegou** ao servidor externo (1 acesso contado). A documentação do Playwright
  confirma que o handler vê só o primeiro URL. Defesa adotada: camada de rede (proxy "sumidouro" com exceção apenas para
  as origens permitidas; `<-loopback>` precisa vir primeiro na lista). Comprovado: 0 acessos externos, redirecionamento
  na mesma origem preservado. Teste de causa raiz: `test_causa_raiz_roteamento_nao_ve_redirecionamento`.
- Tentar "cumprir" (fulfill) um 302 manualmente quebra a navegação legítima (`interrupted by another navigation`) —
  descartado.

## 4. Contrato do projeto (decidido no F0)

- Repositório independente **público** `Nekkora-Operation/Nekkora-RPA-Framework` (escolha da usuária; LICENSE "todos
  os direitos reservados", como Studio e extensão). Trabalho no branch `feat/rpa-framework-001`, PR sem merge.
- Pacote `nekkora-rpa` (import `nekkora_rpa`), layout `src/`, Python ≥ 3.12, dependência direta única: Playwright.
- Somente ambiente LAB = loopback; qualquer outra origem é recusada na carga da configuração.
- Interfaces públicas: ver [contracts.md](contracts.md).
- Riscos registrados: dependência de comportamento do Chromium (rede), identidade limitada ao que o ARIA expõe,
  frames/shadow fora do escopo, processo síncrono não preemptivo (prazo da transação só é observado nas ações do
  framework). Detalhes em [known-limitations.md](known-limitations.md).
