# Cenários de falha

> Entregável da linha **A6**. Fecha o Marco 1 junto com `docs/CONTRATOS.md` (A7) e `docs/RISCOS.md` (A8).
>
> Formato dos dados e das métricas: `docs/CONTRATOS.md`. Fundamentação: `docs/paper/`.

## Como ler este documento

Cada cenário tem **hipótese** e **critério de sucesso**, e eles não são a mesma coisa.

A **hipótese** é uma previsão falsificável sobre o comportamento do DynamoDB. Ela pode ser refutada — e refutar é resultado, não fracasso.

O **critério de sucesso da execução** é o que diz se o experimento rodou direito: estado inicial correto, todas as etapas concluídas, métricas gravadas. Uma execução bem-sucedida com hipótese refutada é um bom experimento. Uma execução que não completou não é experimento nenhum.

**Nenhum número esperado entra como critério de aprovação.** Se o Cenário C medir zero sobrevendas, isso é um achado sobre a janela de concorrência ou sobre a replicação, e vai para o relatório como tal.

## Visão geral

| Cenário | Pergunta | Mecanismo do paper | Métrica-alvo |
|---|---|---|---|
| **A** | a aplicação continua escrevendo com uma região fora, e quando o dado reaparece lá? | §3 replicação; §6.1 quórum | vendas aceitas; tempo de convergência |
| **B** | o que o admission control faz com carga acima do teto, e quanto depende do cliente? | §4 admission control; §4.4 item quente | vendas perdidas por fase |
| **C** | o que acontece quando duas regiões vendem o mesmo produto ao mesmo tempo? | §3 escrita condicional; replicação LWW | sobrevendas por modo |
| **D** | dá para desfazer um erro lógico da aplicação? | §5.5 backup e PITR | divergências; checksum |

## Protocolo comum

Vale para os quatro:

1. **Reset antes de cada execução.** `scripts/03_reset.py` ou `POST /reset`. Sem estado inicial conhecido, nenhuma métrica significa coisa alguma. O erro `ESTOQUE_NAO_RESETADO` existe para abortar em vez de produzir número inválido.
2. **Três execuções por cenário** na fase de desenvolvimento (linha C4) e **duas rodadas completas** na Semana 7 (linha G1). Uma medição isolada em sistema distribuído é anedota, não dado.
3. **Toda execução grava arquivo**, inclusive a que falha — com `status: "erro"` e a etapa onde parou.
4. **Nenhum parâmetro muda entre as três execuções.** Variar e repetir ao mesmo tempo impede saber a que atribuir a diferença.

---

# Cenário A — falha de região

## Pergunta

Com uma região indisponível, a aplicação continua aceitando vendas? Quando a região volta, quanto tempo até ela refletir o que foi vendido na ausência dela?

## O que este cenário realmente mede

Ponto que precisa estar claro no relatório, porque é fácil errar: remover uma réplica de **Global Table** retira uma **cópia regional inteira** — não um membro do quórum Paxos.

O quórum de duas em três réplicas em AZs distintas (§6.1) é interno a **cada região**: cada região tem o seu próprio replication group por partição. Remover a réplica de `us-east-1` não toca no grupo de replicação de `sa-east-1`, que permanece íntegro.

Portanto este cenário mede a **replicação assíncrona entre regiões** das Global Tables, e não o consenso Multi-Paxos da §3. A ligação com §6.1 é por **contraste**, e é justamente o que torna a discussão interessante: dois mecanismos de tolerância a falhas em camadas diferentes, com garantias diferentes.

## Hipóteses

- **H1** — A taxa de aceitação de escrita em `sa-east-1` permanece em 100% durante toda a ausência de `us-east-1`, porque o grupo de replicação local está intacto e a perda é de uma cópia regional.
- **H2** — Após a réplica ser recriada, a convergência leva **ordem de minutos**, não de segundos, porque recriar réplica de Global Table copia a tabela inteira (backfill), não apenas o delta.
- **H3** — Em regime normal, com as três réplicas no ar, a propagação de uma escrita entre regiões leva **ordem de segundos**.

O contraste entre H2 e H3 é o achado principal: o mesmo sistema tem dois tempos de convergência muito diferentes, conforme a réplica esteja sendo reconstruída ou apenas acompanhando.

## Procedimento

| Etapa | Ação |
|---|---|
| — | reset e medição da linha de base: escrever 1 item e cronometrar a propagação às 3 regiões (**H3**) |
| `removendo_replica` | `UpdateTable` com `ReplicaUpdates: [{Delete: {RegionName: "us-east-1"}}]`; aguardar a tabela voltar a `ACTIVE` |
| `vendendo_durante_queda` | 100 vendas distribuídas entre os 50 produtos, escrevendo em `sa-east-1`, contando aceitas e rejeitadas |
| `recriando_replica` | `UpdateTable` com `ReplicaUpdates: [{Create: ...}]` |
| `medindo_convergencia` | consultar `resumo_regiao` em `us-east-1` até `unidades` igualar as outras duas; cronometrar (**H2**) |

