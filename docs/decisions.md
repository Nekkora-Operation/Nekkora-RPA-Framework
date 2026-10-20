# Decisões arquiteturais (D-F001-xx)

| # | Decisão | Motivo | Alternativa descartada |
|---|---|---|---|
| D-F001-01 | Repositório público próprio `Nekkora-RPA-Framework`, LICENSE "todos os direitos reservados" | escolha da usuária no F0; mesmo padrão do Studio e da extensão | construir dentro do Studio (proibido pela missão) |
| D-F001-02 | Pacote `nekkora-rpa` / `nekkora_rpa`, layout `src/`, setuptools, versão em `_version.py`, dependência direta só Playwright (`>=1.63,<2`, piso = versão homologada) | instalável por qualquer projeto; piso declarado = o que foi testado | piso 1.49 (não testado) |
| D-F001-03 | Laboratório próprio em Python (biblioteca padrão), com oráculo e falhas injetáveis | independência do repositório da extensão; oráculo no mesmo processo dos testes | reaproveitar o `LabServer` Java da extensão |
| D-F001-04 | Identidade pelo motor ARIA do Playwright conferida contra o MESMO nó (`ElementHandle`), não por `textContent` | nome acessível real; evita conferir um nó e agir em outro | `locator.and_()` (re-resolve o seletor) |
| D-F001-05 | Ação age sobre o `ElementHandle` verificado | troca de DOM entre verificação e ação vira `TARGET_DETACHED`, nunca clique em outro elemento | `Locator` preguiçoso (re-resolve na hora da ação) |
| D-F001-06 | Qualquer candidato com 2+ elementos → `TARGET_AMBIGUOUS`; candidatos de um elemento que apontam para nós diferentes → `TARGET_AMBIGUOUS` | fail-closed contra sósias e alternativo que "acha outra coisa" | cair no alternativo quando o preferido é ambíguo |
| D-F001-07 | Navegação e esperas em `libs/actions.py` (uma classe) | infraestrutura comum única (prazo, origem, eventos, retry); menos abstração vazia | `navigation.py`/`waits.py` separados |
| D-F001-08 | Distinção despachado × não despachado: `click(trial=True)` antes do clique real | falha no trial prova que não clicou (pode repetir); falha depois → `OUTCOME_UNKNOWN` | tratar todo erro do Playwright como transitório |
| D-F001-09 | `fill` idempotente com conferência do valor; `click`/`double_click` não idempotentes por padrão (declaráveis); `navigate` GET idempotente por padrão | "nunca repetir automaticamente ações potencialmente não idempotentes" | padrão idempotente para clique |
| D-F001-10 | Classificação por ESTADO observado (aba fechada, nó conectado, visível, habilitado, somente leitura), nunca pelo texto da mensagem | mensagens mudam entre versões e podem conter dados | `'strict mode violation' in str(ex)` (STUDIO-009) |
| D-F001-11 | Eventos fechados (dataclass com campos fixos; todo texto validado por padrão) | vazamento impossível por construção; o teste de sentinela confirma | redaction por expressão regular sobre texto livre |
| D-F001-12 | Exceções não encadeiam a exceção externa (`__suppress_context__` + `from None`); só `cause_type` | traceback impresso pelo processo não pode levar a mensagem do Playwright | guardar a exceção externa |
| D-F001-13 | `transaction_id` = `tx-` + HMAC-SHA256(sal aleatório do checkpoint, referência)[:20] | referência do item pode ser dado de negócio (CPF, pedido); retomada precisa de id estável | id sequencial (não estável) ou a própria referência |
| D-F001-14 | `FAILED_TECHNICAL` ⇔ nenhum efeito despachado; com efeito → `OUTCOME_UNKNOWN` | o estado diz se reprocessar é seguro, sem interpretação | um único estado de falha técnica |
| D-F001-15 | Reconciliação controlada: na mesma execução (desfecho desconhecido) e na retomada (transação EM ANDAMENTO); padrão `UNKNOWN` | só o estado lido do sistema decide; sem prova, revisão humana | reprocessar na retomada |
| D-F001-16 | Destino incerto: `OUTCOME_UNKNOWN`, salvo destino idempotente/recusa explícita sem efeito → `FAILED_TECHNICAL` | missão: "sink falha depois de receber → OUTCOME_UNKNOWN" | marcar entregue |
| D-F001-17 | Parada do lote: segurança, configuração, cancelamento, checkpoint, entrada indisponível, N falhas técnicas seguidas | sem `continue_on_error` genérico | continuar sempre |
| D-F001-18 | Camada de rede com proxy "sumidouro" (porta reservada sem `listen`) + exceção só para origens permitidas (`<-loopback>` primeiro) | achado F0-A10: o roteamento não vê redirecionamentos | cumprir 302 manualmente (quebra navegação) |
| D-F001-19 | Transporte de tentativa única para métodos não idempotentes, por cliente HTTP do Playwright sem proxy, com cookies do contexto | achado F9-A2: Chromium reenviava POST em conexão derrubada (duplicidade detectada pelo oráculo) | `route.fetch` (herda o proxy sumidouro e falha) |
| D-F001-20 | Clique cuja aba fechou no meio → `OUTCOME_UNKNOWN` (ou `PAGE_CLOSED` se idempotente) | achado F3-A1: o Playwright devolve o clique como concluído | confiar no retorno sem erro |
| D-F001-21 | Login como `LoginModule` idempotente com pós-condição; credencial recusada → `INVALID_CONFIGURATION:login_rejected` (para o lote) | não insistir e bloquear conta | tentar de novo |
| D-F001-22 | Sem capturas de tela em nenhum ponto | missão: não depender de screenshots; `nekkora-visual/1` não se aplica ao Python | captura mascarada como na STUDIO-009 |
| D-F001-23 | Somente LAB = loopback, validado na carga da configuração; o CLI `--base-url` vira a única origem permitida | missão: não automatizar fora do laboratório | aceitar qualquer host com aviso |
| D-F001-24 | Versões travadas da homologação em `constraints/lab.txt` e `constraints/dev.txt`; o e2e instala o wheel com elas | a venv limpa pegou Playwright 1.64.0 (sem navegador baixado) — achado F9-A1 | sem restrições |
| D-F001-25 | `is_visible` adicionado à API | o laboratório (como sistemas reais) mantém mensagens ocultas no DOM; `exists` não basta para pós-condições | ler classes CSS no processo |

