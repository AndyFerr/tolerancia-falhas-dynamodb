# Cenários de falha

> Entregável da linha **A6**. Fecha o Marco 1 junto com `docs/CONTRATOS.md` (A7) e `docs/RISCOS.md` (A8).
>
> **Versão 2 — projeto de região única.** A conta AWS do grupo foi criada pela nova experiência de cadastro, que atribui uma única região ao projeto e não suporta recursos entre regiões. Global Tables, portanto, está fora. O registro completo dessa restrição e das alternativas descartadas está em `docs/RISCOS.md` (I4).

## O que mudou em relação à versão 1

| Cenário | Antes | Agora |
|---|---|---|
| **A** | falha de região: remover réplica e medir convergência | **atomicidade: escrita parcial vs. transação** |
| **B** | throttling em produto quente | inalterado |
| **C** | conflito entre regiões com last-writer-wins | **concorrência dentro de uma região: atualização perdida vs. escrita condicional** |
| **D** | recuperação via PITR | inalterado |

As letras foram mantidas de propósito: os nomes de arquivo (`scenarios/cenario_a.py`, `results/cenario_a_*.json`) e os endpoints (`/cenario/a`) seguem válidos. O que mudou foi o conteúdo do A e os modos do C.

**O que o projeto perdeu:** disponibilidade sob falha de região (§6.1). Nenhum experimento cobre mais essa promessa, e isso precisa estar escrito no relatório como limitação de ambiente — não omitido.

**O que o projeto ganhou:** o Cenário A passou de três minutos de operação de réplica ao vivo para uma execução de segundos e determinística. O maior risco da apresentação desapareceu junto com a restrição.

## Como ler este documento

Cada cenário tem **hipótese** e **critério de sucesso**, e eles não são a mesma coisa.

A **hipótese** é uma previsão falsificável sobre o comportamento do DynamoDB. Ela pode ser refutada — e refutar é resultado, não fracasso.

O **critério de sucesso da execução** é o que diz se o experimento rodou direito: estado inicial correto, todas as etapas concluídas, métricas gravadas. Uma execução bem-sucedida com hipótese refutada é um bom experimento. Uma execução que não completou não é experimento nenhum.

**Nenhum número esperado entra como critério de aprovação.**

## Visão geral

| Cenário | Pergunta | Mecanismo do paper | Métrica-alvo |
|---|---|---|---|
| **A** | uma operação de dois passos pode deixar estado pela metade? | §3 transações ACID entre itens | unidades perdidas na transferência |
| **B** | o que o admission control faz com carga acima do teto, e quanto depende do cliente? | §4 admission control; §4.4 item quente | vendas perdidas por fase |
| **C** | dois processos vendendo o mesmo produto ao mesmo tempo — o estoque fica certo? | §3 escrita condicional | sobrevendas por modo |
| **D** | dá para desfazer um erro lógico da aplicação? | §5.5 backup e PITR | divergências; checksum |

## Protocolo comum

1. **Reset antes de cada execução.** `scripts/03_reset.py` ou `POST /reset`. Sem estado inicial conhecido, nenhuma métrica significa coisa alguma.
2. **Três execuções por cenário** na fase de desenvolvimento e **duas rodadas completas** na Semana 7.
3. **Toda execução grava arquivo**, inclusive a que falha — com `status: "erro"` e a etapa onde parou.
4. **Nenhum parâmetro muda entre as três execuções.**

---

# Cenário A — escrita parcial vs. transação

## Pergunta

Uma operação que precisa de duas escritas para estar correta pode terminar pela metade? E o que muda quando ela é feita dentro de uma transação?

## O caso

Uma **transferência de estoque** entre dois produtos: tirar 10 unidades de `prod-001` e colocar em `prod-050`. São duas escritas, e o sistema só está correto se as duas acontecerem ou nenhuma acontecer.

A falha é provocada por uma regra de negócio legítima no destino: `prod-050` tem um **limite de prateleira**, e a escrita no destino carrega `ConditionExpression: quantidade <= :limite`. O produto é preparado acima desse limite, então a segunda escrita **sempre falha**.

O resultado é determinístico, roda em segundos e não depende de concorrência nem de temporização.

## O invariante

O número total de unidades no estoque **não pode mudar** durante uma transferência. Unidades mudam de prateleira, não somem.

É essa conservação que o cenário mede — e é um critério que qualquer pessoa da banca entende sem explicação técnica.

## Hipóteses

