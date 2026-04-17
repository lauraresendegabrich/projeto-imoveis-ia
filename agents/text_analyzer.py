from services.llm_service import get_llm

def analisar_descricao(descricao: str) -> str:
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