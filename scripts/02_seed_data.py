"""Popula a tabela Estoque: 50 produtos com 100 unidades cada.

Ao final, a tabela deve somar 5.000 unidades. Na EstoqueThrottle entra
apenas o produto do Cenário B (prod-007): a 1 WCU, semear 50 itens seria lento.

Uso: python scripts/02_seed_data.py [--espera 60]
"""
import sys

import _caminho  # noqa: F401
from lab import aws, config

PRODUTO_THROTTLE = 7   # produto usado pelo Cenário B; precisa bater com prod-007 no contrato
ESPERADO_ITENS = config.TOTAL_PRODUTOS
ESPERADO_UNIDADES = config.TOTAL_PRODUTOS * config.UNIDADES_POR_PRODUTO


def semear(cfg, escritor: str = "seed") -> None:
    t = aws.tabela(cfg.primaria, cfg.tabela)
    with t.batch_writer() as lote:
        for n in range(1, config.TOTAL_PRODUTOS + 1):
            lote.put_item(Item=aws.item_estoque(n, cfg.primaria, escritor))

    # Tabela de throttling: um único produto, porque ela tem 1 WCU.
    aws.tabela(cfg.primaria, cfg.tabela_throttle).put_item(
        Item=aws.item_estoque(PRODUTO_THROTTLE, cfg.primaria, escritor)
    )


def conferir(cfg) -> bool:
    """Confere o total da tabela com leitura fortemente consistente."""
    r = aws.resumo_regiao(cfg.primaria, cfg.tabela, consistente=True)
    print(f"  {cfg.tabela:<16} itens={r['itens']:<3} unidades={r['unidades']}")
    return r["itens"] == ESPERADO_ITENS and r["unidades"] == ESPERADO_UNIDADES  

def conferir_produto_throttle(cfg) -> bool:
    """O Cenário B precisa do produto na tabela de throttling."""
    t = aws.tabela(cfg.primaria, cfg.tabela_throttle)
    pid = config.id_produto(PRODUTO_THROTTLE)
    achou = "Item" in t.get_item(Key={"produto_id": pid}, ConsistentRead=True)
    print(f"  {cfg.tabela_throttle:<16} {pid}: {'ok' if achou else 'AUSENTE'}")
    return achou


def main() -> int:
    cfg = config.carregar()

    print(f"Escrevendo {ESPERADO_ITENS} produtos em {cfg.primaria} ...")
    semear(cfg)
    print("Conferindo os dados ...")
    if conferir(cfg) and conferir_produto_throttle(cfg):
        print(f"OK: {ESPERADO_UNIDADES} unidades em {cfg.tabela}; produto do Cenário B semeado.")
        return 0
    print("ERRO: os dados não bateram com o esperado.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
