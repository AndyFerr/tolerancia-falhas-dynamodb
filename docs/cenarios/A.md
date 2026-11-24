# Cenário A — escrita parcial vs. transação

> Entregável das linhas **C1** (metodologia) e **C4** (execuções).
> Implementação: `scenarios/cenario_a.py` · Resultados: `results/cenario_a_*.json`

## Pergunta

Uma operação que precisa de duas escritas para estar correta pode terminar pela metade? E o que muda quando ela é feita dentro de uma transação?

## Amarração com o paper

A §3 afirma que o DynamoDB suporta **transações ACID entre itens**, permitindo atualizar múltiplos itens com atomicidade, consistência, isolamento e durabilidade, sem comprometer escalabilidade e performance. Este cenário testa a primeira dessas propriedades — atomicidade — de forma direta e mensurável.

A escrita condicional, também de §3, entra como o mecanismo que provoca a falha: é ela que faz a segunda operação ser rejeitada.

## O caso

Uma **transferência de estoque**: tirar 10 unidades de `prod-001` e colocar em `prod-050`. São duas escritas, e o sistema só está correto se as duas acontecerem ou nenhuma acontecer.

A falha é provocada por uma regra de negócio legítima no destino: `prod-050` tem um **limite de prateleira** de 100 unidades, e a escrita no destino carrega `ConditionExpression: quantidade <= 100`. O script prepara o destino com **105 unidades** (`EXCESSO_DESTINO = 5`), então a condição falha sempre.

O resultado é determinístico, roda em segundos e não depende de concorrência nem de temporização.

> **Nota sobre o total inicial.** Por causa dessas 5 unidades extras no destino, o estoque total de partida registrado nas métricas é **5005**, não 5000. É efeito do preparo, não resíduo de execução anterior — o script se recusa a rodar se a tabela não estiver com 50 produtos e 5000 unidades exatas antes do preparo.

## O invariante

O número total de unidades no estoque **não pode mudar** durante uma transferência. Unidades mudam de prateleira, não somem.

É essa conservação que o cenário mede, e é um critério que dispensa explicação técnica.

## Hipóteses

- **H1 — `sem_transacao`:** a primeira escrita é confirmada e a segunda falha. O total de unidades **diminui**: as unidades saíram da origem e não chegaram ao destino. `estado_parcial = true`.
- **H2 — `com_transacao`:** a mesma condição falha, mas `TransactWriteItems` aborta a operação inteira. O total permanece **exatamente igual** e `prod-001` não é tocado.
- **H3:** a diferença não está no banco. Mesma tabela, mesmos itens, mesma condição, mesmo erro — o que muda é apenas a forma de chamar.

## Procedimento

| Etapa | Ação |
|---|---|
| — | `scripts/03_reset.py`; o cenário aborta com `ESTOQUE_NAO_RESETADO` se a tabela não estiver em 50 produtos / 5000 unidades |
| `preparando_destino` | `prod-001` com 100 unidades; `prod-050` com 105 (acima do limite) |
| `modo_sem_transacao` | 5 rodadas de dois `UpdateItem` separados: debita a origem, tenta creditar o destino com a condição |
| `modo_com_transacao` | 5 rodadas das mesmas duas operações num único `TransactWriteItems` |
| — | `prod-001` e `prod-050` restaurados ao fim de cada modo |

A `ConditionalCheckFailedException` e a `TransactionCanceledException` são o **evento provocado de propósito**: são contadas, nunca tratadas como falha da AWS. O cenário também confirma o estado parcial lendo o banco, não apenas pelo retorno das chamadas.

## Resultados medidos

| Execução | Duração | `sem_transacao` — unidades perdidas | `com_transacao` — unidades perdidas |
|---|---|---|---|
| `a-2026-11-23T221646Z` | 8,7 s | **50** | **0** |

> Preencher com as execuções seguintes. O comando consolidador está no fim deste documento.

Detalhe da primeira execução:

| Métrica | `sem_transacao` | `com_transacao` |
|---|---|---|
| transferências tentadas | 5 | 5 |
| transferências concluídas | 0 | 0 |
| unidades totais antes | 5005 | 5005 |
| unidades totais depois | **4955** | **5005** |
| unidades perdidas | **50** | **0** |
| estado parcial | **sim** | não |

## Interpretação

**H1 e H2 confirmadas.**

Cinco transferências, nenhuma concluída nos dois modos — como projetado, já que a condição do destino sempre nega. A diferença está no que sobrou:

- **Sem transação**, cada rodada debitou 10 unidades da origem e falhou ao creditar o destino. Cinco rodadas, 50 unidades evaporadas. A aplicação não recebeu nenhum erro na primeira escrita; o erro veio só na segunda, quando o dinheiro já tinha saído do caixa.
- **Com transação**, o mesmo erro na mesma posição, e o total intacto. O `TransactWriteItems` reverteu a primeira operação sem que o cliente precisasse fazer nada.

**H3 é o ponto para a apresentação.** As duas escritas são idênticas, contra os mesmos itens, com a mesma condição, produzindo o mesmo erro. O banco é o mesmo. O que separa um estoque correto de um estoque com 50 unidades fantasma é **uma decisão de como chamar a API** — e essa decisão é do desenvolvedor, não do DynamoDB.

É o mesmo tipo de conclusão do Cenário B, onde o que separa 58% de 100% de sucesso é o cliente ter ou não backoff. Em ambos, a tolerância a falhas não está inteira no serviço.

## O que este cenário não mede

**Isolamento sob concorrência real.** `TransactWriteItems` oferece as quatro propriedades ACID, mas este cenário exercita atomicidade e consistência. Duas transações simultâneas sobre os mesmos itens não são testadas aqui — a concorrência é assunto do Cenário C, que a trata sem transações.

**Transações que dão certo.** Todas as transferências falham por desenho. O cenário não mede latência nem custo de uma transação bem-sucedida.

## Como reproduzir

```bash
source .venv/bin/activate

for i in 1 2 3; do
  echo "=== execução $i ==="
  python scripts/03_reset.py && python scenarios/cenario_a.py || break
done 2>&1 | tee evidencias/A/execucoes.log
```

Consolidar os resultados em tabela:

```bash
python3 - <<'EOF'
import json, glob
print(f"{'execucao':<28} {'dur_s':>6} {'sem_transacao':>14} {'com_transacao':>14}")
for f in sorted(glob.glob("results/cenario_a_*.json")):
    d = json.load(open(f)); m = d["metricas"]["modos"]
    print(f"{d['execucao_id']:<28} {d['duracao_s']:>6} "
          f"{m['sem_transacao']['unidades_perdidas']:>14} "
          f"{m['com_transacao']['unidades_perdidas']:>14}")
EOF
```
