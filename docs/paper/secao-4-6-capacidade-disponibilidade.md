# §4 e §6 — Capacidade e disponibilidade (estudo dirigido)

> Fonte: Elhemali et al., *Amazon DynamoDB*, USENIX ATC 2022, §4 (pp. 1040–1043) e §6 (pp. 1045–1047).
> Entregável da linha **A5**. Paráfrase do original; `§x.y` aponta para a subseção.
> Complementa `secao-3-arquitetura.md` e `secao-5-durabilidade.md`, que cobrem §3 e §5.

---

# Parte I — §4: da capacidade provisionada à sob demanda

## 1. O ponto de partida e o erro de projeto

No lançamento, o cliente declarava o throughput da tabela em **RCUs** e **WCUs**:

- 1 RCU = uma leitura fortemente consistente por segundo, para itens de até 4 KB;
- 1 WCU = uma escrita por segundo, para itens de até 1 KB.

A tabela era dividida em partições, e o throughput da tabela era **dividido igualmente entre elas**. O exemplo do paper: uma tabela criada com 3.200 WCUs vira quatro partições de 800 WCUs cada. Subindo para 6.000 WCUs, as partições se dividem em oito, com 750 WCUs cada.

O **admission control** era responsabilidade de cada storage node, de forma independente, com base nas partições que ele hospedava. Cada partição tinha um teto, e a soma dos tetos das partições de um node não podia passar o que os discos daquele node aguentam.

Esse desenho assume duas coisas: que a aplicação **acessa as chaves de forma uniforme**, e que dividir uma partição por tamanho **divide a performance proporcionalmente**. Nenhuma das duas se sustenta na prática.

## 2. Os dois problemas que apareceram

**Partição quente.** Aplicações com tráfego concentrado em poucos itens. Os itens quentes podiam estar num conjunto estável de partições ou migrar entre partições ao longo do tempo.

**Diluição de throughput.** Quando uma partição é dividida **por tamanho**, o throughput é dividido igualmente entre as filhas — então o throughput por partição cai. Se a parte quente ficou numa das filhas, ela passa a ter *menos* performance disponível do que tinha antes da divisão.

Nos dois casos o resultado é **throttling**: leituras e escritas rejeitadas, mesmo com o throughput total da tabela sendo suficiente. Do ponto de vista do cliente, a aplicação fica indisponível por períodos — e o serviço está se comportando exatamente como projetado.

A reação dos clientes era **superprovisionar**: aumentar o throughput da tabela e não usar a capacidade toda. Funcionava, mas era uma experiência ruim, porque estimar o nível certo de provisionamento é difícil.

## 3. As duas primeiras correções

### 3.1 Bursting (§4.1.1)

A observação: nem todas as partições de um storage node usam sua capacidade alocada **ao mesmo tempo**.

O DynamoDB passou a reter parte da capacidade não usada de uma partição por **até 300 segundos** e a liberá-la quando o consumo passa do provisionado. Essa capacidade retida é a *burst capacity*.

O isolamento é mantido por **token buckets**: dois por partição (alocado e burst) e um por node.

```
chega uma requisição
      │
      ├─ há token no bucket ALOCADO da partição?
      │     sim → admite, desconta do bucket da partição e do bucket do NODE
      │
      └─ não → só admite se houver token no bucket BURST e no bucket do NODE
```

Leituras são aceitas com base nos buckets locais. **Escritas usando burst exigem uma checagem a mais**: o bucket de nível de node das *outras réplicas* da partição. O líder da partição coleta periodicamente a informação de capacidade de node de cada membro.

### 3.2 Adaptive capacity (§4.1.2)

Burst resolve pico curto. Para picos **longos**, veio a capacidade adaptativa.

Ela monitorava continuamente a capacidade provisionada e consumida de todas as tabelas. Se uma tabela sofria throttling **sem ter estourado o throughput no nível da tabela**, o sistema aumentava automaticamente a capacidade alocada das partições daquela tabela, por um algoritmo de controle proporcional. Se a tabela passava a consumir mais que o provisionado, as partições que receberam o aumento tinham a capacidade reduzida de volta.

O autoadmin garantia que partições com capacidade aumentada fossem realocadas para um node capaz de servir o throughput maior.

Como o bursting, era **best-effort** — mas eliminou **mais de 99,99%** do throttling causado por padrão de acesso enviesado.

## 4. Global admission control (§4.2)

