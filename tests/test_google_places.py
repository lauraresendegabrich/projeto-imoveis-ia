"""Teste local do Agente 4 com Google Places API (substitui Overpass)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.infra_evaluator import _buscar_pois_classificados, _buscar_transporte

# Coordenadas de teste: Santa Luzia/MG (mesmo do log)
LAT = -19.765276
LON = -43.844099

print("=" * 55)
print("TESTE: Google Places API (POIs + Transporte)")
print("=" * 55)
print(f"Coordenadas: {LAT}, {LON}")
print(f"GOOGLE_MAPS_KEY: {'OK' if os.getenv('GOOGLE_MAPS_KEY') else 'NAO CONFIGURADA'}")
print()

print("--- Buscando POIs ---")
pois = _buscar_pois_classificados(LAT, LON)
print()

total_geral = 0
for faixa, categorias in pois.items():
    total_faixa = sum(len(v) for v in categorias.values())
    total_geral += total_faixa
    if total_faixa > 0:
        print(f"  {faixa}: {total_faixa} POIs")
        for cat, lista in categorias.items():
            if lista:
                print(f"    {cat}: {len(lista)} — {[p['nome'] for p in lista[:3]]}")

print(f"\n  TOTAL: {total_geral} POIs")
print()

print("--- Buscando Transporte ---")
transporte = _buscar_transporte(LAT, LON)
print(f"  Status: {transporte['status']}")
print(f"  Paradas: {len(transporte['paradas'])}")
print(f"  Estacoes: {len(transporte['estacoes'])}")
if transporte['paradas']:
    print(f"  Mais proxima: {transporte['paradas'][0]}")
print()
print("TESTE CONCLUIDO")
