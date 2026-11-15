# Mapa conceito → cenário de falha (§3 + §5)

> Base: Elhemali et al., *Amazon DynamoDB*, USENIX ATC 2022, §3 e §5 (com referências pontuais a §6 quando o mecanismo só fecha lá).
> Uso pretendido: ligar cada mecanismo do paper ao **tipo de falha que ele cobre**, ao **comportamento observável** e ao **seu limite** — é o esqueleto da parte de simulação de falhas do trabalho.

---

## Parte A — Mapa direto: mecanismo → falha coberta

### A.1 Falha de nó e de hardware

| Conceito (§) | Como funciona | Falha que cobre | Comportamento esperado | Limite / o que NÃO cobre |
|---|---|---|---|---|
| **Write-ahead log em 3 réplicas** (§5.1) | todo write é registrado no WAL e replicado antes do ACK | perda de um disco/nó; crash recovery | nenhuma escrita confirmada é perdida | não protege contra erro **lógico** da aplicação |
| **Arquivamento do WAL no S3** (§5.1) | WAL arquivado periodicamente em object store de 11 noves | perda simultânea de réplicas; perda de histórico | histórico reconstruível desde a criação da tabela | WAL recente (centenas de MB) ainda **não arquivado** fica só nas réplicas |
| **Log replica** (§3, §5.1) | réplica só com WAL recente, sem B-tree; análoga a *acceptor* Paxos; **adicionada pelo líder em segundos** | janela de risco enquanto uma storage replica insalubre é reparada (minutos) | quórum de persistência restaurado quase imediatamente; **sem impacto na durabilidade** | não serve dados chave-valor; não substitui a storage replica, só cobre a janela |
| **Cura de storage replica** (§5.1) | copia **B-tree + WAL** de uma réplica saudável | nó perdido de forma definitiva | grupo volta a 3 storage replicas | leva **vários minutos** — por isso existe a log replica |
| **Autoadmin** (§3) | monitora continuamente saúde de partições e da frota; substitui réplicas insalubres (lentas, não responsivas, hardware ruim) e hardware falho | degradação de hardware, nó lento, nó morto | processo de recuperação substitui as réplicas do nó insalubre | reativo a sinais de saúde; não detecta corrupção de conteúdo (isso é o scrub) |
| **Réplicas em AZs diferentes** (§3) | cada partição tem réplicas distribuídas em múltiplas Availability Zones | falha de rack e de AZ inteira | partição sobrevive à perda de uma AZ | perda de região inteira exige **global tables** (§1) |

### A.2 Falha de liderança e de rede

| Conceito (§) | Como funciona | Falha que cobre | Comportamento esperado | Limite / o que NÃO cobre |
|---|---|---|---|---|
| **Multi-Paxos + eleição de líder** (§3) | qualquer réplica pode disparar eleição; par que detecta líder falho se propõe líder | morte do líder da partição | novo líder eleito; escrita volta | **indisponibilidade de alguns segundos** até o lease antigo expirar |
| **Leadership lease** (§3) | líder só continua líder renovando o lease periodicamente | *split brain* (dois líderes atendendo escrita) | novo líder **não atende** escrita nem leitura forte antes da expiração do lease anterior | o preço da segurança é latência de failover |
| **Quórum de escrita** (§3; definido em §6.1 como 2 de 3 em AZs distintas) | ACK ao cliente só após quórum de peers persistir o log | perda de 1 das 3 réplicas | escrita continua disponível | perder o quórum = partição **indisponível para escrita** (preserva durabilidade, sacrifica disponibilidade) |
| **Leitura eventualmente consistente em qualquer réplica** (§3) | followers atendem leitura eventual | falha/eleição de líder | leitura eventual **continua funcionando** durante o failover | pode devolver dado desatualizado |
| **Detecção de falha com confirmação entre pares** (§6.2 — complementa §3) | follower que quer disparar failover pergunta aos outros se eles falam com o líder; se respondem "líder saudável", desiste | **gray network failures** (falha parcial de rede) | elimina a maior parte dos falsos positivos e das eleições espúrias | não remove a janela de lease quando o failover é real |

