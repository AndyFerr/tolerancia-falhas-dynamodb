"""Acesso ao DynamoDB por Região. Só este módulo importa o boto3."""
from decimal import Decimal

from . import config
from .tempo import iso


def cliente(regiao: str, *, tentativas: int | None = None, endpoint_url: str | None = None,
            timeout_s: float = 3.0):
    """Cliente DynamoDB de baixo nível para uma Região.

    tentativas=1 desliga os retries do SDK, para que o cenário controle o backoff.
    endpoint_url aponta para outro endpoint: serve para testar o caminho de erro
    do cliente. NÃO é a forma de simular queda de Região: o Cenário A remove a
    réplica de verdade, porque só assim existe convergência para medir.
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
        "preco": config.preco(n),
        "versao": versao,
        "atualizado_em": iso(),
        "regiao_escrita": regiao,
        "escritor": escritor,
    }


def resumo_regiao(regiao: str, nome: str) -> dict:
    """Conta itens, soma unidades e valor (preco × quantidade) de uma Região.

    Scan paginado: a tabela é pequena. O valor é o checksum de negócio do Cenário D.
    """
    t = tabela(regiao, nome)
    itens, unidades, valor = 0, 0, Decimal(0)
    kwargs = {"ProjectionExpression": "quantidade, preco"}
    while True:
        pagina = t.scan(**kwargs)
        for it in pagina.get("Items", []):
            itens += 1
            q = int(it.get("quantidade", 0))
            unidades += q
            valor += Decimal(it.get("preco", 0)) * q
        if "LastEvaluatedKey" not in pagina:
            return {"itens": itens, "unidades": unidades, "valor": valor}
        kwargs["ExclusiveStartKey"] = pagina["LastEvaluatedKey"]
