# Cenário D — recuperação via PITR

> Entregável das linhas **E4** (desenho) e **F1** (implementação).
> Implementação: `scenarios/cenario_d.py` · Resultados: `results/cenario_d_*.json`

## Pergunta

Quando a própria aplicação corrompe os dados, é possível voltar atrás — e o que volta é exatamente o que havia antes?

## Amarração com o paper

A §5.5 é explícita sobre o propósito: além de proteger contra corrupção de mídia física, o DynamoDB oferece backup e restore **para proteger contra corrupção lógica causada por um bug na aplicação do cliente**. Os backups são construídos a partir dos write-ahead logs arquivados no S3, por isso não afetam performance nem disponibilidade da tabela.

O point-in-time restore permite recuperar o conteúdo de um instante arbitrário dentro da janela de retenção, combinando snapshots periódicos das partições com a reaplicação dos logs até o timestamp pedido.

Este é o único cenário do projeto em que **os mecanismos automáticos não ajudam**. As escritas corrompidas foram confirmadas corretamente: o quórum se formou, as réplicas concordam, nenhum checksum diverge, o scrub não tem o que acusar. Para §5.1 a §5.4, nada aconteceu de errado.

## O caso

O estado inicial é registrado integralmente: todos os 50 produtos, com quantidade e preço, mais um checksum do conjunto.

Em seguida a aplicação **zera a quantidade de 40 produtos** (`prod-001` a `prod-040`) com um `BatchWriteItem` — escritas perfeitamente válidas, confirmadas pelo serviço, e erradas do ponto de vista do negócio. É o bug de atualização em massa que todo mundo já cometeu.

A recuperação é um `RestoreTableToPointInTime` para uma **tabela nova**, apontando para um instante anterior à corrupção. A verificação compara item a item contra o retrato inicial.

## O detalhe de timing que define o procedimento

O PITR **não restaura para "agora"**. O `LatestRestorableDateTime` fica cerca de **cinco minutos atrás** do relógio.

Por isso o cenário escolhe o instante de corte logo após o retrato inicial, espera a corrupção acontecer depois dele, e só então **aguarda ativamente** o PITR alcançar aquele instante antes de pedir a restauração. Sem essa espera, o pedido seria recusado por apontar para um momento ainda não restaurável.

O script verifica também o outro lado da janela: se o `EarliestRestorableDateTime` for posterior ao instante pedido, ele aborta com `TABELA_INDISPONIVEL` em vez de restaurar o estado errado.

## O checksum

A impressão digital do estoque é o SHA-256 dos 50 pares `produto:quantidade:preço`, ordenados, truncado em 8 caracteres. Comparar dois checksums substitui comparar 50 itens a olho — e é o mesmo princípio que a §5.3 descreve no scrub do próprio DynamoDB, que compara réplicas por checksum em vez de transferir os dados.

Além dele, o cenário calcula o **valor total do estoque** (soma de preço × quantidade). É um checksum de negócio: legível por quem não é técnico e sensível a qualquer alteração de quantidade.

## Hipóteses

- **H1** — A restauração devolve o estado exato do instante pedido: `divergencias = 0`, checksums iguais, valor igual.
- **H2** — A restauração cria uma **tabela nova** e leva ordem de minutos. Não existe restauração in-place.
- **H3** — A corrupção é invisível para todos os mecanismos de §5.1 a §5.4. Nenhum alarme dispara, nenhuma réplica diverge. Só backup e PITR cobrem este caso.

## Procedimento

| Etapa | Ação |
|---|---|
| — | `scripts/03_reset.py`; o cenário aborta se a tabela não estiver em 50 produtos / 5000 unidades |
| — | retrato completo, resumo e checksum do estado inicial |
| — | escolhe o instante de corte e o nome da tabela destino |
| `corrompendo_quantidade` | `BatchWriteItem` zerando a quantidade de 40 produtos |
| `restaurando_pitr` | espera o instante virar restaurável, pede o restore, espera a tabela ficar `ACTIVE` |
| `comparando_itens` | retrato da tabela restaurada e comparação item a item com o inicial |

