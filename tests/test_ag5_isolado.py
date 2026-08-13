"""Teste isolado do Agente 5 — Estimador de Preço e Liquidez."""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.price_liquidity import estimar_preco

print("=" * 60)
print("TESTE ISOLADO — AGENTE 5: ESTIMADOR DE PREÇO E LIQUIDEZ")
print("=" * 60)

# Imóvel alvo (complementa dados do Ag.3)
imovel_alvo_extra = {
    "area": 89,
    "area_terreno": 0,
    "propertyType": "Apartamentos",
    "bedrooms": 2,
    "bathrooms": 3,
    "parkingSpaces": 2,
}

resultado = estimar_preco(imovel_alvo_extra=imovel_alvo_extra)

print(f"\n{'=' * 60}")
print("RESULTADO DO AGENTE 5")
print(f"{'=' * 60}")

# Avaliação planilha
av = resultado.get("avaliacao_planilha", {})
print(f"\nAVALIAÇÃO PLANILHA:")
print(f"  Valor mínimo:  R$ {av.get('valor_minimo_imovel', 0):,.2f}")
print(f"  Valor médio:   R$ {av.get('valor_medio_imovel', 0):,.2f}")
print(f"  Desconto:      {av.get('desconto_liquidez_percentual', '?')}%")
print(f"  Valor liquidez: R$ {av.get('valor_liquidez', 0):,.2f}")

# Liquidez experimental
liq = resultado.get("liquidez_experimental", {})
print(f"\nLIQUIDEZ EXPERIMENTAL:")
print(f"  Score liquidez:  {liq.get('score_liquidez', '?')}")
print(f"  Classificação:   {liq.get('classificacao', '?')}")
print(f"  Tempo estimado:  {liq.get('tempo_estimado', '?')}")
print(f"  Score Ag.3 usado: {liq.get('score_agente3_usado', '?')}")
print(f"  Score Ag.4 usado: {liq.get('score_agente4_usado', '?')}")

# Auditoria
audit = resultado.get("auditoria", {})
print(f"\nAUDITORIA:")
print(f"  Terrenos na zona: {len(audit.get('valores_m2_terreno', []))}")
print(f"  m2 terreno mínimo: R$ {audit.get('valor_m2_terreno_minimo', 0):,.2f}")
print(f"  m2 terreno médio:  R$ {audit.get('valor_m2_terreno_medio', 0):,.2f}")
print(f"  Série MIN/TERRENO: {len(audit.get('m2_construcao_min_terreno', []))} valores")
print(f"  Série MÉD/TERRENO: {len(audit.get('m2_construcao_med_terreno', []))} valores")
print(f"  m2 construção mínimo: R$ {audit.get('valor_m2_construcao_minimo', 0):,.2f}")
print(f"  m2 construção médio:  R$ {audit.get('valor_m2_construcao_medio', 0):,.2f}")

# Avisos
avisos = resultado.get("avisos", [])
if avisos:
    print(f"\nAVISOS:")
    for a in avisos:
        print(f"  ⚠️ {a}")