- **H1 — `sem_transacao`:** a primeira escrita é confirmada e a segunda falha. O total de unidades **diminui**: as unidades saíram da origem e não chegaram ao destino. `estado_parcial = true`.
- **H2 — `com_transacao`:** a mesma condição falha, mas `TransactWriteItems` aborta a operação inteira. O total permanece **exatamente igual** e `prod-001` não é tocado.
- **H3:** a diferença não está no banco. Mesma tabela, mesmos itens, mesma condição, mesmo erro — o que muda é apenas a forma de chamar.

## Procedimento

| Etapa | Ação |
|---|---|
| — | reset; preparar `prod-050` acima do limite de prateleira; registrar `unidades_totais_antes` |
| `modo_sem_transacao` | `UpdateItem` decrementando `prod-001`; em seguida `UpdateItem` incrementando `prod-050` com a condição que falha; capturar o erro |
| — | registrar o total; reset |
| `modo_com_transacao` | as duas mesmas operações dentro de um único `TransactWriteItems`, com a mesma condição; capturar o erro |
| — | registrar o total |

Cinco rodadas de cada modo.

## Critério de sucesso da execução

Os dois modos completam as cinco rodadas, o erro da condição é capturado nas duas (a transferência **deve** falhar — é o desenho) e o total de unidades é medido antes e depois de cada modo.

## O que este cenário não mede

Isolamento sob concorrência real. `TransactWriteItems` oferece as quatro propriedades ACID, mas este cenário exercita atomicidade e consistência, não isolamento entre transações simultâneas.

---

# Cenário B — throttling em produto quente

## Pergunta

O que acontece com uma carga acima da capacidade da tabela, e quanto do resultado final depende do comportamento do cliente e não do banco?

## Hipóteses

- **H1** — Sem tratamento de retry, a maioria das escritas é rejeitada com `ProvisionedThroughputExceededException`, e a fase termina rápido — falhar é barato.
- **H2** — Com backoff exponencial e jitter, a taxa de sucesso se aproxima de 100%, **ao custo de uma duração total muito maior**.
- **H3** — Como a carga se concentra em **um único item**, o throttling **não diminui ao longo da execução**. A §4.4 afirma que tráfego concentrado em um item é um dos dois padrões que o split por consumo não resolve, e que o DynamoDB detecta e evita dividir nesse caso.

H3 testa diretamente uma limitação que o próprio paper declara.

## Procedimento

Roda contra `EstoqueThrottle`, provisionada em 1 WCU — capacidade é configuração fixa da tabela, não algo que o cenário manipula.

| Etapa | Ação |
|---|---|
| — | reset; conferir que `prod-007` existe na tabela de throttling |
| `fase_sem_retry` | 100 vendas em `prod-007` com `aws.cliente(regiao, tentativas=1)`, sem backoff próprio |
| — | reset |
| `fase_com_backoff` | mesma carga, com backoff exponencial e jitter implementado no cenário |

Desligar o retry do SDK é obrigatório nas duas fases: sem isso, o boto3 aplica o backoff dele por baixo e as duas fases medem a mesma coisa.

Para H3, registrar a taxa de throttle **em janelas ao longo da fase 1**, não só o total — é a série temporal que mostra se melhora ou não.

## Critério de sucesso da execução

As duas fases completam as 100 tentativas e gravam contadores.

## O que este cenário não mede

Bursting, adaptive capacity e GAC — todos atuam antes de o cliente ver qualquer coisa.

---

# Cenário C — atualização perdida e sobrevenda

## Pergunta

Dois processos vendem o mesmo produto ao mesmo tempo. O estoque final bate com o que foi vendido?

## O que mudou

Na versão anterior este cenário comparava duas regiões sob last-writer-wins. Sem Global Tables, ele passa a exercitar **concorrência dentro de uma região** — o problema clássico de *lost update*, que o paper trata com escrita condicional (§3).

A mudança não é um rebaixamento: a atualização perdida é o modo de falha mais comum em aplicação real com banco chave-valor, e a demonstração continua sendo a mesma — estoque negativo na tela.

## Hipóteses

- **H1 — `sem_condicao`:** `sobrevendas > 0`. Dois processos leem a mesma quantidade, cada um subtrai e grava o resultado; uma gravação sobrescreve a outra e o decremento se perde. A aplicação confirma vendas que nunca saem da prateleira, **sem nenhum erro aparecer**.
- **H2 — `com_condicao`:** `sobrevendas = 0` e `conflitos_detectados > 0`. A `ConditionExpression` sobre `versao` faz a escrita concorrente falhar explicitamente em vez de sobrescrever.

O achado é o contraste entre perda **silenciosa** e erro **explícito**. Nos dois casos há conflito; a diferença é se a aplicação fica sabendo.

## Procedimento