As duas soluções tinham limites: bursting só serve para picos curtos e depende de o node ter folga; a capacidade adaptativa era **reativa**, entrava em ação **depois** que o throttling já havia sido observado — ou seja, a aplicação já tinha passado por um período de indisponibilidade.

A conclusão foi que o erro estava em acoplar capacidade de partição ao admission control. A solução: **tirar o controle de admissão da partição**, deixar a partição sempre fazer burst, e manter o isolamento por outro caminho.

O **GAC** usa a mesma ideia de token buckets, mas centralizada:

- o serviço rastreia centralmente o consumo total da capacidade da tabela em tokens;
- cada request router mantém um bucket local e conversa com o GAC para repor tokens em intervalos da ordem de poucos segundos;
- o GAC mantém estado **efêmero**, calculado a partir das requisições dos clientes — qualquer servidor GAC pode ser parado e reiniciado sem impacto;
- os servidores GAC formam um **hash ring** independente; cada um rastreia um ou mais buckets configurados de forma independente.

Quando o router fica sem tokens — por consumo ou por expiração — pede mais ao GAC, que estima o consumo global e entrega a fatia do cliente para a próxima unidade de tempo.

Os token buckets de partição **foram mantidos como defesa em profundidade**, com a capacidade limitada para que uma aplicação não consuma tudo ou uma fatia significativa dos recursos de um storage node.

## 5. Equilibrar a capacidade consumida (§4.3)

Deixar as partições sempre fazerem burst exigiu gerenciar bem a capacidade. A geração mais recente de storage nodes hospeda **milhares de réplicas de partição**, possivelmente de tabelas e clientes completamente diferentes.

Com provisionamento estático a colocação era simples: bastava achar um node que coubesse a capacidade alocada da partição, e nenhuma partição podia passar do seu teto — não havia vizinho barulhento. Com bursting, o node pode passar da capacidade prescrita, e o sistema passa a **empacotar os nodes com mais réplicas do que a capacidade provisionada do node**.

Para mitigar o risco de disponibilidade disso, cada storage node monitora de forma independente o throughput e o tamanho de todas as réplicas que hospeda. Se o throughput passa de um percentual limite da capacidade máxima do node, ele **reporta ao autoadmin uma lista de réplicas candidatas a sair**. O autoadmin encontra um novo node — na mesma AZ ou em outra — que **não tenha outra réplica daquela partição**.

## 6. Dividir por consumo (§4.4)

Mesmo com GAC e burst permanente, uma tabela ainda sofre throttling se o tráfego se concentra num conjunto específico de itens. Para isso, o DynamoDB divide a partição automaticamente **com base no throughput consumido**.

O ponto de corte é escolhido pela **distribuição de chaves observada**, não pelo meio da faixa — a distribuição observada funciona como proxy do padrão de acesso da aplicação, e é mais eficaz que cortar ao meio. A divisão costuma levar **alguns minutos**.

E então a passagem mais importante da seção para o trabalho de vocês:

> **Existem workloads que a divisão não resolve.** Uma partição que recebe tráfego alto para **um único item**, ou cuja faixa de chaves é acessada **sequencialmente**, não se beneficia do split. O DynamoDB detecta esses padrões e evita dividir a partição.

## 7. Tabelas sob demanda (§4.5)

Muitas aplicações migradas vinham de ambientes onde o desenvolvedor provisionava servidores. O conceito de unidades de capacidade era novo, e prever o throughput se mostrou difícil — resultando em superprovisionamento (baixa utilização) ou subprovisionamento (throttling).

As tabelas **on-demand** provisionam com base na capacidade consumida, coletando o sinal de leituras e escritas, e acomodam instantaneamente **até o dobro do pico anterior** da tabela. Acima disso, o DynamoDB aloca mais capacidade conforme o volume cresce. O mecanismo de escala é o mesmo **split por consumo**, com decisão baseada em tráfego, e o GAC protege o sistema de uma aplicação consumir todos os recursos.

---

# Parte II — §6: disponibilidade

## 8. Testes de resiliência

As tabelas são distribuídas e replicadas em múltiplas **Availability Zones** de uma Região, e a resiliência a falha de node, rack e AZ é testada regularmente.

Os **power-off tests** usam tráfego simulado realista e um agendador que **desliga nodes aleatórios**. Ao fim, as ferramentas de teste verificam que os dados armazenados estão **logicamente válidos e não corrompidos**.

## 9. Disponibilidade de escrita e de leitura consistente (§6.1)

