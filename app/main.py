"""
Ponto de entrada do pipeline multiagente de precificação imobiliária
=====================================================================

COMO RODAR:
    .venv/Scripts/python.exe app/main.py

ESTADO ATUAL:
    Agentes 1 e 2 conectados e funcionando.
    Agentes 3, 4 e 5 pendentes de implementação.
"""

import logging
from app.graph import executar_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Imóvel alvo — altere aqui para avaliar outro imóvel
IMOVEL_ALVO = {
    "rua":           "Rua Franklin Maximo Pereira",
    "numero":        "188",
    "bairro":        "Centro",
    "cidade":        "Itajai",
    "estado":        "SC",
    "localizacao":   "Itajai, SC",
    "tipo":          "house",
    # Características para o Agente 2
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

if __name__ == "__main__":
    resultado = executar_pipeline(IMOVEL_ALVO)

    print("\n" + "=" * 55)
    print("RESULTADO DO PIPELINE")
    print("=" * 55)
    print(f"Status       : {resultado['status']}")
    print(f"Imóvel alvo  : {resultado['imovel_alvo']}")
    print(f"Comparáveis  : {resultado['resumo'].get('cluster_a', 0)} similares")
    print(f"Não similares: {resultado['resumo'].get('cluster_b', 0)}")
    print(f"Terrenos     : {resultado['resumo'].get('terrenos_excluidos', 0)}")
    print(f"Preço estimado: {resultado['preco_estimado'] or 'pendente (Agente 5)'}")
    print(f"Liquidez      : {resultado['liquidez'] or 'pendente (Agente 5)'}")
