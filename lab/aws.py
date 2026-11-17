"""Acesso ao DynamoDB por Região. Só este módulo importa o boto3."""
from decimal import Decimal

from . import config
from .tempo import iso


def cliente(regiao: str, *, tentativas: int | None = None, endpoint_url: str | None = None,
            timeout_s: float = 3.0):
    """Cliente DynamoDB de baixo nível para uma Região.

    tentativas=1 desliga os retries do SDK, para que o cenário controle o backoff.
    endpoint_url permite apontar para um endpoint inválido e simular a Região fora do ar.
    """
    import boto3
    from botocore.config import Config as BotoConfig

    opcoes = {"connect_timeout": timeout_s, "read_timeout": timeout_s}
    if tentativas is not None:
        opcoes["retries"] = {"total_max_attempts": tentativas, "mode": "standard"}
    return boto3.client("dynamodb", region_name=regiao, endpoint_url=endpoint_url, config=BotoConfig(**opcoes))


def tabela(regiao: str, nome: str):
    """Recurso Table (alto nível) para uma Região."""
    import boto3

    return boto3.resource("dynamodb", region_name=regiao).Table(nome)


def codigo_erro(e: Exception) -> str:
    """Código do erro da AWS quando existir; senão, o nome da exceção."""
    resposta = getattr(e, "response", None)
    if isinstance(resposta, dict):
        codigo = resposta.get("Error", {}).get("Code")
        if codigo:
            return codigo
    return type(e).__name__


def item_estoque(n: int, regiao: str, escritor: str, quantidade: int = config.UNIDADES_POR_PRODUTO,
                 versao: int = 1) -> dict:
    """Item da tabela Estoque, com os atributos de versão e horário pedidos no enunciado."""
    return {
        "produto_id": config.id_produto(n),
        "nome": f"Produto {n:03d}",
        "quantidade": quantidade,
        "versao": versao,
        "atualizado_em": iso(),
        "regiao_escrita": regiao,
        "escritor": escritor,
    }


def resumo_regiao(regiao: str, nome: str) -> dict:
    """Conta itens e soma unidades de uma Região com Scan paginado (tabela pequena)."""
    t = tabela(regiao, nome)
    itens, unidades, kwargs = 0, 0, {"ProjectionExpression": "quantidade"}
    while True:
        pagina = t.scan(**kwargs)
        for it in pagina.get("Items", []):
            itens += 1
            unidades += int(it.get("quantidade", Decimal(0)))
        if "LastEvaluatedKey" not in pagina:
            return {"itens": itens, "unidades": unidades}
        kwargs["ExclusiveStartKey"] = pagina["LastEvaluatedKey"]
