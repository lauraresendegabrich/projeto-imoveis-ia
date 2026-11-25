"""Debug: por que o Agente 5 está usando só 1 comparável?"""
import json
import sys
sys.path.insert(0, ".")
from agents.price_liquidity import (
    carregar_dados_pipeline, extrair_preco, extrair_area,
    normalizar_tipo, TIPOS_TERRENO
)

print("=" * 60)
print("DEBUG — DADOS DO AGENTE 5")
print("=" * 60)

# Carrega exatamente como o Agente 5 faz
imovel_alvo, terrenos_zona, comparaveis_zona, dados_ag3, dados_ag4 = carregar_dados_pipeline()

print(f"\nImovel alvo: {imovel_alvo.get('propertyType', '?')} - {imovel_alvo.get('area', '?')}m2")
print(f"Terrenos na zona: {len(terrenos_zona)}")
print(f"Comparáveis na zona: {len(comparaveis_zona)}")

# Verifica os comparáveis
print(f"\n--- COMPARÁVEIS (primeiros 10) ---")
for i, c in enumerate(comparaveis_zona[:10]):
    preco = extrair_preco(c)
    area = extrair_area(c)
    tipo = normalizar_tipo(c.get("propertyType", ""))
    print(f"  [{i+1}] preco={preco} | area={area} | tipo={tipo} | "
          f"price_field={c.get('price','NULO')} | preco_field={c.get('preco','NULO')}")

# Verifica o JSON da zona homogênea direto
print(f"\n--- ZONA HOMOGENEA JSON ---")
zona = json.load(open("data/zona_homogenea_ag2.json", encoding="utf-8"))
confirmados = zona.get("comparaveis_confirmados", [])
print(f"Total confirmados: {len(confirmados)}")

# Conta quantos têm price/preco
com_price = sum(1 for c in confirmados if c.get("price"))
com_preco = sum(1 for c in confirmados if c.get("preco"))
com_area = sum(1 for c in confirmados if c.get("area"))
com_area_constr = sum(1 for c in confirmados if c.get("area_construida"))
print(f"Com 'price' (float): {com_price}")
print(f"Com 'preco' (string): {com_preco}")
print(f"Com 'area' (float): {com_area}")
print(f"Com 'area_construida' (string): {com_area_constr}")

# Mostra campos de preço/area dos primeiros 5
print(f"\n--- CAMPOS DOS PRIMEIROS 5 CONFIRMADOS ---")
for i, c in enumerate(confirmados[:5]):
    print(f"  [{i+1}] price={c.get('price','NULO')} | preco={c.get('preco','NULO')} | "
          f"area={c.get('area','NULO')} | area_construida={c.get('area_construida','NULO')} | "
          f"propertyType={c.get('propertyType','NULO')}")
