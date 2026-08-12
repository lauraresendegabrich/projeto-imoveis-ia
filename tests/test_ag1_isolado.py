"""Teste isolado do Agente 1 — Coleta de imóveis."""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.collector import coletar_imoveis

print("=" * 60)
print("TESTE ISOLADO — AGENTE 1: COLETOR")
print("=" * 60)

resultado = coletar_imoveis(
    localizacao="Campinas, SP",
    tipo_imovel="apartment",
    bairro="Cambuí",
    rua="Rua Doutor Liraucio Gomes",
)

print(f"\n{'=' * 60}")
print(f"RESULTADO FINAL: {len(resultado)} imóveis coletados")
print(f"{'=' * 60}")

for i, im in enumerate(resultado[:15]):
    area = im.get("area", "?")
    quartos = im.get("bedrooms", "?")
    preco = im.get("price", 0)
    bairro = im.get("neighborhood", "?")
    source = im.get("source", "Apify")
    rua_im = im.get("street", "?")
    print(f"  [{i+1:>2}] {area:>5}m2 | {quartos}q | R$ {preco:>12,.0f} | {bairro} | {rua_im} | {source}")

if len(resultado) > 15:
    print(f"  ... e mais {len(resultado) - 15}")

# Contagem por fonte
athena_count = sum(1 for im in resultado if im.get("source") == "Athena/S3")
apify_count = len(resultado) - athena_count
print(f"\nFontes: {athena_count} Athena | {apify_count} Apify")