## Resultados medidos

Duas execuções, em dias diferentes, cada uma restaurando para uma tabela própria.

| Execução | Duração total | Tabela restaurada | Divergências | Restauração |
|---|---|---|---|---|
| `d-2026-11-24T060148Z` | 539,8 s | `Estoque_restore_20261124T060152` | **0** | 228 s |
| `d-2026-11-25T021059Z` | 539,5 s | `Estoque_restore_20261125T021103` | **0** | 228 s |

As duas execuções produziram exatamente as mesmas métricas, inclusive o checksum e a duração da restauração:

| Métrica | Valor |
|---|---|
| produtos antes | 50 |
| unidades antes | 5000 |
| valor antes | R$ 317.000 |
| unidades após corrupção | **1000** |
| valor após corrupção | **R$ 47.400** |
| produtos restaurados | 50 |
| unidades restauradas | **5000** |
| valor restaurado | **R$ 317.000** |
| **divergências** | **0** |
| checksum antes | `b96eca48` |
| checksum depois | `b96eca48` |
| duração da restauração | **228 s** |

## Interpretação

**H1 confirmada.** Zero divergências em 50 produtos, checksums idênticos, valor de volta ao centavo. A restauração não é aproximada: devolveu exatamente o conjunto registrado antes da corrupção.

**H2 confirmada.** A tabela restaurada tem nome e ARN próprios, e a origem fica registrada no `RestoreSummary`. A restauração levou **3 minutos e 48 segundos** para 50 itens — e o tempo é dominado pelo provisionamento da tabela nova, não pelo volume de dados. Uma tabela de produção levaria consideravelmente mais.

Some-se a isso a espera pelo instante virar restaurável, e os 539 s totais do cenário mostram o que a recuperação realmente custa em tempo de parede: **cerca de nove minutos entre perceber o erro e ter os dados de volta** — num caso minúsculo, sem contar o tempo humano de decidir restaurar.

**H3 é o argumento do cenário, e não se mede com número.** A corrupção foi feita com escritas legítimas: chave correta, tipos corretos, versão incrementada, confirmadas pelo serviço. Do ponto de vista do DynamoDB nada deu errado — e é justamente por isso que nenhum dos mecanismos das seções anteriores do paper tem o que fazer. A durabilidade descrita em §5.1–§5.4 garante que o dado **não se perca**; ela não tem opinião sobre o dado estar **certo**.

Aqui está a fronteira que o projeto inteiro circula: falha do sistema e falha do usuário do sistema são problemas distintos, e exigem mecanismos distintos. É o único cenário em que a recuperação não é automática — alguém precisa perceber, decidir e comandar.

## Consequências operacionais

Duas, registradas também no `docs/RUNBOOK.md`:

- Depois do cenário, a tabela `Estoque` **fica corrompida**. Rodar `scripts/03_reset.py`.
- A tabela restaurada **não está no Terraform** e não sai no `terraform destroy`. Precisa ser apagada à mão; o script imprime o comando ao final. É o risco **R9** da matriz.

## O que este cenário não mede

**A janela de retenção.** O `describe-continuous-backups` da conta reporta `RecoveryPeriodInDays = 35`, confirmando em 2026 o valor que o paper afirma desde 2022 — mas o cenário restaura para minutos atrás, não testa o limite.

**A consistência "até o segundo mais próximo"** que a §5.5 atribui aos backups entre partições. Testar isso exigiria escrever durante o instante de corte. Fica como extensão opcional.

**Restauração de tabela grande.** Com 50 itens, o tempo medido reflete o custo fixo de criar a tabela, não o de mover dados.

## Como reproduzir

```bash
source .venv/bin/activate
python scripts/03_reset.py && python scenarios/cenario_d.py
```

Reserve dez minutos. **Rode com antecedência e apresente em replay** — é o cenário mais lento do conjunto e o menos adequado para execução ao vivo.

Depois:

```bash
python scripts/03_reset.py
aws dynamodb delete-table --table-name <tabela_restaurada> --region us-east-2
```