A disponibilidade de escrita de uma partição depende de ter **um líder saudável e um quórum de escrita saudável**.

> **No DynamoDB, um quórum de escrita saudável são duas das três réplicas, em AZs diferentes.**

A partição continua disponível enquanto houver réplicas suficientes para o quórum e um líder. Fica **indisponível para escrita** se o número de réplicas necessárias ao quórum mínimo não estiver disponível.

Se uma réplica não responde, **o líder adiciona uma log replica ao grupo** — é a forma mais rápida de garantir que o quórum de escrita esteja sempre satisfeito, e minimiza a interrupção da disponibilidade de escrita.

O paper credita a introdução das log replicas à confiança dada pela implementação de Paxos **formalmente provada**: foi ela que permitiu mexer e experimentar no sistema em busca de mais disponibilidade. Em produção, são **milhões de grupos Paxos por Região** com log replicas.

Leituras eventualmente consistentes são servidas por qualquer réplica. Se o líder falha, as outras detectam e elegem um novo, minimizando a interrupção da leitura consistente.

## 10. Detecção de falha (§6.2)

O novo líder eleito **espera o lease do líder antigo expirar** antes de servir tráfego. São alguns segundos, mas nesse período ele não aceita escrita nem leitura consistente — é indisponibilidade.

Por isso a detecção de falha precisa ser **rápida e robusta**, e **falsos positivos causam mais interrupção**.

A detecção funciona bem quando todas as réplicas perdem contato com o líder. O problema são as **falhas cinzentas** (*gray failures*): problemas de comunicação entre líder e seguidor, problemas só de entrada ou só de saída de um node, ou routers que não conseguem falar com o líder **mesmo com líder e seguidores se comunicando normalmente**.

Uma réplica que para de receber heartbeats tenta eleger um novo líder — e dispara a janela de indisponibilidade sem necessidade.

**A solução:** antes de disparar o failover, o seguidor **pergunta às outras réplicas do grupo se elas conseguem falar com o líder**. Se responderem que o líder está saudável, ele desiste da tentativa. Essa mudança reduziu significativamente os falsos positivos e, com eles, as eleições espúrias.

## 11. Medir disponibilidade (§6.3)

Metas de projeto: **99,999%** para global tables e **99,99%** para tabelas regionais.

A disponibilidade é calculada **a cada intervalo de 5 minutos**, como o percentual de requisições processadas com sucesso. O monitoramento é contínuo, no nível de serviço e de tabela, e dispara **customer-facing alarms (CFA)** quando o cliente vê erros acima de um limite — para mitigar proativamente, de forma automática ou por intervenção de operador.

Além do tempo real, jobs diários agregam métricas por cliente e sobem o resultado para o S3, para análise de tendência.

A disponibilidade também é medida **do lado do cliente**, por dois conjuntos:

1. **serviços internos da Amazon** que usam DynamoDB como armazenamento e compartilham as métricas observadas pelo próprio software deles;
2. **aplicações canário**, executadas a partir de todas as AZs da Região, conversando com o DynamoDB por todos os endpoints públicos.

O tráfego real de aplicação é o que permite enxergar latência e disponibilidade como o cliente enxerga, e **capturar falhas cinzentas**.

## 12. Implantações (§6.4)

Não há janela de manutenção. Atualizações entram em cadência regular, sem impacto em performance e disponibilidade.

A lição acumulada: **não importam só o estado inicial e o final**. Às vezes o software novo não funciona e precisa de rollback — e **o estado após o rollback pode ser diferente do estado inicial**. O procedimento de rollback costuma escapar dos testes e gerar impacto no cliente. Por isso o DynamoDB roda testes de upgrade e downgrade por componente antes de cada implantação, e **faz rollback de propósito**, rodando testes funcionais depois.

Em sistema distribuído a implantação **não é atômica**: durante um tempo há nodes com código antigo e nodes com código novo. Se o software novo introduz um tipo de mensagem ou muda o protocolo, o antigo não entende.

A solução são as **read-write deployments**, em várias etapas:

1. implanta o software capaz de **ler** o novo formato ou protocolo;
2. quando todos os nodes já sabem ler, atualiza o software para **enviar** as novas mensagens.

Assim os dois tipos de mensagem coexistem — e, mesmo em rollback, o sistema entende as duas.

Toda implantação começa por **um conjunto pequeno de nodes** antes de ir para a frota inteira. Se taxa de erro ou latência passam dos limites de alarme durante a implantação, o sistema dispara **rollback automático**.

