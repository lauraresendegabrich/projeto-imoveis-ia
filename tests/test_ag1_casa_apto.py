"""Teste do Agente 1 — Casa e Apartamento separados."""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.collector import coletar_imoveis

# ==============================================================
# TESTE 1: CASA
# ==============================================================
print("\n" + "=" * 60)
print("TESTE 1 — CASA (Jardim Guanabara, Campinas/SP)")
print("=" * 60)

resultado_casa = coletar_imoveis(
    localizacao="Campinas, SP",
    tipo_imovel="house",
    bairro="Jardim Guanabara",
    rua="Rua Conego Nery",
)

print(f"\nRESULTADO CASA: {len(resultado_casa)} imóveis")
# Conta tipos
casas = [i for i in resultado_casa if i.get("propertyType") == "Casas"]
terrenos = [i for i in resultado_casa if i.get("propertyType") == "Terrenos"]
outros = [i for i in resultado_casa if i.get("propertyType") not in ("Casas", "Terrenos")]
print(f"  Casas: {len(casas)} | Terrenos: {len(terrenos)} | Outros: {len(outros)}")
athena = sum(1 for i in resultado_casa if i.get("source") == "Athena/S3")
apify = len(resultado_casa) - athena
print(f"  Fontes: {athena} Athena | {apify} Apify")
for i, im in enumerate(resultado_casa[:5]):
    print(f"  [{i+1}] {im.get('area','?')}m2 | {im.get('bedrooms','?')}q | R$ {im.get('price',0):,.0f} | {im.get('propertyType','?')} | {im.get('street','?')}")

# ==============================================================
# TESTE 2: APARTAMENTO
# ==============================================================
print("\n" + "=" * 60)
print("TESTE 2 — APARTAMENTO (Jardim Guanabara, Campinas/SP)")
print("=" * 60)

resultado_apto = coletar_imoveis(
    localizacao="Campinas, SP",
    tipo_imovel="apartment",
    bairro="Jardim Guanabara",
    rua="Rua Conego Nery",
)

print(f"\nRESULTADO APARTAMENTO: {len(resultado_apto)} imóveis")
aptos = [i for i in resultado_apto if i.get("propertyType") == "Apartamentos"]
outros_a = [i for i in resultado_apto if i.get("propertyType") != "Apartamentos"]
print(f"  Apartamentos: {len(aptos)} | Outros: {len(outros_a)}")
athena_a = sum(1 for i in resultado_apto if i.get("source") == "Athena/S3")
apify_a = len(resultado_apto) - athena_a
print(f"  Fontes: {athena_a} Athena | {apify_a} Apify")
for i, im in enumerate(resultado_apto[:5]):
    print(f"  [{i+1}] {im.get('area','?')}m2 | {im.get('bedrooms','?')}q | R$ {im.get('price',0):,.0f} | {im.get('propertyType','?')} | {im.get('street','?')}")

# ==============================================================
print("\n" + "=" * 60)
print("RESUMO")
print("=" * 60)
print(f"  Casa:        {len(resultado_casa)} imóveis ({len(casas)} casas + {len(terrenos)} terrenos)")
print(f"  Apartamento: {len(resultado_apto)} imóveis ({len(aptos)} apartamentos)")
print("  OK!" if len(resultado_casa) > 0 and len(resultado_apto) > 0 else "  FALHA!")
