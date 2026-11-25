"""Teste isolado da Zona Homogênea (Agente 2 - Etapa 4)."""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.comparables import analisar_zona_homogenea

print("=" * 60)
print("TESTE ISOLADO — ZONA HOMOGÊNEA (Groq qwen3.6-27b)")
print("=" * 60)

# Testa com o apartamento do Cambuí (sabemos que funciona)
resultado = analisar_zona_homogenea(
    endereco_alvo="Rua Doutor Liraucio Gomes, 119, Cambuí, Campinas, SP",
    imoveis=[],  # Sem imóveis para geocodificar (só testa a análise visual)
    cidade="Campinas",
    estado="SP",
)

print(f"\n{'=' * 60}")
print("RESULTADO")
print(f"{'=' * 60}")

zona = resultado.get("zona_homogenea", {})
print(f"Padrão construtivo: {zona.get('padrao_construtivo', '?')}")
print(f"Homogeneidade visual: {zona.get('homogeneidade_visual', '?')}")
print(f"Densidade urbana: {zona.get('densidade_urbana', '?')}")
print(f"Raio sugerido: {zona.get('raio_sugerido_metros', zona.get('raio_metros', '?'))}m")
print(f"Justificativa: {zona.get('justificativa_raio', '?')}")
print(f"Confiança: {zona.get('confianca', '?')}")
print(f"Descrição: {zona.get('descricao_zona_homogenea', '?')}")

confirmados = resultado.get("comparaveis_confirmados", [])
fora = resultado.get("fora_zona", [])
print(f"\nNa zona: {len(confirmados)} | Fora: {len(fora)}")
