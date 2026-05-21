"""
Pipeline Multiagente de Precificação Imobiliária
=================================================

COMO RODAR:
    .venv/Scripts/python.exe app/main.py

FLUXO:
    Agente 1 (coleta) → Agente 2 (comparáveis + zona) → Agente 3 + 4 (paralelo) → Agente 5 (preço)
"""

import logging
from app.graph import executar_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# =============================================================================
# IMOVEL ALVO — altere aqui para avaliar outro imóvel
# =============================================================================

IMOVEL_ALVO = {
    # Localização (obrigatório para Agente 1)
    "rua":           "Rua Franklin Maximo Pereira",
    "numero":        "188",
    "bairro":        "Centro",
    "cidade":        "Itajai",
    "estado":        "SC",
    "localizacao":   "Itajai, SC",

    # Tipo (obrigatório para Agente 1)
    "tipo":          "house",   # "house" (casas + terrenos) ou "apartment"

    # Características do imóvel (para Agente 2 — score de similaridade)
    "propertyType":  "Casas",
    "area":          170,
    "bedrooms":      3,
    "bathrooms":     4,
    "parkingSpaces": 2,
    "pricePerSqm":   8205.88,
    "price":         1395000,
    "priceFormatted": "R$ 1.395.000",
    "neighborhood":  "Centro",
    "street":        "Rua Franklin Máximo Pereira",
    "description":   "Casa com 170m², 3 quartos, 4 banheiros, 2 vagas, Centro de Itajaí",
}

# =============================================================================
# EXECUÇÃO
# =============================================================================

if __name__ == "__main__":
    resultado = executar_pipeline(IMOVEL_ALVO)

    print("\n" + "=" * 60)
    print("RESULTADO DO PIPELINE")
    print("=" * 60)
    print(f"Status:          {resultado['status']}")
    print(f"Imóvel alvo:     {resultado['imovel_alvo']}")

    resumo = resultado.get("resumo", {})
    print(f"Comparáveis:     {resumo.get('cluster_a', '?')} similares | {resumo.get('cluster_b', '?')} não similares")
    print(f"Terrenos:        {resumo.get('terrenos_excluidos', '?')}")

    ag3 = resultado.get("analise_qualitativa", {})
    if ag3:
        print(f"Score qualit.:   {ag3.get('resumo', {}).get('score_qualitativo_medio', '?')}")

    ag4 = resultado.get("infraestrutura", {})
    if ag4:
        print(f"Score infra:     {ag4.get('scores', {}).get('score_final', '?')}")

    print(f"Preço estimado:  {resultado.get('preco_estimado') or 'pendente (Agente 5)'}")