## Critério de sucesso da execução

As cinco etapas concluem, a réplica volta a `ACTIVE` e `unidades_por_regiao` fica igual nas três regiões dentro do tempo limite. Qualquer valor de `vendas_aceitas` e `tempo_convergencia_ms` é resultado válido.

## O que este cenário não mede

Eleição de líder, janela de lease, falha de AZ, falha de nó. Nenhum desses é provocável pelo cliente — ver `docs/paper/mapa-conceito-cenario-falha.md`, parte D.

---

# Cenário B — throttling em produto quente

## Pergunta

O que acontece com uma carga acima da capacidade da tabela, e quanto do resultado final depende do comportamento do cliente e não do banco?

## Hipóteses

- **H1** — Sem tratamento de retry, a maioria das escritas é rejeitada com `ProvisionedThroughputExceededException`, e a fase termina rápido — falhar é barato.
- **H2** — Com backoff exponencial e jitter, a taxa de sucesso se aproxima de 100%, **ao custo de uma duração total muito maior**. O banco é o mesmo; o que muda é o cliente.
- **H3** — Como a carga se concentra em **um único item**, o throttling **não diminui ao longo da execução**. A §4.4 afirma que tráfego concentrado em um item é um dos dois padrões que o split por consumo não resolve, e que o DynamoDB detecta e evita dividir nesse caso.

H3 é a hipótese mais valiosa: ela testa diretamente uma limitação que o próprio paper declara.

## Procedimento

Roda contra `EstoqueThrottle`, que já está provisionada em 1 WCU — a capacidade é configuração fixa da tabela, não algo que o cenário manipula.

| Etapa | Ação |
|---|---|
| — | reset; conferir que `prod-007` existe na tabela de throttling |
| `fase_sem_retry` | 100 vendas em `prod-007` com `aws.cliente(regiao, tentativas=1)`, sem backoff próprio; contar sucesso, throttle e duração |
| — | reset |
| `fase_com_backoff` | mesma carga, com backoff exponencial e jitter implementado no cenário; contar sucesso, throttle, tentativas totais e duração |

Desligar o retry do SDK é obrigatório nas duas fases. Sem isso, o boto3 aplica o backoff dele por baixo e as duas fases medem a mesma coisa.

Para H3, registrar a taxa de throttle **em janelas ao longo da fase 1**, não só o total — é a série temporal que mostra se melhora ou não.

## Critério de sucesso da execução

As duas fases completam as 100 tentativas e gravam contadores. A diferença entre elas, qualquer que seja, é o resultado.

## O que este cenário não mede

Bursting, adaptive capacity e GAC. Todos atuam antes de o cliente ver qualquer coisa, e o sucesso deles é a ausência de sintoma — ver `docs/paper/secao-4-6-capacidade-disponibilidade.md`, parte III.

---

# Cenário C — conflito e sobrevenda

## Pergunta

Quando duas regiões vendem a mesma unidade ao mesmo tempo, quem ganha, e a escrita condicional impede o estoque de ficar errado?

## Hipóteses

Três modos, uma hipótese cada:

- **H1 — `sem_condicao`:** `sobrevendas > 0`. Os decrementos são escritas completas de item; a resolução last-writer-wins faz uma sobrescrever a outra, e o estoque final fica **acima** do esperado. A aplicação confirmou vendas que nunca saíram da prateleira.
- **H2 — `com_condicao_multi_regiao`:** `sobrevendas` continua `> 0`. A `ConditionExpression` é avaliada contra a **réplica local** da região que recebe a escrita, e não enxerga a escrita concorrente em curso na outra região.
- **H3 — `com_condicao_regiao_unica`:** `sobrevendas = 0` e `conflitos_detectados > 0`. É o **grupo de controle**: mesma concorrência, mesma condição, uma região só — aqui a condição funciona.

O achado é a diferença entre H2 e H3. Ela separa duas coisas que costumam ser confundidas: escrita condicional protege contra concorrência **dentro de uma região**, e não é mecanismo de coordenação **entre regiões**.

## Procedimento

| Etapa | Ação |
|---|---|
| — | reset; `prod-042` com 100 unidades |
| `modo_sem_condicao` | 50 vendas a partir de `sa-east-1` e 50 a partir de `eu-west-1`, simultâneas, sem condição |
| `aguardando_convergencia` | consultar as duas regiões até concordarem; cronometrar |
| — | reset; repetir com `ConditionExpression` sobre `versao` |
| — | reset; repetir com condição e as 100 vendas partindo só de `sa-east-1` |

