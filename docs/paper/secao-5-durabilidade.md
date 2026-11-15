# §5 — Durabilidade e corretude (estudo dirigido)

> Fonte: Elhemali et al., *Amazon DynamoDB*, USENIX ATC 2022, §5 (pp. 1043–1044).
> Paráfrase do original; `§5.x` aponta para a subseção.

---

## 0. A premissa da seção

A frase de abertura é o requisito que organiza tudo: *"Data should never be lost after it has been committed."* (§5, p. 1043) — ou seja, **dado confirmado ao cliente nunca pode ser perdido**.

Na prática, perda de dados pode acontecer por três causas, e o DynamoDB é projetado com mecanismos para **prevenir, detectar e corrigir** cada uma:

```
       CAUSA                        MECANISMO PRINCIPAL          SUBSEÇÃO
┌──────────────────────┐
│ falhas de hardware   │ ──────▶  WAL + 3 réplicas + S3 + log replica   §5.1
├──────────────────────┤
│ erros silenciosos    │ ──────▶  checksums em tudo + scrub             §5.2 / §5.3
│ (hardware bugs)      │
├──────────────────────┤
│ bugs de software     │ ──────▶  TLA+ / model checking / fault inject. §5.4
├──────────────────────┤
│ corrupção LÓGICA     │ ──────▶  backup e point-in-time restore        §5.5
│ (bug do cliente)     │
└──────────────────────┘
```

O quarto caso é conceitualmente diferente: não é falha do DynamoDB, é a aplicação do cliente gravando dados errados — e exige um mecanismo totalmente diferente (voltar no tempo, não reparar réplica).

---

## 1. §5.1 — Falhas de hardware

**O write-ahead log é o centro da durabilidade e do crash recovery.**

Onde o WAL vive:

| Camada | O que guarda | Durabilidade |
|---|---|---|
| 3 réplicas da partição | WAL completo recente | local, replicado em AZs |
| Amazon S3 (arquivamento periódico) | WAL arquivado | S3 é projetado para **11 noves** de durabilidade |

- O WAL é armazenado **em todas as três réplicas** de uma partição.
- Para durabilidade ainda maior, os WALs são **periodicamente arquivados no S3**.
- Cada réplica **ainda mantém o WAL mais recente**, normalmente aguardando arquivamento. Esses logs não arquivados têm tipicamente **algumas centenas de megabytes**.

**O que acontece quando um node falha:**

Em um serviço grande, falhas de hardware (memória, disco) são **comuns**. Quando um node falha, **todos os replication groups hospedados nele ficam reduzidos a duas cópias**.

```
ANTES                          NODE FALHA                  REAÇÃO (segundos)
┌──────┐ ┌──────┐ ┌──────┐     ┌──────┐ ┌──────┐  ╳        ┌──────┐ ┌──────┐ ┌─────────┐
│ R1   │ │ R2   │ │ R3   │ →   │ R1   │ │ R2   │  ╳    →   │ R1   │ │ R2   │ │ LOG     │
│ WAL  │ │ WAL  │ │ WAL  │     │ WAL  │ │ WAL  │           │ WAL  │ │ WAL  │ │ REPLICA │
│ Btree│ │ Btree│ │ Btree│     │ Btree│ │ Btree│           │ Btree│ │ Btree│ │ só WAL  │
└──────┘ └──────┘ └──────┘     └──────┘ └──────┘           └──────┘ └──────┘ └─────────┘
  3 cópias                      2 cópias (risco)            quórum restaurado
                                                            ┌─ em paralelo: cura da
                                                               storage replica (minutos)
```

A assimetria de tempo é o insight da subseção:

| Ação | Custo | Por quê |
|---|---|---|
| Curar uma **storage replica** | **vários minutos** | o reparo envolve copiar a **B-tree + os write-ahead logs** |
| Adicionar uma **log replica** | **poucos segundos** | copia **apenas o WAL recente** de uma réplica saudável, **sem a B-tree** |

Portanto: **ao detectar uma storage replica insalubre, o líder do grupo de replicação adiciona uma log replica para garantir que não haja impacto na durabilidade.** A cura rápida dos grupos afetados via log replicas assegura alta durabilidade **das escritas mais recentes** — justamente as que estariam em risco durante os minutos de reparo.

---

## 2. §5.2 — Erros silenciosos (silent data errors)

Algumas falhas de hardware fazem o sistema **armazenar dados incorretos**. Pela experiência relatada, esses erros podem vir da **mídia de armazenamento, da CPU ou da memória**, são **muito difíceis de detectar** e **podem acontecer em qualquer ponto do sistema**.

