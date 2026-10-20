| Mutação | Proteção | Testes | Detectada | Resultado da suíte com o defeito |
|---|---|---|---|---|
| M22 | célula da planilha é sempre texto (texto lido que começa com '=' não vira fórmula) | `tests/unit/test_xlsx.py` | sim | 1 failed, 28 passed in 0.45s |
| M23 | tudo ou nada: transação sem sucesso retém a planilha (nada parcial) | `tests/unit/test_xlsx.py` | sim | 1 failed, 37 passed in 0.54s |
| M24 | lote incompleto (parada/cancelamento) retém a planilha | `tests/unit/test_xlsx.py` | **NÃO** | 50 passed in 0.90s |
| M25 | chave repetida entre transações é recusada | `tests/unit/test_xlsx.py` | sim | 1 failed, 39 passed in 0.58s |
| M26 | planilha conferida REABRINDO o temporário antes da troca | `tests/unit/test_xlsx.py` | sim | 1 failed, 35 passed in 0.49s |
| M27 | data por extenso: duas datas distintas não viram uma (nunca escolhe) | `tests/unit/test_text.py` | sim | 1 failed, 16 passed in 0.07s |
| M28 | tecla só é despachada em alvo visível e habilitado | `tests/integration/test_leitura.py` | sim | 1 failed, 3 passed in 3.31s |
| M29 | lista exibida é lida como itens (não como texto colado) | `tests/integration/test_leitura.py` | sim | 1 failed in 1.21s |
| M30 | o engine consolida o destino depois do lote | `tests/unit/test_xlsx.py` | sim | 1 failed, 46 passed in 0.74s |

Código-fonte restaurado depois das mutações: sim
