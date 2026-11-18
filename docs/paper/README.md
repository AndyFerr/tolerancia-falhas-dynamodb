# Estudo dirigido — paper DynamoDB (USENIX ATC 2022)

Material de estudo das seções §3 (Arquitetura) e §5 (Durabilidade e corretude) do paper base do trabalho *Tolerância a Falhas com Amazon DynamoDB*.

| Arquivo | Conteúdo |
|---|---|
| [`secao-3-arquitetura.md`](secao-3-arquitetura.md) | modelo de dados, API, particionamento, replication group, Multi-Paxos e lease, caminho de escrita, storage replica × log replica, microsserviços (metadata, request router, storage, autoadmin) |
| [`secao-5-durabilidade.md`](secao-5-durabilidade.md) | WAL e arquivamento no S3, log replica na cura de réplica, checksums, manifesto e verificação cruzada, scrub, TLA+/model checking, backup e point-in-time restore |
| [`secao-4-6-capacidade-disponibilidade.md`](secao-4-6-capacidade-disponibilidade.md) | §4 admission control, bursting, adaptive capacity, GAC, split por consumo, on-demand; §6 quórum 2-de-3, lease, falha cinzenta, deployments, estabilidade estática, MemDS |
| [`mapa-conceito-cenario-falha.md`](mapa-conceito-cenario-falha.md) | **mapa conceito → cenário de falha**: mecanismo→falha coberta (A), falha→cadeia de reação (B), limites de §3/§5 (C), ponte para a simulação do trabalho (D) |

## Como usar

- **Para estudar o paper:** §3 → §5 → mapa. Cada resumo termina com perguntas de verificação com resposta curta.
- **Para escrever a fundamentação teórica:** §3 e §5 já estão em paráfrase com referência de subseção; as partes A e C do mapa dão a estrutura de "mecanismo / falha / limite".
- **Para desenhar a simulação de falhas:** parte B (o que acontece em cada falha) + parte D (o que é de fato observável do lado do cliente).

## Convenção

Todo o conteúdo é paráfrase do original, com referências no formato `§3`, `§5.1`. Onde um mecanismo de §3/§5 só fecha o raciocínio com informação de §6 (quórum 2-de-3, detecção de falha cinzenta, deploy com entrega de liderança), isso está marcado explicitamente. A parte D do mapa é a única que **não** vem do paper.

**Referência:** Elhemali et al., *Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL Database Service*, 2022 USENIX ATC, pp. 1037–1048.
