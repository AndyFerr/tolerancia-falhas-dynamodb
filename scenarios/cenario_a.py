"""Cenário A — escrita parcial vs. transação (docs/CENARIOS.md; contrato, seção 2).

Transferência de 10 unidades de prod-001 para prod-050. O destino tem um
limite de prateleira (ConditionExpression quantidade <= limite) e é preparado
ACIMA desse limite, então a escrita no destino sempre falha. O que se mede é
se o total de unidades do estoque se conserva.

  modo_sem_transacao  dois UpdateItem separados: a origem é debitada e o destino falha
  modo_com_transacao  as mesmas duas operações num único TransactWriteItems

A ConditionalCheckFailedException (e a TransactionCanceledException) são o
evento provocado de propósito: são contadas, nunca tratadas como falha da AWS.

Uso: python scenarios/cenario_a.py      (rode scripts/03_reset.py antes)
"""
import sys

try:
    from . import _caminho  # noqa: F401
except ImportError:
    import _caminho  # noqa: F401

from lab import aws, config
from lab.execucao import ErroCenario, rodar_cli
from lab.tempo import iso

ORIGEM, DESTINO = 1, 50
UNIDADES = 10
LIMITE_PRATELEIRA = 100
EXCESSO_DESTINO = 5          # o destino começa com 105 > 100: a condição sempre falha
RODADAS = 5

ERROS_PROVOCADOS = {"ConditionalCheckFailedException", "TransactionCanceledException"}


def _update(tabela: str, produto_id: str, delta: int, com_limite: bool) -> dict:
    """Parâmetros de um UpdateItem/Update que soma `delta` à quantidade."""
    op = {
        "TableName": tabela,
        "Key": {"produto_id": {"S": produto_id}},
        "UpdateExpression": "SET quantidade = quantidade + :d, versao = versao + :um, "
                            "atualizado_em = :t, escritor = :e",
        "ExpressionAttributeValues": {
            ":d": {"N": str(delta)}, ":um": {"N": "1"}, ":t": {"S": iso()}, ":e": {"S": "cenario_a"},
        },
    }
    if com_limite:
        op["ConditionExpression"] = "quantidade <= :limite"
        op["ExpressionAttributeValues"][":limite"] = {"N": str(LIMITE_PRATELEIRA)}
    return op


def _preparar(cfg) -> None:
    """Origem com 100 unidades; destino acima do limite de prateleira."""
    t = aws.tabela(cfg.primaria, cfg.tabela)
    t.put_item(Item=aws.item_estoque(ORIGEM, cfg.primaria, "cenario_a"))
    t.put_item(Item=aws.item_estoque(DESTINO, cfg.primaria, "cenario_a",
                                     quantidade=LIMITE_PRATELEIRA + EXCESSO_DESTINO))


def _restaurar(cfg) -> None:
    t = aws.tabela(cfg.primaria, cfg.tabela)
    for n in (ORIGEM, DESTINO):
        t.put_item(Item=aws.item_estoque(n, cfg.primaria, "reset"))


def _total(cfg) -> int:
    return aws.resumo_regiao(cfg.primaria, cfg.tabela, consistente=True)["unidades"]


def _quantidade(cfg, n: int) -> int:
    it = aws.tabela(cfg.primaria, cfg.tabela).get_item(
        Key={"produto_id": config.id_produto(n)}, ConsistentRead=True)["Item"]
    return int(it["quantidade"])


def _transferir_sem_transacao(c, cfg) -> tuple[bool, bool]:
    """Devolve (concluida, origem_debitada)."""
    tabela = cfg.tabela
    c.update_item(**_update(tabela, config.id_produto(ORIGEM), -UNIDADES, com_limite=False))
    try:
        c.update_item(**_update(tabela, config.id_produto(DESTINO), +UNIDADES, com_limite=True))
    except Exception as e:  # noqa: BLE001
        if aws.codigo_erro(e) not in ERROS_PROVOCADOS:
            raise
        return False, True
    return True, True


def _transferir_com_transacao(c, cfg) -> tuple[bool, bool]:
    tabela = cfg.tabela
    try:
        c.transact_write_items(TransactItems=[
            {"Update": _update(tabela, config.id_produto(ORIGEM), -UNIDADES, com_limite=False)},
            {"Update": _update(tabela, config.id_produto(DESTINO), +UNIDADES, com_limite=True)},
        ])
    except Exception as e:  # noqa: BLE001
        if aws.codigo_erro(e) not in ERROS_PROVOCADOS:
            raise
        return False, False
    return True, True


def _modo(ex, cfg, c, nome: str, transferir) -> dict:
    ex.etapa("preparando_destino")
    _preparar(cfg)
    antes = _total(cfg)
    origem_antes = _quantidade(cfg, ORIGEM)

    ex.etapa(f"modo_{nome}", total=RODADAS)
    concluidas = 0
    parcial = False
    for _ in range(RODADAS):
        ok, origem_debitada = transferir(c, cfg)
        concluidas += ok
        parcial = parcial or (origem_debitada and not ok)
        ex.avancar()

    depois = _total(cfg)
    # Confirma pelo banco, não só pelo retorno das chamadas
    parcial = parcial or (_quantidade(cfg, ORIGEM) != origem_antes and concluidas == 0)
    resultado = {
        "transferencias_tentadas": RODADAS,
        "transferencias_concluidas": concluidas,
        "unidades_totais_antes": antes,
        "unidades_totais_depois": depois,
        "unidades_perdidas": antes - depois,
        "estado_parcial": parcial,
    }
    print(f"  {nome}: {resultado}", flush=True)
    _restaurar(cfg)
    return resultado


def executar(ex, cfg, parciais: dict) -> dict:
    r = aws.resumo_regiao(cfg.primaria, cfg.tabela, consistente=True)
    esperado = config.TOTAL_PRODUTOS * config.UNIDADES_POR_PRODUTO
    if r["itens"] != config.TOTAL_PRODUTOS or r["unidades"] != esperado:
        raise ErroCenario("ESTOQUE_NAO_RESETADO",
                          f"{cfg.tabela} tem {r['itens']} produtos e {r['unidades']} unidades; "
                          f"esperado {config.TOTAL_PRODUTOS} e {esperado}. Rode scripts/03_reset.py.")

    c = aws.cliente(cfg.primaria)
    parciais.setdefault("modos", {})
    try:
        parciais["modos"]["sem_transacao"] = _modo(ex, cfg, c, "sem_transacao", _transferir_sem_transacao)
        parciais["modos"]["com_transacao"] = _modo(ex, cfg, c, "com_transacao", _transferir_com_transacao)
    finally:
        _restaurar(cfg)
    return {"modos": parciais["modos"]}


def parametros(cfg) -> dict:
    return {
        "tabela": cfg.tabela,
        "produto_origem": config.id_produto(ORIGEM),
        "produto_destino": config.id_produto(DESTINO),
        "unidades_transferidas": UNIDADES,
        "limite_prateleira": LIMITE_PRATELEIRA,
        "rodadas": RODADAS,
    }


if __name__ == "__main__":
    _cfg = config.carregar()
    sys.exit(rodar_cli("A", parametros(_cfg), executar))