## Achados da homologação

| # | Achado | Como apareceu | Correção | Teste |
|---|---|---|---|---|
| F0-A10 | `context.route` não vê saltos de redirecionamento | sonda: 302 externo chegou ao servidor | D-F001-18 | `test_redirecionamento_para_outra_origem_e_bloqueado_na_rede`, `test_causa_raiz_roteamento_nao_ve_redirecionamento` |
| F3-A1 | `click` do Playwright retorna sem erro se a aba fechar no meio do clique | teste de "falha depois do despacho" não recebia exceção | D-F001-20 | `test_falha_depois_do_despacho_*` (controle negativo M07) |
| F9-A1 | venv limpa instalou Playwright 1.64.0 | e2e: `INIT_FAILED UNEXPECTED_ERROR` | D-F001-24 | e2e completo |
| F9-A2 | Chromium (Windows) reenviou POST de conexão keep-alive derrubada: pedido duplicado e página com 201 | oráculo do e2e: `{'REF-A': 2}` com um único duplo clique | D-F001-19 | `test_pedido_criado_e_conexao_perdida_reconcilia_sem_duplicar`, `test_post_com_conexao_derrubada_*`, causa raiz |
| S014-A1 | Glifo de fonte de ícones (área de uso privado, via `::before`) entra no nome acessível do Playwright: `" Login"` ≠ `"Login"` gravado | código gerado pelo Studio para the-internet.herokuapp.com/login parou em `TARGET_IDENTITY_MISMATCH:name` no botão Login | comparação exata do texto, tolerando só glifos U+E000–U+F8FF e espaços nas PONTAS (`accessible_name`) | `test_glifo_de_fonte_de_icone_nao_muda_o_nome`, `test_glifo_de_icone_nao_afrouxa_o_texto` (controle negativo: falha sem a correção) |
| S014-A2 | Com `include_hidden=True` o Playwright inclui descendentes `aria-hidden` no nome: `"Next →"` ≠ `"Next"` (nome do Chrome e o gravado) | código gerado para quotes.toscrape.com parou em `TARGET_IDENTITY_MISMATCH:name` no link Next | nome EXPOSTO primeiro; o modo com ocultos fica só para alvo oculto | `test_descendente_aria_hidden_fora_do_nome` (controle negativo: falha sem a correção) |
| T-01 | teste "contexto suprimido mesmo sem `from None`" usava `from None` | controle negativo M12 não detectado | teste corrigido | M12 |
| T-02 | `window.close()` só fecha janela aberta por script; `fetch keepalive` no `mousedown` não chegava no Chrome de marca | testes de despacho; Chrome real | cenário em pop-up; efeito registrado na janela de origem | `test_falha_depois_do_despacho_*` |
| T-03 | PIPE não lido travava o processo em segundo plano (kill) | e2e de interrupção sem pedidos | saída em arquivos | `test_interrupcao_real_*` |

## Para decisão da usuária

- **Licenciamento** do repositório público (hoje "todos os direitos reservados", como os demais).
- **Publicação** (PyPI interno/externo) e política de versão — fora desta missão (o classificador `Private :: Do Not
  Upload` impede envio acidental ao PyPI).
- Ver também as limitações em [known-limitations.md](known-limitations.md) que podem virar missões próprias.