Detalhe elegante: implantação em storage node **dispara failover de liderança projetado para não impactar a disponibilidade** — o líder **abre mão** da liderança, e por isso o novo líder **não precisa esperar o lease antigo expirar**.

## 13. Dependências externas (§6.5)

Todo serviço do qual o DynamoDB depende no caminho da requisição deveria ser mais disponível que ele — ou o DynamoDB precisa continuar operando mesmo com a dependência degradada. Exemplos no caminho da requisição: **IAM** e **AWS KMS** (para tabelas com chave do cliente), usados para autenticar cada requisição.

A resposta é o **design estaticamente estável**: o sistema continua funcionando mesmo com a dependência degradada. Talvez ele não receba informação atualizada que a dependência deveria ter entregue — mas **tudo que já funcionava antes da degradação continua funcionando**.

Na prática: os request routers **cacheiam** os resultados de IAM e KMS e os atualizam periodicamente, de forma assíncrona. Se IAM ou KMS ficam indisponíveis, os routers **seguem usando o resultado em cache por um período estendido pré-determinado**. Clientes que caem em routers sem o resultado em cache sentem impacto — mas, na prática, o impacto observado é mínimo.

O cache ainda melhora o tempo de resposta por eliminar uma chamada externa, o que vale especialmente sob carga alta.

## 14. Disponibilidade de metadados (§6.6)

O metadado mais importante para o request router é o **mapeamento entre as chaves primárias de uma tabela e os storage nodes**.

No lançamento, esse metadado ficava **no próprio DynamoDB**. Quando um router recebia requisição para uma tabela que ainda não conhecia, ele **baixava a informação de roteamento da tabela inteira** e guardava em cache local. Como a configuração das réplicas muda raramente, a taxa de acerto do cache ficava em torno de **99,75%**.

O problema é que **cache introduz comportamento bimodal**. Em partida a frio — routers com cache vazio — toda requisição vira uma consulta de metadados, e o serviço de metadados teria que escalar na mesma taxa do DynamoDB inteiro. Isso foi observado na prática: ao adicionar capacidade à frota de routers, o tráfego para o serviço de metadados chegava a subir **75%**. Pior: um cache ineficaz pode causar **falhas em cascata**, com a fonte dos dados caindo por excesso de carga direta.

Duas correções:

**MemDS.** Um armazenamento distribuído **em memória**, que guarda todos os metadados e os replica por toda a frota. Escala horizontalmente para suportar a taxa de requisições inteira do DynamoDB, com os dados **altamente comprimidos**. Cada processo encapsula uma estrutura chamada **Perkle** — híbrido de árvore **Patricia** e árvore **Merkle** — que permite inserir chaves e valores para consulta posterior pela chave inteira ou por prefixo. Como as chaves ficam ordenadas, suporta consultas de intervalo (`lessThan`, `greaterThan`, `between`) e duas operações especiais: **`floor`** (maior entrada com chave ≤ a chave dada) e **`ceiling`** (menor entrada com chave ≥ a chave dada).

Repare também que o router **só precisa da informação da partição que hospeda aquela chave** — baixar o roteamento da tabela inteira era desperdício, especialmente em tabelas grandes.

**Cache que não é bimodal.** O novo partition map cache, em cada host de router, faz algo contraintuitivo: **um acerto de cache também dispara uma chamada assíncrona ao MemDS para atualizar a entrada**. Assim a frota MemDS recebe **volume constante de tráfego, independentemente da taxa de acerto do cache**.

Isso aumenta a carga sobre a frota de metadados em comparação com um cache convencional — onde o tráfego ao backend é determinado pela taxa de acerto — mas **previne a falha em cascata** quando os caches ficam ineficazes. É o exemplo mais claro da lição da §1: *não deixe o cache esconder o trabalho que seria feito na ausência dele*.

Por fim: os **storage nodes são a fonte autoritativa** da participação em partição. As atualizações são empurradas dos storage nodes para o MemDS, e cada atualização é propagada para todos os nodes MemDS. Se o MemDS devolver informação obsoleta, o storage node contatado por engano **responde com a informação mais recente, se a conhecer**, ou com um código de erro que **dispara nova consulta ao MemDS** pelo request router.

---

# Parte III — Mapa conceito → métrica observável

A contraparte do mapa de §3/§5. Lá a pergunta era "que falha este mecanismo cobre?". Aqui é: **o que um cliente comum consegue medir deste mecanismo?**