### A.3 Corrupção silenciosa (hardware bugs)

| Conceito (§) | Como funciona | Falha que cobre | Comportamento esperado | Limite / o que NÃO cobre |
|---|---|---|---|---|
| **Checksum por entrada de log, mensagem e arquivo** (§5.2) | integridade validada em **todo** transporte entre dois nodes | corrupção por mídia, CPU ou memória; corrupção introduzida por camadas de transformação da mensagem | erro é detectado na borda e **não se propaga** | detecta, não corrige sozinho — a correção vem da réplica/log bom |
| **Manifesto + checagens pré-upload** (§5.2) | antes de arquivar: entrada pertence à tabela/partição correta, checksums válidos, **sem buracos na sequência** | arquivamento de log incompleto ou trocado | arquivo só vai para o S3 se passar em tudo | cobre o arquivamento, não a réplica viva |
| **Verificação cruzada entre os 3 agentes de arquivamento** (§5.2) | agente que vê o arquivo já arquivado **baixa e compara com o WAL local** | divergência entre o que foi arquivado e o que a réplica tem | divergência detectada por uma segunda fonte independente | custo de banda/IO; detecção, não prevenção |
| **Content checksum verificado pelo S3 no PUT** (§5.2) | checksum enviado junto e validado pelo S3 | corrupção **em trânsito** até o S3 | put rejeitado se não bater | não cobre corrupção anterior ao cálculo do checksum |
| **Scrub / verificação contínua** (§5.3) | verifica (1) as 3 réplicas têm os mesmos dados e (2) réplica viva bate com réplica reconstruída offline do WAL arquivado | **bit rot** e erros em repouso **não antecipados**; divergência acumulada | divergência contra a história completa dos logs é detectada | processo de fundo; detecta depois do fato, não no instante da escrita |

### A.4 Bugs de software

| Conceito (§) | Como funciona | Falha que cobre | Comportamento esperado | Limite / o que NÃO cobre |
|---|---|---|---|---|
| **TLA+ e model checking do protocolo de replicação** (§5.4) | protocolo central especificado em TLA+; features novas entram na especificação e são model-checked | bugs **subtis** de corretude/durabilidade no protocolo | bug capturado **antes de ir para produção** | prova o modelo, não a implementação inteira |
| **Failure injection + stress testing** (§5.4) | testes extensivos de cada peça de software implantada | bugs de implementação sob falha e sob carga | falhas aparecem em teste | cobertura empírica, nunca exaustiva |
| **Métodos formais no control plane e nas transações** (§5.4) | mesma técnica aplicada fora do data plane | bugs em control plane e em transações distribuídas | corretude verificada | — |
| **Power-off tests / game days** (§6, §1) | nós aleatórios desligados com tráfego simulado; ao fim, as ferramentas verificam se os dados são **logicamente válidos e não corrompidos** | falha de nó, rack e AZ **na prática** | resiliência validada de ponta a ponta | é teste do provedor, não do cliente |

### A.5 Corrupção lógica (bug da aplicação do cliente)

| Conceito (§) | Como funciona | Falha que cobre | Comportamento esperado | Limite / o que NÃO cobre |
|---|---|---|---|---|
| **Backup on-demand** (§5.5) | cópia completa da tabela construída a partir do WAL arquivado no S3; consistente entre partições **até o segundo mais próximo** | deleção/escrita indevida pela aplicação; necessidade de cópia de longo prazo | restore para uma **tabela nova**, a qualquer momento | granularidade de 1 segundo; não é restore in-place |
| **Point-in-time restore** (§5.5) | snapshots periódicos das partições no S3 + reaplicação do WAL até o timestamp pedido | voltar a tabela a **qualquer instante dos 35 dias anteriores** | tabela nova com o estado de T, na mesma região | janela de 35 dias (valor do paper, 2022 — **confirmar o limite atual na doc AWS**); destino é outra tabela |
| **Escrita condicional** (§3) | operação de put/update/delete só sucede se a condição for satisfeita | sobrescrita concorrente indevida; update cego | operação falha em vez de corromper | previne, não repara |
| **Transações ACID entre itens** (§3) | atomicidade/consistência/isolamento/durabilidade entre múltiplos itens | estado parcialmente aplicado em escrita multi-item | tudo ou nada | escopo de itens, não de tabelas inteiras |

