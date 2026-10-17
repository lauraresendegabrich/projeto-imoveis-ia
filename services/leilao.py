"""
Avaliacao de imovel de leilao da CAIXA
======================================

Pergunta respondida: ate quanto posso pagar por este imovel para ter 55% de lucro?
Os 55% JA INCLUEM os custos de aquisicao (comissao, ITBI, registro, debitos): nada e
somado nem descontado.

Regra (nesta ordem):
  1. A estimativa do Agente 5 e confiavel? Usa o status que ele ja calcula
     (price_liquidity.py, MIN_AMOSTRAS_CONFIAVEL). Qualquer status diferente de "ok"
     (sem_amostra, valor_nao_estimado, amostra_insuficiente) ou Agente 5 sem
     resultado -> "Sem estimativa", sem lance maximo.
  2. lance_maximo = liquidez / FATOR_LUCRO_LEILAO
  3. sobra = lance_maximo - valor_minimo_caixa
       sobra >= 0 -> "Nao descartar"; sobra < 0 -> "Descartar"

O valor minimo e o "valor minimo de venda" do site da CAIXA. Ele NAO entra em nenhum
agente: preco de leilao fica bem abaixo do mercado e distorceria a escolha dos
comparaveis. O valor de avaliacao CAIXA e so informativo.
"""
from __future__ import annotations

from datetime import date, datetime

from services.formatos import ler_numero_br

# Lucro desejado de 55%, com os custos de aquisicao ja incluidos. Unico lugar do fator.
FATOR_LUCRO_LEILAO = 1.55

ORIGEM_CAIXA = "CAIXA"

# Modalidades do site da CAIXA. No Leilao SFI so registramos qual valor foi informado
# (1o ou 2o leilao); nao ha tratamento das etapas.
MODALIDADES_CAIXA = [
    "Venda Online",
    "Venda Direta Online",
    "Compra Direta",
    "Licitação Aberta",
    "Leilão SFI (valor do 1º leilão)",
    "Leilão SFI (valor do 2º leilão)",
    "Outra",
]

# Formas de pagamento como aparecem na pagina do imovel na CAIXA ("Formas de
# pagamento aceitas"). So registradas: nao entram no calculo.
FORMAS_PAGAMENTO_CAIXA = [
    "Recursos próprios (à vista)",
    "FGTS",
    "Financiamento",
    "Parcelamento",
]

DECISAO_NAO_DESCARTAR = "Não descartar"
DECISAO_DESCARTAR = "Descartar"
DECISAO_SEM_ESTIMATIVA = "Sem estimativa"


def ler_valor_reais(texto) -> float | None:
    """
    Valor em reais digitado no formulario: "323158", "323.158", "323.158,50",
    "R$ 323.158,50", "323158.50". Vazio -> None; invalido -> ValueError.
    """
    return ler_numero_br(texto)


def ler_data_br(texto) -> date | None:
    """
    Data digitada no formulario: "25/11/2026" ou "25/11/26". Vazio -> None;
    invalido -> ValueError.
    """
    texto = str(texto or "").strip()
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(texto)


def contar_status_zona(resultado_ag5: dict | None) -> dict:
    """
    Quantos comparaveis usados pelo Agente 5 (construcao e terreno) foram:
      confirmado    = dentro do raio da zona homogenea;
      fallback      = "zona nao verificada": completaram a amostra porque havia menos
                      de 5 confirmados (a distancia nao pode ser medida);
      sem_validacao = socorro do Agente 5: Cluster A usado sem nenhum confirmado.
    Os de fallback e sem_validacao contam para o minimo de 5 (decisao do professor,
    17/10/2026); o aviso na tela, no laudo e nos logs deixa isso claro.
    """
    usados = (resultado_ag5 or {}).get("comparaveis_usados") or {}
    contagem = {"confirmado": 0, "fallback": 0, "sem_validacao": 0}
    for lista in (usados.get("construcao") or [], usados.get("terreno") or []):
        for comparavel in lista:
            status = comparavel.get("status_zona") or "confirmado"
            contagem[status if status in contagem else "confirmado"] += 1
    contagem["total"] = sum(contagem.values())
    return contagem


def texto_aviso_zona(contagem: dict, escopo_busca: str | None = None) -> str | None:
    """
    Aviso com numeros sobre os comparaveis cuja distancia nao foi verificada (e sobre
    a busca na cidade toda). None quando todos foram confirmados perto do imovel.
    """
    partes = []
    total = contagem.get("total", 0)
    if contagem.get("sem_validacao"):
        partes.append(
            f"Nenhum comparável foi confirmado perto do imóvel. O valor usa "
            f"{contagem['sem_validacao']} imóveis parecidos encontrados na busca, sem verificar "
            f"a distância. Confira esses anúncios antes de decidir."
        )
    elif contagem.get("fallback"):
        partes.append(
            f"Só {contagem.get('confirmado', 0)} dos {total} comparáveis foram confirmados perto "
            f"do imóvel (dentro da zona homogênea). Os outros {contagem['fallback']} não têm "
            f"localização exata no anúncio, então não foi possível medir a distância: podem "
            f"estar perto ou longe. Eles contam para o mínimo de 5. Confira esses anúncios "
            f"antes de decidir."
        )
    if escopo_busca == "cidade":
        partes.append(
            "Nenhum anúncio foi encontrado na rua ou no bairro do imóvel; o valor usa imóveis "
            "parecidos de outros bairros da cidade."
        )
    return " ".join(partes) or None


