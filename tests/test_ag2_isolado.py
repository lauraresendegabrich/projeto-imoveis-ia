"""Teste isolado do Agente 2 — Identificador de Comparáveis."""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.comparables import identificar_comparaveis

print("=" * 60)
print("TESTE ISOLADO — AGENTE 2: IDENTIFICADOR DE COMPARÁVEIS")
print("=" * 60)

# Imóvel alvo: Apartamento 89m², 2q, Cambuí, Campinas
imovel_alvo = {
    "rua": "Rua Doutor Liraucio Gomes",
    "numero": "119",
    "bairro": "Cambuí",
    "cidade": "Campinas",
    "estado": "SP",
    "propertyType": "Apartamentos",
    "area": 89,
    "area_terreno": 0,
    "bedrooms": 2,
    "bathrooms": 3,
    "parkingSpaces": 2,
    "neighborhood": "Cambuí",
    "street": "Rua Doutor Liraucio Gomes",
    "description": "Apartamento com 2 quartos, 3 banheiros, 2 vagas, 89m². Cambuí, Campinas/SP.",
}

# Usa os dados já coletados pelo Agente 1 (imoveis_completos_ag1.json)
resultado = identificar_comparaveis(imovel_alvo=imovel_alvo)

print(f"\n{'=' * 60}")
print("RESULTADO DO AGENTE 2")
print(f"{'=' * 60}")

resumo = resultado.get("resumo", {})
print(f"Total analisados: {resumo.get('total_analisados', '?')}")
print(f"Cluster A (similares): {resumo.get('cluster_a', '?')}")
print(f"Cluster B (não similares): {resumo.get('cluster_b', '?')}")
print(f"Terrenos excluídos: {resumo.get('terrenos_excluidos', '?')}")
print(f"Método: {resumo.get('metodo', '?')}")

comparaveis = resultado.get("comparaveis", [])
cluster_a = [c for c in comparaveis if c.get("cluster") == "A"]
print(f"\nTop 10 do Cluster A:")
for i, c in enumerate(cluster_a[:10]):
    area = c.get("area", "?")
    quartos = c.get("bedrooms", "?")
    preco = c.get("price", 0)
    score = c.get("score_similaridade", 0)
    ranking = c.get("ranking_llm", "?")
    rua = c.get("street", "?")
    just = (c.get("justificativa", "") or "")[:60]
    print(f"  [{i+1}] {area}m² | {quartos}q | R$ {preco:,.0f} | score={score:.2f} | rank={ranking} | {rua}")
    if just:
        print(f"       → {just}")
