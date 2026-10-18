# Plano de testes

## Camadas

| Camada | Pasta | Navegador | O que prova |
|---|---|---|---|
| Unitários | `tests/unit` (112) | não | erros/categorias, retentativa (contagem, backoff, prazo total, cancelamento, bloqueios), configuração estrita, origens, segredos, eventos fechados, registro estrito, engine (lote, estados, cleanup, sink, checkpoint, retomada, reconciliação) com processo falso |
| Contrato | `tests/contract` (7) | não | esquemas versionados = gerador; registros dos exemplos válidos; artefatos reais válidos |
| Integração | `tests/integration` (67) | sim (laboratório) | resolver (identidade, ambiguidade, sósias, estratégias, DOM mutável), ações (click/duplo/fill/wait/navigate/read_text/nova aba/rota), origem e redirecionamento, transporte de POST, privacidade com sentinelas, causas-raiz |
| Ponta a ponta | `tests/e2e` (10) | sim | wheel em venv limpa fora do repositório; dois exemplos como processos separados; oráculo do servidor; falhas injetadas; kill real + retomada; varredura de privacidade e de contratos em todos os artefatos |

Total: 196 testes. Marcadores: `browser`, `e2e` (`-m "not browser and not e2e"` roda só o que não precisa de navegador).

## Comandos exatos

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]" -c constraints/dev.txt     # Linux: .venv/bin/python
.venv/Scripts/python -m playwright install chromium                        # se o Chromium 1243 ainda não existir
.venv/Scripts/ruff check src tests lab tools examples
.venv/Scripts/ruff format --check src tests lab tools examples
.venv/Scripts/mypy                                                         # --strict, só src/
.venv/Scripts/python -m pytest -q                                          # Chromium do Playwright, headless
NK_BROWSER_CHANNEL=chrome NK_HEADLESS=0 .venv/Scripts/python -m pytest -q  # Google Chrome instalado, janela visível
sh tools/linux.sh                                                          # Linux em contêiner (Docker)
.venv/Scripts/python tools/controle_negativo.py --saida reports/evidence/controle-negativo.md
.venv/Scripts/python tools/gerar_contratos.py                              # depois de mudar enums públicos
```

## Matriz mínima da missão (§5) → testes

| Eixo | Cenário | Teste(s) |
|---|---|---|
| Resolver | CSS, XPath, id, name, role, test_id | `test_estrategias_resolvem_o_mesmo_alvo_e_clicam[*]`, `test_name_strategy_preenche_o_campo` |
| | 0 / 1 / 2+ | `test_ausente_espera_ate_o_prazo…`, `test_dois_elementos_sao_ambiguos_nunca_o_primeiro`, `test_exists_e_seguro` |
| | DOM muda | `test_dom_muda_entre_consultas…`, `test_no_desconectado_entre_verificacao_e_acao…` |
| | botão errado / sósias | `test_troca_do_alvo_por_outro_elemento_com_mesmo_id…`, `test_sosias_por_papel_e_nome…`, `test_alternativo_que_casa_sosia…`, `test_candidatos_que_discordam…`, `test_nome_divergente…`, `test_tag_divergente…` |
| Click | simples, duplo | `test_clique_simples…`, `test_duplo_clique_e_um_dblclick_efetivo[*]` |
| | timeout, disabled, covered | `test_desabilitado_ate_o_fim…`, `test_desabilitado_que_habilita…`, `test_coberto_ate_o_fim…`, `test_coberto_por_instantes…` |
| | detached, nova aba, rota alterada | `test_no_desconectado…`, `test_nova_aba`, `test_rota_alterada_pelo_clique` |
| | parâmetros inválidos, página fechada | `test_parametros_invalidos_nao_fazem_nada[*]` (10), `test_pagina_fechada` |
| Fill | variável/segredo, espera, readonly, campo incorreto | `test_fill_e_conferencia_do_valor`, `test_fill_com_segredo`, `test_fill_somente_leitura`, `test_fill_desabilitado`, `test_tipo_divergente_bloqueia_preenchimento`, `test_fill_valor_nao_aplicado…` |
| Retry | transitória antes da ação | `test_transitoria_repete…`, e2e `test_consulta_lote_misto_com_falha_transitoria_recuperada` |
| | ação pode ter concluído / duplicidade | `test_falha_depois_do_despacho…`, `test_poscondicao_nao_confirmada…`, `test_resultado_desconhecido_nunca_e_repetido`, e2e `test_pedido_criado_e_conexao_perdida…` |
| | backoff, deadline | `test_backoff_com_jitter_limitado`, `test_prazo_total_nao_reinicia_por_tentativa`, `test_prazo_da_transacao_limita_a_acao` |
| Processo | INIT falha; PROCESS falha; TRANSFER OUT incerto; END falha; cancelamento; lote parcial | `test_init_falha_end_roda…`, `test_lote_com_invalido_entre_validos…`, `test_destino_incerto_*`, `test_cancelamento`, `test_falhas_tecnicas_seguidas…`, `test_seguranca_para_o_lote…` |
| Retomada | interrupção entre itens e durante o sink; checkpoint íntegro/corrompido | `test_retomada_nao_repete_confirmadas…`, `test_reconciliacao_decide_a_retomada[*]`, `test_checkpoint_corrompido…`, `test_checkpoint_ilegivel`, `test_falha_de_disco_no_checkpoint…`, e2e `test_interrupcao_real_no_meio_do_lote…` |
| Origem | local permitido, URL não permitida, redirecionamento externo | `test_navegar_para_origem_nao_permitida…`, `test_redirecionamento_*`, `test_clique_que_leva_a_outra_origem…`, `test_link_com_redirecionamento_externo`, `test_nova_aba_para_origem_externa…`, `test_origens`, e2e `test_configuracao_fora_do_laboratorio…` |
| Logs | sentinelas em variáveis, exceções Playwright, HTML/URL, config | `test_privacidade.py`, `test_evento_fechado_recusa_texto_livre[*]`, `test_excecao_externa…`, e2e `test_zz_nenhum_valor_sensivel…` |
| Reutilização | dois projetos usam o mesmo pacote | e2e `test_pacote_instalado_e_o_usado_e_exemplos_nao_copiam_o_nucleo` + todos os cenários e2e |
| Distribuição | wheel em venv limpa, execução fora da raiz | fixture `venv` do e2e (wheel + `constraints/lab.txt`), sdist (ver homologation.md) |

## Controle negativo

`tools/controle_negativo.py` injeta 13 defeitos plausíveis (um por vez) nas proteções e exige que a suíte falhe. Resultado
em [`reports/evidence/controle-negativo.md`](../reports/evidence/controle-negativo.md): 13/13 detectados.

Regra seguida: falha de teste obrigatório = investigar a causa e corrigir; nenhuma retentativa no próprio teste para
"passar" (os testes não usam `rerun`/`flaky`).
