"""Popula a tabela global: 50 produtos com 100 unidades cada.

Escreve na Região primária e espera a replicação chegar às outras Regiões.
Ao final, cada Região deve somar 5.000 unidades.

Uso: python scripts/02_seed_data.py [--espera 60]
"""
import argparse
import sys
import time

import _caminho  # noqa: F401
from lab import aws, config

ESPERADO_ITENS = config.TOTAL_PRODUTOS
ESPERADO_UNIDADES = config.TOTAL_PRODUTOS * config.UNIDADES_POR_PRODUTO


def semear(cfg, escritor: str = "seed") -> None:
    t = aws.tabela(cfg.primaria, cfg.tabela)
    with t.batch_writer() as lote:
        for n in range(1, config.TOTAL_PRODUTOS + 1):
            lote.put_item(Item=aws.item_estoque(n, cfg.primaria, escritor))


def conferir(cfg, espera_s: int) -> bool:
    """Espera todas as Regiões mostrarem o total esperado. Imprime o que encontrou."""
    limite = time.time() + espera_s
    while True:
        resumos = {r: aws.resumo_regiao(r, cfg.tabela) for r in cfg.regioes}
        certo = all(
            v["itens"] == ESPERADO_ITENS and v["unidades"] == ESPERADO_UNIDADES for v in resumos.values()
        )
        if certo or time.time() >= limite:
            for r, v in resumos.items():
                print(f"  {r:<12} itens={v['itens']:<3} unidades={v['unidades']}")
            return certo
        time.sleep(2)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--espera", type=int, default=60, help="segundos máximos esperando a replicação")
    args = p.parse_args()
    cfg = config.carregar()

    print(f"Escrevendo {ESPERADO_ITENS} produtos em {cfg.primaria} ...")
    semear(cfg)
    print("Conferindo as Regiões ...")
    if conferir(cfg, args.espera):
        print(f"OK: {ESPERADO_UNIDADES} unidades em cada Região.")
        return 0
    print("ERRO: as Regiões não convergiram para o total esperado no tempo dado.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
