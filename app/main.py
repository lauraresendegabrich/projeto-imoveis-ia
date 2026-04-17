from agents.text_analyzer import analisar_descricao

descricao = "Apartamento reformado, com acabamento de luxo, próximo ao metrô, shopping e escolas, com varanda gourmet e armários planejados."

resultado = analisar_descricao(descricao)

print("ANÁLISE TEXTUAL DO IMÓVEL")
print("-" * 40)
print(resultado)