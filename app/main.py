"""
Ponto de entrada do pipeline multiagente de precificação imobiliária
=====================================================================

COMO RODAR:
    .venv/Scripts/python.exe app/main.py

ESTADO ATUAL:
    Apenas o Agente 3 (Analisador Textual) está conectado aqui.
    O pipeline completo será montado em app/graph.py com LangGraph.

TODO:
    - Conectar todos os 5 agentes via LangGraph (app/graph.py)
    - Receber o imóvel alvo como input do usuário
    - Retornar estimativa de preço e liquidez
"""

from agents.text_analyzer import analisar_descricao

# Descrição de exemplo — substituir pelo campo description do imóvel alvo
descricao = "Apartamento reformado, com acabamento de luxo, próximo ao metrô, shopping e escolas, com varanda gourmet e armários planejados."

resultado = analisar_descricao(descricao)

print("ANÁLISE TEXTUAL DO IMÓVEL")
print("-" * 40)
print(resultado)