| Etapa | Ação |
|---|---|
| — | reset; `prod-042` com 100 unidades |
| `modo_sem_condicao` | dois processos paralelos, 50 vendas cada, com leitura seguida de escrita sem condição |
| — | medir `quantidade_final`; reset |
| `modo_com_condicao` | mesma carga, com `ConditionExpression` sobre `versao`; contar `ConditionalCheckFailedException` |
| — | medir `quantidade_final` |

Cinco rodadas de cada modo.

A concorrência real importa: os dois processos precisam começar ao mesmo tempo, com um intervalo deliberado entre a leitura e a escrita para abrir a janela. Se um esperar o outro, não há conflito para observar.

## Critério de sucesso da execução

Os dois modos completam as cinco rodadas e `quantidade_final` é lida depois de todas as escritas terminarem.

## Se a hipótese for refutada

Risco **R3**. Se `sobrevendas` der zero no modo `sem_condicao`, a causa mais provável é janela de concorrência curta demais: aumentar o intervalo entre leitura e escrita e o paralelismo. Se continuar zero com concorrência agressiva, **isso é o achado** — e vai para o relatório como medição, não como experimento com defeito. O que não se faz é ajustar o experimento até ele produzir o número esperado.

## O que este cenário não mede

Resolução de conflito entre réplicas — last-writer-wins só aparece em replicação entre regiões, que esta conta não suporta.

---

# Cenário D — recuperação via PITR

## Pergunta

Quando a própria aplicação corrompe os dados, é possível voltar atrás — e o que volta é exatamente o que havia antes?

## Hipóteses

- **H1** — A restauração devolve o estado exato do instante pedido: `divergencias = 0`, `checksum_antes == checksum_depois`, `valor_antes == valor_restaurado`.
- **H2** — A restauração cria uma **tabela nova** e leva ordem de minutos. Não existe restauração in-place.
- **H3** — A corrupção é invisível para todos os mecanismos de §5.1 a §5.4. Nenhum alarme dispara, nenhuma réplica diverge, o scrub não acusa nada: as escritas foram confirmadas corretamente. Só backup e PITR cobrem este caso.

H3 não se mede com número — demonstra-se pela ausência de qualquer sinal automático. É o argumento central da §5.5.

## Procedimento

| Etapa | Ação |
|---|---|
| — | reset; registrar `unidades_antes`, `valor_antes` e checksum dos 50 produtos |
| — | aguardar alguns minutos para haver um instante de restauração seguro antes da corrupção |
| `corrompendo_quantidade` | `BatchWriteItem` zerando `quantidade` de 40 produtos |
| — | registrar `unidades_apos_corrupcao` e `valor_apos_corrupcao` |
| `restaurando_pitr` | `RestoreTableToPointInTime` para o instante anterior à corrupção, em tabela nova |
| `comparando_itens` | comparar item a item com o estado registrado no início; contar divergências |

## Critério de sucesso da execução

A tabela restaurada fica `ACTIVE`, a comparação roda sobre os 50 produtos e as métricas são gravadas. `divergencias > 0` é resultado válido e interessante.

## Cuidados

- A tabela restaurada **não está no Terraform**. Precisa ser apagada à mão e entra no teardown (risco R9).
- O paper afirma que os backups são consistentes entre partições **até o segundo mais próximo** (§5.5). Testar isso exigiria escrever durante o instante de corte; fica como extensão opcional.

## O que este cenário não mede

A janela de 35 dias do PITR, citada no paper em 2022 e que deve ser conferida na documentação atual da AWS antes de ir para o relatório.

---

# Cobertura e limitação

| Promessa do paper | Cenário | Situação |
|---|---|---|
| Performance previsível (§4) | B | coberta |
| Consistência e concorrência (§3) | C | coberta |
| Durabilidade (§5.5) | D | coberta |
| Atomicidade entre itens (§3) | A | coberta |
| **Disponibilidade sob falha (§6.1)** | — | **não coberta** |

A última linha é a limitação de ambiente, e precisa de um parágrafo próprio no relatório: a conta disponível não suporta recursos entre regiões, então não houve como remover uma réplica regional e medir o comportamento sob perda de região. A fundamentação teórica dessa promessa está em `docs/paper/secao-4-6-capacidade-disponibilidade.md`; o que falta é a medição.

---

# Extensão opcional

**Reconstrução pelo Streams.** Apagar itens e reconstruir o estoque a partir do log de alterações do DynamoDB Streams — o análogo externo do write-ahead log da §5.1.

Com região única essa extensão ficou **mais atraente e menos arriscada** do que era: o risco de o stream carregar registros vindos da replicação entre regiões desapareceu junto com as Global Tables. Agora é só o log das escritas da aplicação.

Se a Semana 6 chegar com folga, é o melhor candidato a quinto cenário — e cobre parcialmente a §5.1, que hoje só aparece na fundamentação teórica.
