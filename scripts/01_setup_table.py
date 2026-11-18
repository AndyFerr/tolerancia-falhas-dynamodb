"""Verifica a tabela global criada pelo Terraform.

Não cria nada: espera a tabela e as réplicas ficarem ACTIVE nas Regiões
configuradas e confere se o PITR está ligado. Confere também se a tabela
de throttling existe, está ACTIVE e em modo provisionado. Sai com código 1 se algo faltar.

Uso: python scripts/01_setup_table.py [--espera 300]
"""
import argparse
import sys
import time

import _caminho  # noqa: F401
from lab import aws, config


def estado_regiao(regiao: str, nome: str) -> dict:
    c = aws.cliente(regiao)
    try:
        t = c.describe_table(TableName=nome)["Table"]
    except Exception as e:  # noqa: BLE001
        return {"regiao": regiao, "status": "INDISPONIVEL", "erro": aws.codigo_erro(e)}
    pitr = c.describe_continuous_backups(TableName=nome)["ContinuousBackupsDescription"]
    return {
        "regiao": regiao,
        "status": t["TableStatus"],
        "replicas": sorted(r["RegionName"] for r in t.get("Replicas", [])),
        "status_replicas": {r["RegionName"]: r.get("ReplicaStatus") for r in t.get("Replicas", [])},
        "cobranca": t.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
        "pitr": pitr["PointInTimeRecoveryDescription"]["PointInTimeRecoveryStatus"],
        "erro": None,
    }


def pronto(estados: list, regioes: tuple) -> bool:
    for e in estados:
        if e["status"] != "ACTIVE" or e["pitr"] != "ENABLED":
            return False
        outras = set(regioes) - {e["regiao"]}
        if not outras.issubset(e["replicas"]):
            return False
        if any(s != "ACTIVE" for s in e["status_replicas"].values()):
            return False
    return True


def conferir_throttle(cfg) -> bool:
    """A tabela do Cenário B precisa existir, estar ACTIVE e em modo provisionado."""
    c = aws.cliente(cfg.primaria)
    try:
        t = c.describe_table(TableName=cfg.tabela_throttle)["Table"]
    except Exception as e:  # noqa: BLE001
        print(f"  {cfg.tabela_throttle:<16} INDISPONIVEL ({aws.codigo_erro(e)})")
        return False
    cobranca = t.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
    wcu = t.get("ProvisionedThroughput", {}).get("WriteCapacityUnits")
    print(f"  {cfg.tabela_throttle:<16} {t['TableStatus']:<9} cobrança={cobranca} WCU={wcu}")
    return t["TableStatus"] == "ACTIVE" and cobranca == "PROVISIONED"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--espera", type=int, default=300, help="segundos máximos esperando ACTIVE")
    args = p.parse_args()
    cfg = config.carregar()

    limite = time.time() + args.espera
    while True:
        estados = [estado_regiao(r, cfg.tabela) for r in cfg.regioes]
        for e in estados:
            if e["erro"]:
                print(f"  {e['regiao']:<12} {e['status']}  ({e['erro']})")
            else:
                print(f"  {e['regiao']:<12} {e['status']:<9} PITR={e['pitr']:<8} "
                      f"cobrança={e['cobranca']}  réplicas={e['replicas']}")
        global_ok = all(not e["erro"] for e in estados) and pronto(estados, cfg.regioes)
        throttle_ok = conferir_throttle(cfg)
        if global_ok and throttle_ok:
            print(f"OK: tabela {cfg.tabela} ACTIVE em {len(cfg.regioes)} Regiões, com PITR ligado; "
                  f"{cfg.tabela_throttle} ACTIVE e provisionada.")
            return 0
        if time.time() >= limite:
            print("ERRO: a tabela não ficou pronta no tempo esperado. Confira o terraform apply.")
            return 1
        print("  ... aguardando 10 s")
        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())
