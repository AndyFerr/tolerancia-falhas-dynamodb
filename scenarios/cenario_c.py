"""Cenário C — atualização perdida e sobrevenda (docs/CENARIOS.md; contrato, seção 2).

Dois processos vendem o mesmo produto (prod-042) ao mesmo tempo, 50 vendas
cada. Cada venda lê a quantidade, espera um pouco (a janela de concorrência)
e grava quantidade − 1.

  modo_sem_condicao  grava sem condição: uma escrita sobrescreve a outra em silêncio
  modo_com_condicao  grava com ConditionExpression sobre `versao`: o conflito vira
                     ConditionalCheckFailedException e a venda NÃO é confirmada

Cada modo roda 5 rodadas, com o produto de volta a 100 unidades no início de
cada uma. As métricas de cada modo são a SOMA das rodadas; o detalhe de cada
rodada fica em `por_rodada`.

Uso: python scenarios/cenario_c.py      (rode scripts/03_reset.py antes)
"""
import sys
import threading
import time

try:
    from . import _caminho  # noqa: F401
except ImportError:
    import _caminho  # noqa: F401

from lab import aws, config
from lab.execucao import ErroCenario, rodar_cli
from lab.tempo import iso

PRODUTO = 42
QUANTIDADE_INICIAL = config.UNIDADES_POR_PRODUTO
PROCESSOS = 2
VENDAS_POR_PROCESSO = 50
RODADAS = 5
JANELA_S = 0.02     # pausa entre ler e gravar; se não houver sobrevenda, aumente (risco R3)


def _vender(c, tabela: str, pid: str, com_condicao: bool) -> bool:
    """Uma venda (ler → esperar → gravar). True se a aplicação a confirmou."""
    it = c.get_item(TableName=tabela, Key={"produto_id": {"S": pid}}, ConsistentRead=True)["Item"]
    q, v = int(it["quantidade"]["N"]), int(it["versao"]["N"])
    time.sleep(JANELA_S)
    op = {
        "TableName": tabela,
        "Key": {"produto_id": {"S": pid}},
        "UpdateExpression": "SET quantidade = :q, versao = :v1, atualizado_em = :t, escritor = :e",
        "ExpressionAttributeValues": {
            ":q": {"N": str(q - 1)}, ":v1": {"N": str(v + 1)},
            ":t": {"S": iso()}, ":e": {"S": "cenario_c"},
        },
    }
    if com_condicao:
        op["ConditionExpression"] = "versao = :v"
        op["ExpressionAttributeValues"][":v"] = {"N": str(v)}
    try:
        c.update_item(**op)
        return True
    except Exception as e:  # noqa: BLE001
        if com_condicao and aws.codigo_erro(e) == "ConditionalCheckFailedException":
            return False
        raise


def _rodada(cfg, com_condicao: bool) -> dict:
    pid = config.id_produto(PRODUTO)
    aws.tabela(cfg.primaria, cfg.tabela).put_item(Item=aws.item_estoque(PRODUTO, cfg.primaria, "cenario_c"))

    largada = threading.Barrier(PROCESSOS)
    confirmadas = [0] * PROCESSOS
    conflitos = [0] * PROCESSOS
    erros: list = []

    def processo(i: int) -> None:
        c = aws.cliente(cfg.primaria)          # um cliente por thread
        try:
            largada.wait()
            for _ in range(VENDAS_POR_PROCESSO):
                if _vender(c, cfg.tabela, pid, com_condicao):
                    confirmadas[i] += 1
                else:
                    conflitos[i] += 1
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    threads = [threading.Thread(target=processo, args=(i,)) for i in range(PROCESSOS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if erros:
        raise erros[0]

    final = int(aws.tabela(cfg.primaria, cfg.tabela).get_item(
        Key={"produto_id": pid}, ConsistentRead=True)["Item"]["quantidade"])
    vendidas = sum(confirmadas)
    esperada = QUANTIDADE_INICIAL - vendidas
    return {
        "vendas_confirmadas": vendidas,
        "quantidade_esperada": esperada,
        "quantidade_final": final,
        "sobrevendas": final - esperada,
        "conflitos_detectados": sum(conflitos),
    }


def _modo(ex, cfg, nome: str, com_condicao: bool) -> dict:
    ex.etapa(f"modo_{nome}", total=RODADAS)
    por_rodada = []
    for _ in range(RODADAS):
        por_rodada.append(_rodada(cfg, com_condicao))
        print(f"  {nome}, rodada {len(por_rodada)}: {por_rodada[-1]}", flush=True)
        ex.avancar()
    soma = {k: sum(r[k] for r in por_rodada) for k in por_rodada[0]}
    return {**soma, "por_rodada": por_rodada}


def executar(ex, cfg, parciais: dict) -> dict:
    item = aws.tabela(cfg.primaria, cfg.tabela).get_item(
        Key={"produto_id": config.id_produto(PRODUTO)}, ConsistentRead=True).get("Item")
    if item is None or int(item["quantidade"]) != QUANTIDADE_INICIAL:
        raise ErroCenario("ESTOQUE_NAO_RESETADO",
                          f"{config.id_produto(PRODUTO)} não está com {QUANTIDADE_INICIAL} unidades. "
                          "Rode scripts/03_reset.py.")
    parciais.setdefault("modos", {})
    try:
        parciais["modos"]["sem_condicao"] = _modo(ex, cfg, "sem_condicao", com_condicao=False)
        parciais["modos"]["com_condicao"] = _modo(ex, cfg, "com_condicao", com_condicao=True)
    finally:
        aws.tabela(cfg.primaria, cfg.tabela).put_item(Item=aws.item_estoque(PRODUTO, cfg.primaria, "reset"))
    return {"modos": parciais["modos"]}


def parametros(cfg) -> dict:
    return {
        "tabela": cfg.tabela,
        "produto_id": config.id_produto(PRODUTO),
        "quantidade_inicial": QUANTIDADE_INICIAL,
        "processos": PROCESSOS,
        "vendas_por_processo": VENDAS_POR_PROCESSO,
        "rodadas": RODADAS,
        "janela_s": JANELA_S,
    }


if __name__ == "__main__":
    _cfg = config.carregar()
    sys.exit(rodar_cli("C", parametros(_cfg), executar))