## O que é observável

| Conceito (§) | O que o cliente mede | Como | Cenário do lab |
|---|---|---|---|
| **Throttling / admission control** (§4) | taxa de `ProvisionedThroughputExceededException` sobre o total de tentativas | carga acima da capacidade, contando sucesso e recusa | **Cenário B** |
| **Backoff do cliente** (§4, implícito) | taxa de sucesso e latência total, com e sem backoff exponencial | duas fases com a mesma carga, variando só o cliente | **Cenário B** |
| **Item único quente** (§4.4) | throttling que **não melhora com o tempo** | carga concentrada em um `produto_id` — o split não se aplica | **Cenário B** |
| **Split por consumo** (§4.4) | throttling que **melhora sozinho** após alguns minutos | carga sustentada distribuída por várias chaves | não previsto |
| **Bursting** (§4.1.1) | pico curto absorvido acima do provisionado | rajada de poucos segundos depois de período ocioso | não previsto |
| **On-demand: até o dobro do pico** (§4.5) | degrau de carga até 2× o pico anterior sem throttle | subir carga em degrau | não previsto |
| **Quórum de escrita 2-de-3** (§6.1) | escrita continua aceita com uma réplica fora | remover réplica e escrever | **Cenário A** |
| **Leitura eventual em qualquer réplica** (§6.1) | leitura eventual segue respondendo durante o failover | ler nos dois modos durante o cenário | **Cenário A** |
| **Janela do lease** (§6.2) | curta janela de erro em escrita e leitura forte | medir p99 e erros sob carga contínua | parcial no A |
| **Disponibilidade medida em 5 min** (§6.3) | o próprio número de disponibilidade | agregar sucesso/total por janela de 5 minutos | **todos** |

## O que não é observável do lado do cliente

Vale tanto quanto a lista acima, e pelo mesmo motivo do mapa de §3/§5: delimita honestamente o alcance do experimento.

| Conceito (§) | Por que não dá para medir |
|---|---|
| **Adaptive capacity e GAC** (§4.1.2, §4.2) | atuam antes de o cliente ver qualquer coisa; o sucesso deles é a **ausência** de sintoma |
| **Token buckets por partição e por node** (§4.1.1) | estrutura interna do storage node |
| **Rebalanceamento de réplicas** (§4.3) | decisão do autoadmin, sem sinal externo |
| **Detecção de falha cinzenta** (§6.2) | o efeito é a eleição espúria que **não** aconteceu |
| **Read-write deployments e rollback automático** (§6.4) | projetados precisamente para serem invisíveis |
| **Estabilidade estática com IAM e KMS** (§6.5) | só apareceria durante uma degradação real desses serviços |
| **MemDS, Perkle e o partition map cache** (§6.6) | infraestrutura de metadados; no máximo, uma diferença de latência na primeira requisição a uma tabela nunca acessada |

**A conclusão metodológica é a mesma do mapa de §3/§5:** a maior parte dos mecanismos de §4 e §6 é bem-sucedida exatamente quando não deixa rastro. O que o laboratório mede são os **casos de borda que o paper admite não resolver** — o item único quente da §4.4 e a janela de lease da §6.2 — mais o comportamento do cliente, que o paper trata como parte do sistema.

---

## Perguntas de verificação

1. Por que dividir uma partição por tamanho pode **piorar** a performance da parte quente? → o throughput é dividido igualmente entre as filhas, então a filha que ficou com os itens quentes tem menos capacidade do que a partição tinha antes.
2. Qual a diferença essencial entre adaptive capacity e GAC? → a primeira é **reativa** (age depois do throttling observado) e por partição; o GAC é central, por tabela, e rastreia consumo antes de a partição recusar.
3. Por que o novo cache de metadados consulta o MemDS mesmo em caso de acerto? → para manter tráfego constante ao backend e evitar o comportamento bimodal que derruba a fonte quando os caches esfriam.
4. Que dois padrões de acesso o split não resolve? → tráfego concentrado em um único item e faixa de chaves acessada sequencialmente.
5. Por que uma implantação em storage node não causa a janela de lease? → o líder entrega a liderança voluntariamente, então o novo líder não precisa esperar o lease antigo expirar.
6. O que significa "estaticamente estável" no caso de IAM e KMS? → tudo que funcionava antes da degradação continua funcionando com os dados em cache; só se perde a informação **nova** que a dependência entregaria.
