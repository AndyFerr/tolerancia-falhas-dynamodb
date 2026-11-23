"""Cenário B — throttling em produto quente (docs/CENARIOS.md; contrato, seção 2).

100 vendas no mesmo produto (`prod-007`) da tabela `EstoqueThrottle`, que tem
1 WCU fixo. Duas fases:

  fase_sem_retry    cada venda tem uma única tentativa (retry do SDK desligado)
  fase_com_backoff  a mesma carga, com backoff exponencial e jitter feito aqui

Antes da fase 1, o script consome a capacidade de burst da tabela. O DynamoDB
guarda até alguns minutos de capacidade não usada; sem esse aquecimento, as
primeiras dezenas de vendas passariam sem throttling e a fase 1 mediria o
burst, não o limite de 1 WCU. O aquecimento é registrado em `metricas`.

Uso: python scenarios/cenario_b.py      (rode scripts/03_reset.py antes)
"""
import random
import sys
import time

try:
    from . import _caminho  # noqa: F401
except ImportError:
    import _caminho  # noqa: F401

from lab import aws, config
from lab.execucao import ErroCenario, rodar_cli
from lab.tempo import iso

PRODUTO = 7                     # tem de bater com PRODUTO_THROTTLE do seed (prod-007)
N_VENDAS = 100
WCU = 1

# Backoff exponencial com jitter completo (fase 2)
BACKOFF_BASE_S = 0.05
BACKOFF_TETO_S = 2.0
MAX_TENTATIVAS = 15

# Aquecimento: para quando houver N throttles seguidos, ou no limite de tempo
AQUECIMENTO_THROTTLES_SEGUIDOS = 10
AQUECIMENTO_MAX_S = 90

ERROS_THROTTLE = {"ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded"}

PARAMETROS = {
    "tabela": None,                     # preenchido com cfg.tabela_throttle
    "produto_id": config.id_produto(PRODUTO),
    "write_capacity_units": WCU,
    "n_vendas": N_VENDAS,
}


def _vender(cliente, tabela: str, produto_id: str) -> None:
    """Uma venda: decrementa 1 unidade. Lança a exceção da AWS se falhar."""
    cliente.update_item(
        TableName=tabela,
        Key={"produto_id": {"S": produto_id}},
        UpdateExpression="SET quantidade = quantidade - :um, versao = versao + :um, "
                         "atualizado_em = :t, escritor = :e",
        ConditionExpression="attribute_exists(produto_id)",
        ExpressionAttributeValues={
            ":um": {"N": "1"}, ":t": {"S": iso()}, ":e": {"S": "cenario_b"},
        },
    )


def _eh_throttle(e: Exception) -> bool:
    return aws.codigo_erro(e) in ERROS_THROTTLE


def _repor(cfg) -> None:
    """Volta o produto para 100 unidades.

    Logo depois de uma fase a tabela está sem capacidade, então esta escrita
    também pode sofrer throttling: insiste com backoff por até ~1 minuto.
    """
    t = aws.tabela(cfg.primaria, cfg.tabela_throttle)
    for tentativa in range(1, 31):
        try:
            t.put_item(Item=aws.item_estoque(PRODUTO, cfg.primaria, "reset"))
            return
        except Exception as e:  # noqa: BLE001
            if not _eh_throttle(e) or tentativa == 30:
                raise
            time.sleep(min(2.0, 0.1 * 2 ** (tentativa - 1)))


def _conferir_estado_inicial(cfg) -> None:
    item = aws.tabela(cfg.primaria, cfg.tabela_throttle).get_item(
        Key={"produto_id": config.id_produto(PRODUTO)}, ConsistentRead=True
    ).get("Item")
    if item is None:
        raise ErroCenario("ESTOQUE_NAO_RESETADO",
                          f"{config.id_produto(PRODUTO)} não existe em {cfg.tabela_throttle}. "
                          "Rode scripts/03_reset.py.")
    if int(item["quantidade"]) != config.UNIDADES_POR_PRODUTO:
        raise ErroCenario("ESTOQUE_NAO_RESETADO",
                          f"{config.id_produto(PRODUTO)} tem {item['quantidade']} unidades, "
                          f"esperado {config.UNIDADES_POR_PRODUTO}. Rode scripts/03_reset.py.")