def _metros(valor) -> str:
    return f"{int(round(float(valor))):,}".replace(",", ".")


def texto_aviso_raio(zona: dict | None) -> str | None:
    """
    Aviso quando o Agente 2 ampliou o raio da zona para chegar ao minimo de
    comparaveis (sem chamar a IA de novo). None quando nao houve ampliacao.
    """
    zona = zona or {}
    amp = zona.get("ampliacao_raio") or {}
    if not amp.get("ampliado"):
        return None
    minimo, limite = amp.get("minimo", 5), amp.get("limite_m", 1500)
    raio_ia = zona.get("raio_ia_m")
    partes = []
    for nome, raio_final, n in (
        ("comparáveis", zona.get("raio_final_m"), amp.get("confirmados_depois", 0)),
        ("terrenos", zona.get("raio_final_terrenos_m"), amp.get("terrenos_depois", 0)),
    ):
        if raio_final is None or raio_ia is None or raio_final == raio_ia:
            continue
        if n >= minimo:
            partes.append(
                f"Havia menos de {minimo} {nome} no raio de {_metros(raio_ia)} m; o raio foi "
                f"ampliado para {_metros(raio_final)} m para chegar a {n}."
            )
        else:
            partes.append(
                f"Havia menos de {minimo} {nome} no raio de {_metros(raio_ia)} m; o raio foi "
                f"ampliado até {_metros(limite)} m e ainda assim só {n} foram confirmados."
            )
    return " ".join(partes) or None


def _numero(valor) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def avaliar_leilao(
    resultado_ag5: dict | None,
    valor_minimo: float | None,
    valor_avaliacao: float | None = None,
) -> dict | None:
    """
    Decisao do leilao a partir do resultado do Agente 5.

    Retorna None quando o valor minimo nao foi informado (o bloco nao aparece).
    Caso contrario, um dict com: origem, decisao, valor_minimo, valor_avaliacao,
    lance_maximo, sobra, liquidez, fator_lucro, status_agente5 e
    comparaveis_fora_da_regiao (quantos comparaveis usados nao foram confirmados
    dentro da zona homogenea: entraram por fallback ou sem validacao de distancia).
    """
    valor_minimo = _numero(valor_minimo)
    if valor_minimo is None:
        return None

    resultado_ag5 = resultado_ag5 or {}
    status = resultado_ag5.get("status_avaliacao") or "sem_resultado"
    base = {
        "origem": ORIGEM_CAIXA,
        "valor_minimo": valor_minimo,
        "valor_avaliacao": _numero(valor_avaliacao),
        "fator_lucro": FATOR_LUCRO_LEILAO,
        "status_agente5": status,
        "decisao": DECISAO_SEM_ESTIMATIVA,
        "lance_maximo": None,
        "sobra": None,
        "liquidez": None,
        "comparaveis_fora_da_regiao": 0,
    }

    # 1. Estimativa confiavel? So o status "ok" do Agente 5 segue.
    liquidez = _numero((resultado_ag5.get("avaliacao_planilha") or {}).get("valor_liquidez"))
    if status != "ok" or not resultado_ag5.get("avaliacao_confiavel", False) or liquidez is None:
        return base

    # 2 e 3. Lance maximo e sobra.
    lance_maximo = liquidez / FATOR_LUCRO_LEILAO
    sobra = lance_maximo - valor_minimo

    usados = resultado_ag5.get("comparaveis_usados") or {}
    fora_da_regiao = sum(
        1
        for lista in (usados.get("construcao") or [], usados.get("terreno") or [])
        for comparavel in lista
        if comparavel.get("status_zona") in ("fallback", "sem_validacao")
    )

    return {
        **base,
        "decisao": DECISAO_NAO_DESCARTAR if sobra >= 0 else DECISAO_DESCARTAR,
        "lance_maximo": lance_maximo,
        "sobra": sobra,
        "liquidez": liquidez,
        "comparaveis_fora_da_regiao": fora_da_regiao,
    }


def linhas_laudo(leilao: dict | None, fmt_brl) -> list[str]:
    """
    Linhas da secao "AVALIACAO DE LEILAO (CAIXA)" do laudo TXT. `fmt_brl` formata
    valores em reais. Sem estimativa confiavel: so a decisao e o valor minimo.
    """
    if not leilao:
        return []
    linhas = [f"Decisão: {leilao['decisao']}"]
    if leilao.get("alvo_sem_localizacao"):
        linhas.append(
            "Atenção: endereço não localizado no mapa com precisão de rua ou bairro; "
            "a distância dos comparáveis não foi verificada."
        )
    if leilao.get("lance_maximo") is not None:
        sobra = leilao["sobra"]
        linhas += [
            f"Lance máximo: {fmt_brl(leilao['lance_maximo'])}",
            f"Valor mínimo CAIXA: {fmt_brl(leilao['valor_minimo'])}",
            f"{'Sobra' if sobra >= 0 else 'Falta'}: {fmt_brl(abs(sobra))}",
            f"(lance máximo = liquidez ÷ {leilao['fator_lucro']:.2f}; "
            f"lucro de 55% com os custos de aquisição incluídos)",
        ]
        if leilao.get("aviso_zona"):
            linhas.append(f"Atenção: {leilao['aviso_zona']}")
    else:
        linhas.append(f"Valor mínimo CAIXA: {fmt_brl(leilao['valor_minimo'])}")
    if leilao.get("valor_avaliacao"):
        linhas.append(f"Valor de avaliação CAIXA (informativo): {fmt_brl(leilao['valor_avaliacao'])}")
    return linhas