Cinco rodadas de cada modo, registrando vencedor e tempo de convergência por rodada, mais p50 e p95.

A simultaneidade real importa: as vendas das duas regiões precisam partir ao mesmo tempo, em threads ou processos paralelos. Se uma fila esperar a outra, não há conflito para observar.

## Critério de sucesso da execução

Os três modos completam as cinco rodadas, as regiões convergem dentro do tempo limite e `quantidade_final` é lida depois da convergência — nunca durante.

## Se a hipótese for refutada

Risco **R3** da matriz. Se `sobrevendas` der zero no modo `sem_condicao`, a causa mais provável é janela de concorrência curta demais: aumentar o paralelismo e reduzir o intervalo entre escritas. Se continuar zero com concorrência agressiva, **isso é o achado** — e vai para o relatório como medição do comportamento da replicação, não como experimento com defeito. O que não se faz é ajustar o experimento até ele produzir o número esperado.

## O que este cenário não mede

O critério interno de desempate do DynamoDB. O campo `atualizado_em` é carimbo da aplicação; o serviço usa um timestamp próprio, que não é exposto. Observa-se quem venceu, não por quê.

---

# Cenário D — recuperação via PITR

## Pergunta

Quando a própria aplicação corrompe os dados, é possível voltar atrás — e o que volta é exatamente o que havia antes?

## Hipóteses

- **H1** — A restauração devolve o estado exato do instante pedido: `divergencias = 0`, `checksum_antes == checksum_depois`, `valor_antes == valor_restaurado`.
- **H2** — A restauração cria uma **tabela nova** e leva ordem de minutos. Não existe restauração in-place; recuperar é uma operação deliberada, com downtime de decisão humana.
- **H3** — A corrupção é invisível para todos os mecanismos de §5.1 a §5.4. Nenhum alarme dispara, nenhuma réplica diverge, o scrub não acusa nada: as escritas foram confirmadas corretamente. Só backup e PITR cobrem este caso.

H3 não se mede com número — demonstra-se pela ausência de qualquer sinal automático. É o argumento central da §5.5 e a razão de este cenário existir.

## Procedimento

| Etapa | Ação |
|---|---|
| — | reset; registrar `unidades_antes`, `valor_antes` e checksum dos 50 produtos |
| — | aguardar alguns minutos para haver um instante de restauração seguro antes da corrupção |
| `corrompendo_quantidade` | `BatchWriteItem` zerando `quantidade` de 40 produtos — simula bug de atualização em massa |
| — | registrar `unidades_apos_corrupcao` e `valor_apos_corrupcao` |
| `restaurando_pitr` | `RestoreTableToPointInTime` para o instante anterior à corrupção, em tabela nova |
| `comparando_itens` | comparar item a item a tabela restaurada com o estado registrado no início; contar divergências |

## Critério de sucesso da execução

A tabela restaurada fica `ACTIVE`, a comparação roda sobre os 50 produtos e as métricas são gravadas. `divergencias > 0` é resultado válido e muito interessante — significaria que a janela de restauração não pegou o instante pretendido.

## Cuidados

- A tabela restaurada **não está no Terraform**. Precisa ser apagada à mão, e entra no teardown (risco R9).
- Verificar se a tabela restaurada vem como Global Table ou como tabela de região única — isso muda o que a comparação significa.
- O paper afirma que os backups são consistentes entre partições **até o segundo mais próximo** (§5.5). Testar isso exigiria escrever durante o instante de corte; fica registrado como extensão opcional, não como parte do cenário.

## O que este cenário não mede

A janela de 35 dias do PITR, citada no paper em 2022 e que deve ser conferida na documentação atual da AWS antes de ir para o relatório.

---

# Extensão opcional

Se a Semana 6 chegar com folga, dois candidatos, em ordem de custo:

**Escrita parcial vs. transação** (meio dia). Uma transferência entre dois produtos que falha no meio, com e sem `TransactWriteItems`. Sem transação, o estado parcial fica visível; com, nada acontece. Instantâneo, determinístico e o melhor momento possível de apresentação.

**Reconstrução pelo Streams** (dois dias). Apagar itens e reconstruir o estoque a partir do log de alterações do DynamoDB Streams — o análogo externo do write-ahead log da §5.1. Risco conhecido: o stream de uma Global Table carrega também os registros vindos da replicação, e reaplicá-los duplicaria os decrementos; filtrar por `regiao_escrita` (risco R13).

Se nenhuma das duas couber, ambas rendem parágrafo de trabalhos futuros no relatório.
