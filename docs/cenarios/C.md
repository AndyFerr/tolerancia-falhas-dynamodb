# Cenário C — atualização perdida e sobrevenda

> Entregável das linhas **E1** (metodologia) e **E2** (implementação).
> Implementação: `scenarios/cenario_c.py` · Resultados: `results/cenario_c_*.json`

## Pergunta

Dois processos vendem o mesmo produto ao mesmo tempo. O estoque final bate com o que foi vendido?

## Amarração com o paper

A §3 descreve que qualquer operação de inserção, atualização ou remoção pode levar uma **condição que precisa ser satisfeita para a operação ter sucesso**. Este cenário mede o que acontece com e sem essa condição, sob concorrência.

O problema que ele expõe — *lost update* — é clássico em banco chave-valor: duas leituras do mesmo valor, dois cálculos sobre ele, duas escritas, e a segunda apaga a primeira sem que ninguém perceba.

> **Nota de escopo.** Na versão original do projeto este cenário comparava duas regiões sob resolução last-writer-wins das Global Tables. A conta disponível não suporta recursos entre regiões (ver `docs/RISCOS.md`, I4), então ele passou a exercitar concorrência **dentro de uma região**. A mudança não é um rebaixamento: a atualização perdida é o modo de falha mais comum em aplicação real, e a demonstração continua a mesma.

## O caso

`prod-042` começa com 100 unidades. Dois processos vendem 50 unidades cada, simultaneamente. O total vendido é exatamente o estoque disponível, então o esperado é terminar em zero.

Cada venda é um ciclo **ler → esperar → gravar**:

1. lê `quantidade` e `versao` com leitura fortemente consistente;
2. espera 20 ms (`JANELA_S`), que é a janela de concorrência;
3. grava `quantidade = q − 1` — valor **absoluto**, calculado pela aplicação.

A escrita absoluta é deliberada: é ela que torna a atualização perdida possível. Um `quantidade = quantidade - 1` feito pelo próprio DynamoDB seria atômico e não produziria o fenômeno.

Os dois processos começam juntos por uma `threading.Barrier`, para que a concorrência seja real e não sequencial.

## Hipóteses

- **H1 — `sem_condicao`:** `sobrevendas > 0`. Uma escrita sobrescreve a outra; o decremento se perde. A aplicação confirma vendas que nunca saem da prateleira, **sem nenhum erro aparecer**.
- **H2 — `com_condicao`:** `sobrevendas = 0` e `conflitos_detectados > 0`. A `ConditionExpression` sobre `versao` faz a escrita concorrente falhar explicitamente em vez de sobrescrever.

O achado é o contraste entre perda **silenciosa** e erro **explícito**. Nos dois casos há conflito; a diferença é se a aplicação fica sabendo.

## Procedimento

| Etapa | Ação |
|---|---|
| — | `scripts/03_reset.py`; o cenário aborta se `prod-042` não estiver com 100 unidades |
| `modo_sem_condicao` | 5 rodadas; em cada uma, 2 processos × 50 vendas sem condição |
| `modo_com_condicao` | 5 rodadas iguais, com `ConditionExpression: versao = :v` |

O produto volta a 100 unidades no início de **cada rodada**. As métricas de cada modo são a soma das 5 rodadas; o detalhe individual fica em `por_rodada`.

Uma venda recusada pela condição **não é repetida**: ela conta como conflito e a venda não é confirmada. Isso é deliberado — o cenário mede o que a condição protege, não o que uma política de retry recuperaria.

## Resultados medidos

Duas execuções, em dias diferentes.

| Execução | Duração | `sem_condicao` — sobrevendas | `com_condicao` — sobrevendas | `com_condicao` — conflitos |
|---|---|---|---|---|
| `c-2026-11-23T222012Z` | 149,2 s | **248** | **0** | 250 |
| `c-2026-11-25T002542Z` | 148,1 s | **249** | **0** | 250 |

Detalhe da primeira execução:

| Métrica (soma de 5 rodadas) | `sem_condicao` | `com_condicao` |
|---|---|---|
| vendas confirmadas | 500 | 250 |
| quantidade esperada | 0 | 250 |
| quantidade final | **248** | **250** |
| **sobrevendas** | **248** | **0** |
| conflitos detectados | 0 | 250 |

Por rodada, `sem_condicao`: sobrevendas de 50, 50, 49, 50, 49 na primeira execução e 50, 49, 50, 50, 50 na segunda. O estoque final de cada rodada é o mesmo número, quando o esperado era zero.

Por rodada, `com_condicao`: 50 vendas confirmadas, 50 conflitos, estoque final exatamente 50, sobrevendas zero. Nas dez rodadas das duas execuções, sem variação.

## Interpretação

**H1 e H2 confirmadas, com margem larga.**

Sem condição, **metade das vendas confirmadas nunca existiu**. Na primeira execução, a aplicação disse "vendido" 500 vezes; 252 unidades saíram da prateleira. A segunda repetiu o padrão, com 249 sobrevendas. Em um sistema real, são 248 clientes esperando um produto que não há.

O número ser tão próximo de exatamente metade não é coincidência: com dois processos alternando dentro de uma janela de 20 ms, quase toda venda de um colide com a venda do outro, e cada colisão descarta um decremento. O par vira um.

Com condição, o estoque fica **exato nas cinco rodadas**. E o preço aparece na mesma tabela: das 100 tentativas por rodada, 50 foram recusadas. A condição não fez mais vendas acontecerem — ela transformou **corrupção silenciosa em erro visível**.

Essa é a frase do cenário. A escrita condicional não elimina o conflito: ela o torna observável. O que a aplicação faz com os 50 conflitos — repetir, enfileirar, avisar o cliente — passa a ser uma decisão possível, porque agora existe um erro para tratar. Sem condição, não há nada para decidir, porque não há nada para ver.

É o mesmo padrão dos Cenários A e B: o DynamoDB oferece o mecanismo, e a corretude depende de o cliente usá-lo.

## O que este cenário não mede

**Resolução de conflito entre réplicas.** Last-writer-wins só aparece em replicação entre regiões, que esta conta não suporta.

**Política de retry sobre o conflito.** As vendas recusadas são perdidas de propósito. Medir quanto uma política de repetição recuperaria seria outro experimento.

**O custo da condição.** A duração total de 149 s cobre os dois modos somados e não foi separada por modo, então o cenário não quantifica a latência adicional da escrita condicional.

## Risco associado

O **R3** da matriz previa que o cenário pudesse não produzir sobrevenda alguma, caso a janela de concorrência fosse curta demais — e orientava a aumentar `JANELA_S` e o paralelismo antes de concluir qualquer coisa. Com 20 ms, o fenômeno apareceu com folga, e o risco não se materializou.

## Como reproduzir

```bash
source .venv/bin/activate
python scripts/03_reset.py && python scenarios/cenario_c.py
```

Leva cerca de dois minutos e meio. Se alguma execução futura devolver `sobrevendas = 0` no modo sem condição, aumente `JANELA_S` em `scenarios/cenario_c.py` antes de tirar conclusões.