### 2.1 Checksums como guard-rail

O DynamoDB usa checksums de forma extensiva:

- Mantém checksums **dentro de cada entrada de log, cada mensagem e cada arquivo de log**.
- Com isso, **valida a integridade de todo transporte de dados entre dois nodes**.
- Os checksums funcionam como **guard-rails que impedem o erro de se espalhar** para o resto do sistema.
- Exemplo do paper: um checksum é calculado para **cada mensagem entre nodes ou componentes** e verificado no destino, porque essas mensagens **passam por várias camadas de transformação** no caminho. Sem essa checagem, qualquer uma das camadas poderia introduzir um erro silencioso.

### 2.2 Arquivamento no S3: manifesto + verificações

Cada arquivo de log arquivado no S3 tem um **manifesto** com informação sobre o log: **tabela, partição e marcadores de início e fim** dos dados contidos no arquivo.

O agente responsável por arquivar faz várias checagens **antes** do upload — entre elas:

1. verificar **cada entrada de log** para garantir que pertence à **tabela e partição corretas**;
2. verificar **checksums**, para detectar erros silenciosos;
3. verificar que o arquivo de log **não tem buracos na sequência de números**.

Só depois de passar em todas as checagens o arquivo de log e seu manifesto são arquivados.

### 2.3 Verificação cruzada entre os três agentes

```
   Réplica 1            Réplica 2            Réplica 3
  [log agent]          [log agent]          [log agent]
       │                    │                    │
       │ arquiva ──────────▶│                    │
       ▼                  (vê que já                (vê que já
   ┌────────┐              está arquivado)          está arquivado)
   │   S3   │                   │                        │
   │ log +  │◀── baixa e compara com o WAL local ────────┤
   │manifest│                   │                        │
   └────────┘◀──────────────────┘
   checksum de conteúdo verificado pelo S3 no PUT
```

- **Agentes de arquivamento rodam em todas as três réplicas** do grupo de replicação.
- Se um agente descobre que um arquivo de log **já foi arquivado**, ele **baixa o arquivo enviado e verifica a integridade comparando com seu próprio write-ahead log local**.
- Cada arquivo de log e cada manifesto são enviados ao S3 com um **content checksum**, que **é verificado pelo S3 como parte da operação de put** — isso protege contra erros **em trânsito** até o S3.

---

## 3. §5.3 — Verificação contínua (scrub)

O DynamoDB **verifica continuamente os dados em repouso** (data-at-rest). O objetivo é detectar erros silenciosos ou **bit rot**.

O exemplo dado é o processo de **scrub**, cujo objetivo é **detectar erros que não foram antecipados**, como bit rot. O scrub verifica **duas coisas**:

```
VERIFICAÇÃO 1  (consistência entre réplicas vivas)
   réplica A ── checksum ─┐
   réplica B ── checksum ─┼──▶ as três cópias têm os MESMOS dados?
   réplica C ── checksum ─┘

VERIFICAÇÃO 2  (consistência contra a história completa)
   réplica viva ── checksum ─────────┐
                                     ├──▶ batem?
   réplica reconstruída OFFLINE a    │
   partir do WAL arquivado no S3 ────┘
   (desde a criação da tabela)
```

1. **as três cópias das réplicas de um replication group têm os mesmos dados**;
2. **os dados das réplicas vivas batem com uma cópia de réplica construída offline a partir das entradas de WAL arquivadas** (a mesma construção usada no restore, §5.5).

A verificação é feita **calculando o checksum da réplica viva e comparando com um snapshot gerado a partir das entradas de log arquivadas no S3**.

O mecanismo de scrub age como **defesa em profundidade** para detectar **divergências entre as réplicas vivas e as réplicas construídas a partir do histórico de logs desde a criação da tabela**. Técnica semelhante de verificação contínua é usada para verificar as réplicas de **global tables**.

> **Lição explícita do paper (também listada na §1):** ao longo dos anos aprendeu-se que a **verificação contínua de dados em repouso é o método mais confiável** de proteção contra falhas de hardware, corrupção silenciosa de dados **e até bugs de software**.

---

## 4. §5.4 — Bugs de software

O DynamoDB é construído sobre um substrato complexo, e **alta complexidade aumenta a probabilidade de erro humano** em design, código e operação. Erros podem causar perda ou corrupção de dados, ou violar contratos de interface dos quais os clientes dependem.

Mecanismos:

| Técnica | Como é aplicada |
|---|---|
| **Métodos formais** | usados extensivamente para garantir a corretude dos **protocolos de replicação** |
| **TLA+** | o **protocolo central de replicação foi especificado em TLA+** |
| **Model checking contínuo** | quando novas features afetam o protocolo de replicação, elas são **incorporadas à especificação e submetidas a model checking** |
| **Failure injection + stress testing** | testes extensivos para garantir a corretude de **cada peça de software implantada** |

Resultados e extensões:

- O model checking **permitiu capturar bugs subtis que poderiam ter causado problemas de durabilidade e corretude antes do código ir para produção**.
- Outros serviços, como o **S3**, também acharam model checking útil em cenários semelhantes.
- Além do protocolo de replicação do data plane, métodos formais também foram usados para verificar a corretude do **control plane** e de features como **transações distribuídas**.

> **Conexão com §6.1:** a implementação de Paxos formalmente provada foi o que deu confiança para introduzir as **log replicas** — uma mudança grande no sistema — e "mexer" no protocolo em busca de mais disponibilidade sem medo de quebrar corretude.

---

## 5. §5.5 — Backups e restores

Além de proteger contra corrupção de mídia física, o DynamoDB suporta **backup e restore para proteger contra corrupção lógica causada por um bug na aplicação do cliente**.

### 5.1 Backups on-demand

- **Não afetam performance nem disponibilidade da tabela**, porque são **construídos a partir dos write-ahead logs arquivados no S3** (não leem a tabela em produção).
- São **consistentes entre múltiplas partições até o segundo mais próximo**.
- São **cópias completas** das tabelas, armazenadas em um bucket do **Amazon S3**.
- Os dados de um backup podem ser **restaurados para uma nova tabela DynamoDB a qualquer momento**.

### 5.2 Point-in-time restore (PITR)

Permite restaurar o conteúdo que a tabela tinha em **qualquer instante dos 35 dias anteriores**, para uma **tabela diferente, na mesma região**.

Como funciona:

```
 tabela com PITR habilitado
 ──────────────────────────────────────────────────────────────▶ tempo
   ▲snapshot      ▲snapshot                 ▲snapshot
   │              │                         │
   └── WAL ───────┴──── WAL ────────────────┴──── WAL ─────────
                                       ▲
                                       │ instante T pedido no restore
 RESTORE =  snapshot mais próximo ANTES de T
          + aplicar os WAL até o timestamp T
          + gerar snapshot da tabela e restaurar
```

- Para tabelas com PITR habilitado, o DynamoDB **cria snapshots periódicos das partições** da tabela e os **envia para o S3**.
- A **periodicidade com que uma partição é snapshotada é decidida com base na quantidade de WAL acumulada** para aquela partição (não é um intervalo fixo de tempo).
- Os **snapshots, em conjunto com os write-ahead logs**, são o que viabiliza o PITR.
- Quando um PITR é solicitado, o DynamoDB: **(1)** identifica os snapshots mais próximos do instante pedido **para todas as partições** da tabela; **(2)** **aplica os logs até o timestamp** do pedido de restore; **(3)** cria um snapshot da tabela; **(4)** restaura.

> **Observação importante para o trabalho:** restore **sempre cria uma tabela nova** — não há "undo" in-place. Isso tem consequência prática no roteiro de simulação: a verificação de recuperação é feita comparando a tabela restaurada com o estado esperado, não observando a tabela original voltar.

---

## 6. Perguntas de verificação (§5)

1. Por que o backup não degrada a performance da tabela? → porque é construído a partir do **WAL já arquivado no S3**, não lendo as réplicas em produção.
2. Qual é a diferença de propósito entre *scrub* e *checksum de mensagem*? → o checksum detecta corrupção **em trânsito/no momento do uso** e impede propagação; o scrub detecta corrupção **em repouso**, acumulada e silenciosa, inclusive divergência contra a história completa dos logs.
3. Por que o PITR depende de snapshots E de logs, e não só de logs? → reaplicar o log desde a criação da tabela a cada restore seria inviável; o snapshot é o ponto de partida e o log cobre apenas o delta até T.
4. Qual mecanismo da §5 **não** protege contra um `DeleteItem` indevido feito pela aplicação? → nenhum dos de §5.1–§5.4: a escrita foi *commitada* corretamente. Só backup/PITR (§5.5) cobre esse caso.
5. O que a log replica garante exatamente, em termos de durabilidade? → mantém o **quórum de persistência de WAL** durante a janela de reparo, protegendo as **escritas mais recentes** — as que ainda não foram arquivadas no S3.
6. Por que a periodicidade de snapshot é baseada em volume de WAL e não em tempo? → o custo do restore é proporcional à quantidade de log a reaplicar; partições com muita escrita acumulam log rápido e precisam de snapshots mais frequentes.