---

## Parte B — Mapa reverso: cenário de falha → cadeia de reação

Esta é a visão útil na hora de escrever a seção de análise do trabalho: para cada falha, **que mecanismos entram, em que ordem, e o que o cliente percebe**.

### B.1 Disco/nó de storage morre

```
t0   nó falha
     └─ todos os replication groups daquele nó caem para 2 cópias        §5.1
t0+s líder detecta réplica insalubre
     └─ ADICIONA LOG REPLICA (segundos, só WAL recente)                  §5.1
     └─ quórum de escrita restaurado                                     §6.1
t0+s autoadmin detecta nó insalubre
     └─ dispara recuperação: substitui réplicas do nó                    §3
t0+m cura da storage replica (copia B-tree + WAL)                        §5.1
     └─ grupo volta a 3 storage replicas
```

**Percepção do cliente:** nenhuma perda de dado; escrita segue disponível (quórum mantido). É o caminho desenhado para ser invisível.

### B.2 Líder da partição morre

```
t0   líder para de renovar o lease / para de responder
t0   followers detectam falha
     └─ follower pergunta aos pares: "vocês falam com o líder?"          §6.2
     └─ se ninguém fala → propõe eleição (Multi-Paxos)                   §3
t0+  novo líder eleito, MAS espera a expiração do lease antigo           §3
     └─ nesse intervalo (segundos): SEM escrita, SEM leitura forte
     └─ leitura eventualmente consistente continua em qualquer réplica    §3
t1   lease expira → novo líder passa a servir escrita e leitura forte
```

**Percepção do cliente:** janela curta de erro em escrita e leitura forte. Leitura eventual não é afetada. (Em deploy planejado o líder **entrega a liderança voluntariamente**, e o novo líder não precisa esperar o lease — §6.4.)

### B.3 Bit rot em uma réplica

```
fundo   scrub compara checksum das 3 réplicas                            §5.3
        scrub compara réplica viva × réplica reconstruída do WAL do S3   §5.3
        └─ divergência detectada
        └─ réplica divergente é tratada como insalubre
           → substituição via autoadmin / recuperação a partir do log    §3, §5.1
```

**Percepção do cliente:** nenhuma — desde que a detecção ocorra antes de a réplica divergente servir uma leitura. É por isso que o paper trata checksum em cada transferência (§5.2) como guard-rail complementar ao scrub.

### B.4 Aplicação do cliente apaga/corrompe dados

```
t0   DeleteItem / UpdateItem errado é COMMITADO corretamente
     └─ §5.1 a §5.4 não ajudam: o sistema fez exatamente o que foi pedido
t1   operador solicita point-in-time restore para o instante T < t0      §5.5
     └─ identifica snapshots mais próximos de T em TODAS as partições
     └─ reaplica WAL até o timestamp T
     └─ cria snapshot e restaura em uma TABELA NOVA
t2   verificação: comparar tabela restaurada × estado esperado
```

**Percepção do cliente:** recuperação é manual, deliberada e gera nova tabela. Este é o único cenário de §5 em que a recuperação **não é automática**.

### B.5 Falha de AZ inteira

```
t0   AZ indisponível → uma das 3 réplicas de cada partição afetada cai
     └─ réplicas estão em AZs distintas por projeto                      §3
     └─ quórum 2-de-3 em AZs distintas ainda alcançável                  §6.1
     └─ se a réplica perdida era o líder → B.2
     └─ líder adiciona log replica em AZ saudável                        §5.1
     └─ autoadmin realoca réplicas para nós de outra AZ                  §3, §4.3
```

