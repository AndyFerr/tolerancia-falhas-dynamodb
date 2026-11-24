"""Confere se a conta permite o que os cenários usam (risco R14 de docs/RISCOS.md).

  PITR ligado na tabela Estoque          → Cenário D
  TransactWriteItems funcionando          → Cenário A
  ConditionExpression funcionando         → Cenários A e C
  Streams ligado na tabela Estoque        → extensão opcional

O teste de transação grava e apaga dois itens temporários (`teste-r14-*`).
Não gera custo relevante. Sai com código 1 se algo essencial falhar.

Uso: python scripts/04_verificar_recursos.py
"""
import sys

import _caminho  # noqa: F401
from lab import aws, config

CHAVES = ("teste-r14-a", "teste-r14-b")


def linha(ok: bool | None, nome: str, detalhe: str = "") -> bool | None:
    marca = {True: "OK  ", False: "FALHA", None: "aviso"}[ok]
    print(f"  [{marca}] {nome}" + (f": {detalhe}" if detalhe else ""))
    return ok


def main() -> int:
    cfg = config.carregar()
    c = aws.cliente(cfg.primaria)
    print(f"Região {cfg.primaria}, tabela {cfg.tabela}")
    resultados = []

    try:
        pitr = c.describe_continuous_backups(TableName=cfg.tabela)["ContinuousBackupsDescription"][
            "PointInTimeRecoveryDescription"]
        status = pitr.get("PointInTimeRecoveryStatus")
        detalhe = status
        if pitr.get("EarliestRestorableDateTime"):
            detalhe += f", restaurável desde {pitr['EarliestRestorableDateTime'].isoformat()}"
        resultados.append(linha(status == "ENABLED", "PITR", detalhe))
    except Exception as e:  # noqa: BLE001
        resultados.append(linha(False, "PITR", aws.codigo_erro(e)))

    try:
        c.transact_write_items(TransactItems=[
            {"Put": {"TableName": cfg.tabela, "Item": {"produto_id": {"S": k}, "quantidade": {"N": "1"}}}}
            for k in CHAVES
        ])
        c.transact_write_items(TransactItems=[
            {"Delete": {"TableName": cfg.tabela, "Key": {"produto_id": {"S": k}}}} for k in CHAVES
        ])
        resultados.append(linha(True, "TransactWriteItems", "gravou e apagou 2 itens temporários"))
    except Exception as e:  # noqa: BLE001
        resultados.append(linha(False, "TransactWriteItems", aws.codigo_erro(e)))

    try:
        c.update_item(
            TableName=cfg.tabela, Key={"produto_id": {"S": "teste-r14-inexistente"}},
            UpdateExpression="SET quantidade = :q", ConditionExpression="attribute_exists(produto_id)",
            ExpressionAttributeValues={":q": {"N": "1"}},
        )
        resultados.append(linha(False, "ConditionExpression", "a condição deveria ter falhado e não falhou"))
    except Exception as e:  # noqa: BLE001
        ok = aws.codigo_erro(e) == "ConditionalCheckFailedException"
        resultados.append(linha(ok, "ConditionExpression", "falhou como esperado" if ok else aws.codigo_erro(e)))

    try:
        spec = c.describe_table(TableName=cfg.tabela)["Table"].get("StreamSpecification", {})
        linha(True if spec.get("StreamEnabled") else None, "Streams", spec.get("StreamViewType", "desligado"))
    except Exception as e:  # noqa: BLE001
        linha(None, "Streams", aws.codigo_erro(e))

    if all(resultados):
        print("OK: a conta permite PITR, transações e escrita condicional.")
        return 0
    print("ERRO: algum recurso usado pelos cenários não está disponível. Ver risco R14.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
