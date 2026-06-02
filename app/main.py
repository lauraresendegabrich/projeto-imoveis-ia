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
    "rua":           "Rua Frederico Soares",
    "numero":        "499",
    "bairro":        "Santa Fe",
    "cidade":        "Campo Grande",
    "estado":        "MS",
    "localizacao":   "Campo Grande, MS",

    # Tipo (obrigatório para Agente 1)
    "tipo":          "house",   # "house" (casas + terrenos) ou "apartment"

    # Características do imóvel (para Agente 2 — score de similaridade)
    "propertyType":  "Casas",
    "area":          230,
    "area_terreno":  360,       # área do terreno em m² (para Agente 5)
    "bedrooms":      3,
    "bathrooms":     2,
    "parkingSpaces": 1,
    "neighborhood":  "Santa Fe",
    "street":        "Rua Frederico Soares",
    "description":   "Casa com 3 quartos, 1 vaga na garagem, varanda/sacada, área de serviço, 2 WC, sala, lavabo, cozinha. Equipamento de segurança, espaço com churrasqueira. Área privativa 230m², terreno 360m². Bairro Santa Fé, Campo Grande/MS.",
    "images": [],
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
