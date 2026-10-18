| Mutação | Proteção | Testes | Detectada | Resultado da suíte com o defeito |
|---|---|---|---|---|
| M01 | ambíguo nunca vira 'o primeiro' | `tests/integration/test_resolver.py` | sim | 1 failed, 7 passed in 8.70s |
| M02 | identidade verificada antes de agir | `tests/integration/test_resolver.py` | sim | 1 failed, 11 passed in 7.16s |
| M03 | camada de rede (proxy sumidouro) contra redirecionamento externo | `tests/integration/test_actions.py -k redir` | sim | 1 failed, 40 deselected in 0.96s |
| M04 | transporte de tentativa única para POST | `tests/integration/test_actions.py -k post_com_conexao` | sim | 1 failed, 43 deselected in 1.04s |
| M05 | OUTCOME_UNKNOWN nunca é repetido pela política | `tests/unit/test_retry.py` | sim | 1 failed, 5 passed in 0.10s |
| M06 | falha depois de efeito vira OUTCOME_UNKNOWN (não reprocessa) | `tests/unit/test_engine.py` | sim | 1 failed, 4 passed in 0.10s |
| M07 | clique que fecha a aba no meio vira desfecho desconhecido (F3-A1) | `tests/integration/test_actions.py -k despacho` | sim | 1 failed, 42 deselected in 1.04s |
| M08 | origem conferida antes de navegar | `tests/integration/test_actions.py -k origem or redir` | sim | 1 failed, 37 deselected in 1.55s |
| M09 | checkpoint grava EM ANDAMENTO antes de agir | `tests/unit/test_engine.py` | sim | 1 failed, 18 passed in 0.13s |
| M10 | referência do item pseudonimizada no checkpoint | `tests/unit/test_engine.py -k checkpoint or retomada` | sim | 1 failed, 3 passed, 26 deselected in 0.18s |
| M11 | Secret não se revela em repr/str | `tests/unit/test_config_security.py` | sim | 1 failed, 18 passed in 0.12s |
| M12 | exceção externa não encadeada no traceback | `tests/unit/test_retry.py -k traceback or contexto` | sim | 1 failed, 1 passed, 24 deselected in 0.07s |
| M13 | reconciliação decide desfecho desconhecido na execução | `tests/unit/test_engine.py -k reconcil` | sim | 1 failed, 2 passed, 28 deselected in 0.12s |
| M14 | planilha com fórmula é recusada (dados) | `tests/unit/test_tabular.py` | sim | 1 failed, 7 passed in 0.48s |
| M15 | download só da origem autorizada | `tests/integration/test_framework002.py -k download` | sim | 1 failed, 5 passed, 9 deselected in 7.67s |
| M16 | assinatura do arquivo baixado conferida | `tests/integration/test_framework002.py -k download` | sim | 1 failed, 2 passed, 9 deselected in 3.09s |
| M17 | benchmark só com origem https exata fora do loopback | `tests/unit/test_config_security.py -k benchmark` | sim | 1 failed, 29 deselected in 0.07s |
| M18 | rótulo irmão só identifica o ÚNICO campo do contêiner | `tests/integration/test_framework002.py -k rotulo` | sim | 1 failed, 2 passed, 13 deselected in 5.64s |
| M19 | padrão de texto do resultado precisa ser ancorado | `tests/integration/test_framework002.py -k padrao` | sim | 1 failed, 2 passed, 14 deselected in 9.71s |
| M20 | prova de avanço: nó marcado precisa sair do documento | `tests/integration/test_framework002.py` | sim | 1 failed in 2.06s |
| M21 | linha vazia entre registros do CSV é recusada (não some em silêncio) | `tests/unit/test_tabular.py` | sim | 1 failed, 20 passed in 0.75s |

Código-fonte restaurado depois das mutações: sim
