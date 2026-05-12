"""
Agente 3 — Analisador Textual
==============================

RESPONSABILIDADE:
    Processa as descrições dos imóveis usando LLM local (Ollama/phi3).
    Extrai características qualitativas como padrão construtivo, estado
    de conservação e diferenciais, convertendo-as em fatores que
    influenciam o valor e a liquidez do imóvel.

ENTRADA:
    Texto livre com a descrição do anúncio imobiliário.
    Pode ser o campo 'title' + 'description' do imóvel coletado.

SAÍDA (formato texto estruturado):
    padrao: [baixo | medio | alto]
    conservacao: [ruim | regular | bom | excelente]
    diferenciais: [lista separada por vírgula]
    impacto_valor: [baixo | medio | alto]
    impacto_liquidez: [baixo | medio | alto]

COMO USAR:
    from agents.text_analyzer import analisar_descricao

    resultado = analisar_descricao(
        "Casa reformada, 3 quartos, varanda gourmet, próximo ao metrô"
    )

DEPENDÊNCIAS:
    - Ollama rodando localmente com modelo llama3.2
      Instale: https://ollama.com | ollama pull llama3.2
    - langchain-ollama (já no requirements.txt)

TODO (próximas versões):
    - Retornar dict estruturado em vez de string
    - Adicionar score numérico de 0-10 para impacto_valor e impacto_liquidez
    - Integrar com o Agente 5 (Estimador de Preço e Liquidez)
"""

from services.llm_service import get_llm


def analisar_descricao(descricao: str) -> str:
    """
    Analisa a descrição de um imóvel e retorna fatores qualitativos.

    Usa o LLM local para interpretar o texto e classificar:
        - Padrão construtivo (baixo/médio/alto)
        - Estado de conservação (ruim/regular/bom/excelente)
        - Diferenciais do imóvel (piscina, varanda, reformado, etc.)
        - Impacto estimado no valor de mercado
        - Impacto estimado na liquidez (facilidade de venda)

    Parâmetros
    ----------
    descricao : str
        Texto do anúncio. Pode ser título, descrição ou ambos concatenados.

    Retorna
    -------
    str
        Texto estruturado com os campos acima, um por linha.
    """
    llm = get_llm()

    prompt = f"""
    Analise a descrição de um imóvel e responda exatamente no formato abaixo:

    padrao: [baixo, medio ou alto]
    conservacao: [ruim, regular, bom ou excelente]
    diferenciais: [liste os principais diferenciais separados por vírgula]
    impacto_valor: [baixo, medio ou alto]
    impacto_liquidez: [baixo, medio ou alto]

    Não escreva explicações longas.
    Seja objetivo.
    Responda em português.

    Descrição do imóvel:
    {descricao}
    """

    resposta = llm.invoke(prompt)
    return resposta
