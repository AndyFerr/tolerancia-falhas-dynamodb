"""Devolve a tabela global ao estado inicial entre execuções.

Regrava os 50 produtos com 100 unidades e versão 1, e apaga qualquer item
que não seja um dos 50 produtos (sobras de cenários).

Uso: python scripts/03_reset.py [--espera 60]
"""
import importlib
import sys

import _caminho  # noqa: F401
from lab import aws, config

seed = importlib.import_module("02_seed_data")


def apagar_sobras(cfg) -> int:
    validos = {config.id_produto(n) for n in range(1, config.TOTAL_PRODUTOS + 1)}
    t = aws.tabela(cfg.primaria, cfg.tabela)
    sobras, kwargs = [], {"ProjectionExpression": "produto_id"}
    while True:
        pagina = t.scan(**kwargs)
        sobras += [i["produto_id"] for i in pagina.get("Items", []) if i["produto_id"] not in validos]
        if "LastEvaluatedKey" not in pagina:
            break
        kwargs["ExclusiveStartKey"] = pagina["LastEvaluatedKey"]
    with t.batch_writer() as lote:
        for chave in sobras:
            lote.delete_item(Key={"produto_id": chave})
    return len(sobras)


def main() -> int:
    cfg = config.carregar()

    print(f"Apagando sobras em {cfg.primaria} ...")
    print(f"  {apagar_sobras(cfg)} item(ns) removido(s)")
    print("Regravando os produtos ...")
    seed.semear(cfg, escritor="reset")
    if seed.conferir(cfg) and seed.conferir_produto_throttle(cfg):
        print("OK: estado inicial restaurado.")
        return 0
    print("ERRO: o estado restaurado não bateu com o esperado.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