---

## Parte C — Limites honestos de §3/§5 (bons parágrafos de discussão)

1. **Durabilidade e disponibilidade são negociadas, não garantidas juntas.** Se o quórum de escrita não é alcançável, a partição fica **indisponível para escrita** — o sistema prefere parar a aceitar escrita sem quórum. Preserva o requisito de §5 ao custo do de §6.
2. **A janela do lease é indisponibilidade de projeto.** Nenhum mecanismo de §5 a elimina; §6.2 apenas reduz quantas vezes ela acontece sem necessidade (falsos positivos).
3. **O WAL mais recente é o ponto mais frágil da cadeia.** Centenas de MB por réplica ainda não arquivados no S3 — e é exatamente esse intervalo que a log replica existe para proteger (§5.1).
4. **Detecção ≠ correção.** Checksum e scrub **detectam**; a correção sempre vem de outra cópia (réplica saudável ou log arquivado). Sem uma cópia boa, a detecção só evita servir dado corrompido.
5. **Método formal cobre o modelo, não o binário.** Por isso §5.4 combina TLA+ com failure injection, stress testing e os power-off tests de §6.
6. **Nada em §5.1–§5.4 protege contra erro da aplicação.** Essa fronteira (falha do sistema × falha do usuário do sistema) é o argumento central de §5.5.

---

## Parte D — Ponte para a simulação de falhas do trabalho

> Esta parte **não** está no paper: é a tradução dos mecanismos acima em experimentos observáveis. Marcada separadamente de propósito.

O ponto de atenção metodológico: em DynamoDB gerenciado o grupo não pode matar storage nodes, forçar eleição de líder nem corromper um setor de disco. **Os mecanismos de §3/§5 não são injetáveis pelo cliente** — só seus *efeitos de ponta a ponta* são observáveis. O desenho do experimento precisa assumir isso.

| Mecanismo do paper | O que dá para observar de fato | Como |
|---|---|---|
| PITR (§5.5) | recuperação completa de corrupção lógica | apagar/corromper um conjunto conhecido de itens, restaurar para T anterior em tabela nova, comparar item a item |
| Backup on-demand (§5.5) | consistência entre partições "até o segundo mais próximo" | escrever em várias partições durante o backup e verificar o corte temporal |
| Escrita condicional (§3) | prevenção de sobrescrita concorrente | dois clientes concorrentes com e sem condição; contar escritas perdidas |
| Transação ACID (§3) | atomicidade multi-item | transação que falha no meio; verificar ausência de estado parcial |
| Leitura forte × eventual (§3) | janela de divergência entre réplicas | escrever e ler imediatamente nos dois modos, medir divergência |
| Quórum e failover (§3, §6.1–6.2) | apenas o efeito agregado | medir latência/erros em carga sustentada e observar outliers de failover; **não** é falha induzida |
| Scrub (§5.3) | nada diretamente | tratar como mecanismo interno; discutir conceitualmente, não experimentalmente |

Alternativa para o que não é injetável na nuvem: **reproduzir o mecanismo em ambiente controlado** (p. ex. um pequeno grupo Raft/Paxos local, ou DynamoDB Local sem replicação para contrastar) e usar o paper como referência de comportamento esperado. Isso rende uma seção de "por que a simulação direta não é possível e o que foi feito no lugar" — que normalmente vale mais nota do que um experimento mal fundamentado.

---

## Referência

Mostafa Elhemali, Niall Gallagher, Nicholas Gordon, Joseph Idziorek, Richard Krog, Colin Lazier, Erben Mo, Akhilesh Mritunjai, Somu Perianayagam, Tim Rath, Swami Sivasubramanian, James Christopher Sorenson III, Sroaj Sosothikul, Doug Terry, Akshat Vig. **Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL Database Service.** 2022 USENIX Annual Technical Conference (ATC '22), pp. 1037–1048.
