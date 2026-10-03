"""
Registra no Athena as pastas novas da tabela imoveis.anuncios.

O scraper grava cada estado numa pasta portal=<p>/coleta=<data>/estado=<UF>/ no S3,
mas o Athena so enxerga as pastas registradas como particoes. Quando uma coleta
adiciona estados (ou uma coleta nova comeca), rode:

    .venv/Scripts/python.exe -m tools.atualizar_particoes

So executa MSCK REPAIR TABLE (registra particoes). Nao le, altera nem apaga dados
no S3, e nao mexe na tabela antiga imoveis.vivareal.
"""
import logging
import sys

sys.path.insert(0, ".")

from services.athena_client import AthenaClient

logging.basicConfig(level=logging.WARNING)


def _particoes(client: AthenaClient) -> dict[tuple[str, str], int]:
    linhas = client.executar_query(
        'SELECT portal, coleta, count(*) AS estados FROM "anuncios$partitions" '
        "GROUP BY portal, coleta",
        timeout=60,
    )
    return {(r["portal"], r["coleta"]): int(r["estados"]) for r in linhas}


def main() -> None:
    client = AthenaClient()
    antes = _particoes(client)
    print("Registrando particoes novas (MSCK REPAIR TABLE anuncios)... pode levar alguns minutos")
    client.executar_query("MSCK REPAIR TABLE anuncios", timeout=900)
    depois = _particoes(client)

    print(f"\n{'portal':12s} {'coleta':11s} {'estados':>7s}  novos")
    for chave in sorted(depois):
        novos = depois[chave] - antes.get(chave, 0)
        print(f"{chave[0]:12s} {chave[1]:11s} {depois[chave]:7d}  {'+' + str(novos) if novos else ''}")


if __name__ == "__main__":
    main()
