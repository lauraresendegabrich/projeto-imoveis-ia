"""Teste isolado do Agente 3 — Analisador Qualitativo."""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.text_analyzer import analisar_comparaveis

print("=" * 60)
print("TESTE ISOLADO — AGENTE 3: ANALISADOR QUALITATIVO")
print("=" * 60)

# Imóvel alvo
imovel_alvo = {
    "rua": "Rua Doutor Liraucio Gomes",
    "numero": "119",
    "bairro": "Cambuí",
    "cidade": "Campinas",
    "estado": "SP",
    "propertyType": "Apartamentos",
    "area": 89,
    "bedrooms": 2,
    "bathrooms": 3,
    "parkingSpaces": 2,
    "neighborhood": "Cambuí",
    "street": "Rua Doutor Liraucio Gomes",
    "description": "Apartamento com 2 quartos, 3 banheiros, 2 vagas, 89m². Cambuí, Campinas/SP.",
    "images": [],
}

# Usa os dados já gerados pelo Agente 2
resultado = analisar_comparaveis(imovel_alvo=imovel_alvo)

print(f"\n{'=' * 60}")
print("RESULTADO DO AGENTE 3")
print(f"{'=' * 60}")

if not resultado:
    print("ERRO: resultado vazio!")
else:
    # Alvo
    alvo = resultado.get("imovel_alvo", {})
    analise_alvo = alvo.get("analise_qualitativa", {})
    print(f"\nIMÓVEL ALVO:")
    print(f"  Estado: {analise_alvo.get('estado_conservacao', '?')}")
    print(f"  Padrão: {analise_alvo.get('padrao_acabamento', '?')}")
    print(f"  Score: {analise_alvo.get('scores', {}).get('score_qualitativo', '?')}")
    print(f"  Classificação: {analise_alvo.get('classificacao_qualitativa', '?')}")
    print(f"  Fotos analisadas: {analise_alvo.get('fotos_analisadas', 0)}")

    # Comparáveis
    comparaveis = resultado.get("comparaveis", [])
    print(f"\nCOMPARÁVEIS ANALISADOS: {len(comparaveis)}")
    for i, c in enumerate(comparaveis[:5]):
        analise = c.get("analise_qualitativa", {})
        print(f"  [{i+1}] estado={analise.get('estado_conservacao','?')} | "
              f"padrao={analise.get('padrao_acabamento','?')} | "
              f"score={analise.get('scores',{}).get('score_qualitativo','?')} | "
              f"fotos={analise.get('fotos_analisadas', 0)}")

    # Resumo
    resumo = resultado.get("resumo", {})
    print(f"\nRESUMO:")
    print(f"  Total analisados: {resumo.get('total_analisados', '?')}")
    print(f"  Score médio: {resumo.get('score_qualitativo_medio', '?')}")