def _aquecer(cliente, tabela: str, produto_id: str) -> dict:
    """Consome o burst até o throttling ficar contínuo."""
    escritas = aceitas = seguidos = 0
    t0 = time.monotonic()
    while seguidos < AQUECIMENTO_THROTTLES_SEGUIDOS and time.monotonic() - t0 < AQUECIMENTO_MAX_S:
        escritas += 1
        try:
            _vender(cliente, tabela, produto_id)
            aceitas += 1
            seguidos = 0
        except Exception as e:  # noqa: BLE001
            if not _eh_throttle(e):
                raise
            seguidos += 1
    return {
        "escritas": escritas,
        "aceitas_pelo_burst": aceitas,
        "duracao_ms": round((time.monotonic() - t0) * 1000),
        "throttling_continuo": seguidos >= AQUECIMENTO_THROTTLES_SEGUIDOS,
    }


def _fase_sem_retry(ex, cliente, tabela: str, produto_id: str) -> tuple[dict, list]:
    concluidas = throttled = 0
    janelas: dict[int, dict] = {}
    t0 = time.monotonic()
    for _ in range(N_VENDAS):
        janela = int(time.monotonic() - t0) + 1
        j = janelas.setdefault(janela, {"janela_s": janela, "tentativas": 0, "throttled": 0})
        j["tentativas"] += 1
        try:
            _vender(cliente, tabela, produto_id)
            concluidas += 1
        except Exception as e:  # noqa: BLE001
            if not _eh_throttle(e):
                raise
            throttled += 1
            j["throttled"] += 1
        ex.avancar()
    fase = {
        "vendas_concluidas": concluidas,
        "vendas_perdidas": N_VENDAS - concluidas,
        "throttled": throttled,
        "tentativas_totais": N_VENDAS,
        "duracao_ms": round((time.monotonic() - t0) * 1000),
    }
    return fase, [janelas[k] for k in sorted(janelas)]


def _fase_com_backoff(ex, cliente, tabela: str, produto_id: str) -> dict:
    concluidas = throttled = tentativas_totais = 0
    t0 = time.monotonic()
    for _ in range(N_VENDAS):
        for tentativa in range(1, MAX_TENTATIVAS + 1):
            tentativas_totais += 1
            try:
                _vender(cliente, tabela, produto_id)
                concluidas += 1
                break
            except Exception as e:  # noqa: BLE001
                if not _eh_throttle(e):
                    raise
                if tentativa == MAX_TENTATIVAS:
                    throttled += 1          # venda perdida: esgotou as tentativas em throttle
                    break
                time.sleep(random.uniform(0, min(BACKOFF_TETO_S, BACKOFF_BASE_S * 2 ** (tentativa - 1))))
        ex.avancar()
    return {
        "vendas_concluidas": concluidas,
        "vendas_perdidas": N_VENDAS - concluidas,
        "throttled": throttled,
        "tentativas_totais": tentativas_totais,
        "duracao_ms": round((time.monotonic() - t0) * 1000),
    }


def executar(ex, cfg, parciais: dict) -> dict:
    tabela = cfg.tabela_throttle
    produto_id = config.id_produto(PRODUTO)
    # Retry do SDK desligado: quem decide se tenta de novo é o cenário.
    cliente = aws.cliente(cfg.primaria, tentativas=1)

    _conferir_estado_inicial(cfg)

    print("  aquecimento: consumindo a capacidade de burst ...", flush=True)
    parciais["aquecimento"] = _aquecer(cliente, tabela, produto_id)
    print(f"  aquecimento: {parciais['aquecimento']}", flush=True)
    _repor(cfg)

    ex.etapa("fase_sem_retry", total=N_VENDAS)
    parciais["fase_sem_retry"], parciais["throttle_por_janela"] = _fase_sem_retry(ex, cliente, tabela, produto_id)
    print(f"  fase_sem_retry: {parciais['fase_sem_retry']}", flush=True)
    _repor(cfg)

    ex.etapa("fase_com_backoff", total=N_VENDAS)
    parciais["fase_com_backoff"] = _fase_com_backoff(ex, cliente, tabela, produto_id)
    print(f"  fase_com_backoff: {parciais['fase_com_backoff']}", flush=True)
    _repor(cfg)

    return {
        "fase_sem_retry": parciais["fase_sem_retry"],
        "fase_com_backoff": parciais["fase_com_backoff"],
        "throttle_por_janela": parciais["throttle_por_janela"],
        "aquecimento": parciais["aquecimento"],
    }


def parametros(cfg) -> dict:
    return {**PARAMETROS, "tabela": cfg.tabela_throttle}


if __name__ == "__main__":
    _cfg = config.carregar()
    sys.exit(rodar_cli("B", parametros(_cfg), executar))
