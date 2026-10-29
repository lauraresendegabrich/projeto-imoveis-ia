"""
Funil dos anuncios (modo conferencia)
=====================================

Mostra, para cada anuncio da avaliacao, em que agente ele saiu e por que (ou se
entrou no calculo). Serve para conferir as avaliacoes durante os testes; para
desligar, defina MOSTRAR_FUNIL=0 no .env / Secrets do Streamlit Cloud, e para tirar
de vez basta apagar este arquivo e a chamada em app/paginas/avaliacao.py.

Nao muda nenhum calculo: so le o que os agentes ja gravam no resultado.
"""
from __future__ import annotations

import os

from agents.price_liquidity import MIN_AMOSTRAS_CONFIAVEL

# "Chegou ao calculo" (e nao "entrou"): chegou ao Agente 5; o Motivo diz o que
# aconteceu na conta (usado na media ou cortado pela media aparada).
ENTROU = "✅ Chegou ao cálculo"
SAIU_AG1 = "Saiu no Agente 1 (busca)"
SAIU_AG2_PARECIDOS = "Saiu no Agente 2 (parecidos)"
SAIU_AG2_ZONA = "Saiu no Agente 2 (zona)"
SAIU_AG5 = "Saiu no Agente 5 (cálculo)"
ETAPAS = (ENTROU, SAIU_AG5, SAIU_AG2_ZONA, SAIU_AG2_PARECIDOS, SAIU_AG1)

ROTULOS_ORIGEM = {"proximidade": "proximidade", "cidade": "resto da cidade"}
ROTULOS_STATUS_ZONA = {
    "confirmado": "confirmado na zona",
    "fallback": "distância não verificada (completou a amostra)",
    "mesmo_bairro": "mesmo bairro, até 2,5 km (completou a amostra)",
    "sem_validacao": "sem verificar a distância (socorro)",
}


def funil_ligado() -> bool:
    """Ligado por padrao; MOSTRAR_FUNIL=0 (ou nao/false) desliga."""
    return str(os.getenv("MOSTRAR_FUNIL", "1")).strip().lower() not in ("0", "nao", "não", "false", "off")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _veio_por(c: dict) -> str:
    origem = c.get("origem_busca")
    if origem in ROTULOS_ORIGEM:
        dist = c.get("distancia_alvo_m")
        return ROTULOS_ORIGEM[origem] + (f" ({int(dist)} m)" if dist is not None else "")
    return "rua ou bairro"


def _motivo_parecidos(c: dict) -> str:
    pre = c.get("pre_classificacao") or {}
    if pre and not pre.get("elegivel_llm", True):
        motivos = pre.get("motivos_incompatibilidade") or []
        return "pré-classificação: " + ("; ".join(motivos) if motivos else "incompatível com o imóvel")
    if c.get("justificativa"):
        return "a IA não considerou parecido: " + str(c["justificativa"])
    if c.get("status_julgamento") and c.get("status_julgamento") != "julgado":
        return f"não julgado pela IA ({c.get('status_julgamento')})"
    return "não considerado parecido com o imóvel"


def _motivo_zona(c: dict, raio, nao_verificado: bool) -> str:
    dist = c.get("distancia_metros")
    if c.get("motivo_zona_nao_verificada"):
        return f"posição não confirmada: {c['motivo_zona_nao_verificada']}"
    if nao_verificado:
        return ("posição não confirmada (anúncio sem localização exata) e já havia comparáveis "
                "suficientes confirmados dentro da zona")
    if dist is not None and raio:
        return f"fora da zona: está a {int(dist)} m, e o raio usado foi de {int(raio)} m"
    if dist is None:
        return "fora da zona: posição do anúncio não pôde ser medida"
    return "fora da zona"


def _reais_m2(v) -> str:
    return f"R$ {float(v):,.0f}/m²".replace(",", ".")


def _valores_m2(lista) -> str:
    return " e ".join(_reais_m2(v) for v in dict.fromkeys(lista))


def motivo_na_conta(usado: dict, preco: dict) -> str:
    """
    O que aconteceu na conta do Agente 5 com um anuncio que chegou ao calculo:
    "R$ X/m², usado na média", "R$ X/m², cortado pela média aparada" ou
    "não houve cálculo: N comparáveis < mínimo de 5". Usa a conta que o Agente 5
    grava em cada comparavel usado (conta_m2: R$/m2 e se ficou na media aparada).
    """
    status = (preco or {}).get("status_avaliacao", "ok")
    if status == "amostra_insuficiente":
        n = len(((preco or {}).get("comparaveis_usados") or {}).get("construcao") or [])
        return (f"não houve cálculo: {n} {'comparável' if n == 1 else 'comparáveis'} < mínimo de "
                f"{MIN_AMOSTRAS_CONFIAVEL}")
    if status == "valor_nao_estimado":
        return "não houve cálculo: o valor deu zero"
    if status != "ok":
        return "não houve cálculo"
    conta = usado.get("conta_m2") or []
    if not conta:
        return "usado no cálculo"
    na_media = [c["valor_m2"] for c in conta if c.get("na_media")]
    cortados = [c["valor_m2"] for c in conta if not c.get("na_media")]
    if not cortados:
        return f"{_valores_m2(na_media)}, usado na média"
    if not na_media:
        return f"{_valores_m2(cortados)}, cortado pela média aparada"
    if set(na_media) == set(cortados):
        # Casa: o mesmo R$/m2 entra nas duas series; uma copia ficou e a outra foi cortada.
        return (f"{_valores_m2(na_media)}, usado na média uma vez (a outra cópia foi cortada "
                f"pela média aparada)")
    return f"{_valores_m2(na_media)}, usado na média; {_valores_m2(cortados)}, cortado pela média aparada"


def montar_funil(resultado: dict) -> list[dict]:
    """Uma linha por anuncio: onde saiu (ou se entrou) e o motivo."""
    resultado = resultado or {}
    candidatos = list(resultado.get("comparaveis") or [])
    vistos = {c.get("url") for c in candidatos if c.get("url")}
    for t in resultado.get("terrenos") or []:
        if t.get("url") not in vistos:
            candidatos.append(t)
            vistos.add(t.get("url"))

    zona = resultado.get("zona_homogenea") or {}
    raio_casas = zona.get("raio_final_m") or (zona.get("zona_homogenea") or {}).get("raio_metros")
    raio_terrenos = zona.get("raio_final_terrenos_m") or raio_casas
    zona_rodou = bool((zona.get("coordenadas_alvo") or {}).get("lat")) if zona else False
    urls = lambda lista: {x.get("url") for x in lista or [] if x.get("url")}
    na_zona = urls(zona.get("comparaveis_confirmados")) | urls(zona.get("terrenos"))
    nao_verificados = urls(zona.get("comparaveis_nao_verificados")) | urls(zona.get("terrenos_nao_verificados"))

    preco = resultado.get("preco_estimado") or {}
    usados = {u.get("url"): u for lista in (preco.get("comparaveis_usados") or {}).values() for u in lista or []}
    descartados = {d.get("url"): d for lista in (preco.get("comparaveis_descartados") or {}).values()
                   for d in lista or []}

    notas_ag3 = {}
    for c in (resultado.get("analise_qualitativa") or {}).get("comparaveis") or []:
        nota = ((c.get("analise_qualitativa") or {}).get("scores") or {}).get("score_qualitativo")
        if c.get("url") and nota is not None:
            notas_ag3[c["url"]] = nota

    linhas = []
    for c in candidatos:
        url = c.get("url")
        eh_terreno = c.get("cluster") == "terreno" or "terreno" in str(c.get("propertyType") or c.get("tipo") or "").lower()
        # Situacao na zona (coluna propria): confirmado, distancia nao verificada,
        # ampliacao do raio.
        situacao_zona = None
        if url in usados:
            status = (usados[url].get("status_zona") or "confirmado")
            situacao_zona = ROTULOS_STATUS_ZONA.get(status, status)
            if c.get("incluido_por_ampliacao_raio"):
                situacao_zona += " · entrou pela ampliação do raio"
        elif url in na_zona:
            situacao_zona = ROTULOS_STATUS_ZONA["confirmado"]
        elif url in nao_verificados:
            situacao_zona = "distância não verificada"
        if url in usados:
            etapa, motivo = ENTROU, motivo_na_conta(usados[url], preco)
            if c.get("possivel_anuncio_do_alvo"):
                motivo += " · alerta: possível anúncio do próprio imóvel"
        elif c.get("eh_anuncio_do_alvo"):
            etapa, motivo = SAIU_AG5, "excluído: é o anúncio do próprio imóvel (identidade confirmada)"
        elif url in descartados:
            etapa = SAIU_AG5
            motivo = descartados[url].get("motivo_descarte") or "descartado pelo Agente 5"
        elif not eh_terreno and c.get("cluster") != "A":
            etapa, motivo = SAIU_AG2_PARECIDOS, _motivo_parecidos(c)
        elif not zona:
            etapa, motivo = SAIU_AG2_ZONA, "a zona homogênea não foi calculada nesta avaliação"
        elif not zona_rodou:
            etapa, motivo = SAIU_AG2_ZONA, "endereço do imóvel não localizado no mapa: a distância não pôde ser medida"
        elif url in na_zona:
            etapa, motivo = SAIU_AG5, "estava na zona, mas não entrou no cálculo"
        else:
            etapa = SAIU_AG2_ZONA
            motivo = _motivo_zona(c, raio_terrenos if eh_terreno else raio_casas, url in nao_verificados)
        linhas.append({
            "Etapa": etapa,
            "Motivo": motivo,
            "Zona": situacao_zona,
            "Tipo": "Terreno" if eh_terreno else "Construção",
            "Preço": _num(c.get("price") or c.get("preco")),
            "Área (m²)": _num(c.get("area") or c.get("area_construida")),
            "Quartos": c.get("bedrooms") or c.get("quartos"),
            "Bairro": c.get("neighborhood") or c.get("bairro"),
            "Rua": c.get("street") or c.get("rua"),
            "Portal": c.get("source") or c.get("portal"),
            "Veio por": _veio_por(c),
            "Nota vizinhança (Ag3)": notas_ag3.get(url),
            "Anúncio": url,
        })

    # Repetidos que o Agente 1 juntou (ficou so um anuncio de cada imovel).
    for d in resultado.get("duplicatas_descartadas") or []:
        linhas.append({
            "Etapa": SAIU_AG1,
            "Motivo": (f"repetido: é o mesmo imóvel do anúncio que ficou ({d.get('Mantido')}); "
                       f"regra: {d.get('Motivo') or '-'}"),
            "Zona": None, "Tipo": None, "Preço": _num(d.get("Preço")), "Área (m²)": _num(d.get("Área")),
            "Quartos": None, "Bairro": None, "Rua": None, "Portal": d.get("Descartado"),
            "Veio por": None, "Nota vizinhança (Ag3)": None, "Anúncio": d.get("Anúncio descartado") or None,
        })
    linhas.sort(key=lambda l: (ETAPAS.index(l["Etapa"]), l["Tipo"] or "", l["Preço"] or 0))
    return linhas


def resumo_funil(linhas: list[dict]) -> dict:
    """Quantos anuncios em cada etapa."""
    return {etapa: sum(1 for l in linhas if l["Etapa"] == etapa) for etapa in ETAPAS}


VAZIO = "–"


def _reais(v) -> str:
    return f"R$ {v:,.0f}".replace(",", ".")


def _numero_br(v) -> str:
    """360 -> '360'; 179.5 -> '179,5'."""
    texto = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto[:-3] if texto.endswith(",00") else texto.rstrip("0")


def linhas_para_tela(linhas: list[dict]) -> list[dict]:
    """
    Linhas do funil como a tela mostra: "–" no lugar de vazio e preco com ponto de
    milhar (R$ 1.200.000). O Excel continua com os numeros (formatados la).
    """
    saida = []
    for linha in linhas:
        nova = {}
        for coluna, valor in linha.items():
            if coluna == "Anúncio":
                nova[coluna] = valor or None          # coluna de link: vazio fica em branco
            elif valor is None or valor == "":
                nova[coluna] = VAZIO
            elif coluna == "Preço":
                nova[coluna] = _reais(valor)
            elif isinstance(valor, float):
                nova[coluna] = _numero_br(valor)
            else:
                nova[coluna] = str(valor)
        saida.append(nova)
    return saida


def mostrar_funil(st, resultado: dict) -> None:
    """Bloco da tela com o resumo, o filtro por etapa e a tabela com o motivo de cada anuncio."""
    linhas = montar_funil(resultado)
    if not linhas:
        return
    import pandas as pd

    resumo = resumo_funil(linhas)
    with st.expander(f"🔎 Funil dos anúncios (conferência) — {len(linhas)} anúncios", expanded=False):
        st.caption(
            "Para cada anúncio: em que agente saiu e por quê, ou, se chegou ao cálculo, o que "
            "aconteceu na conta do Agente 5 (usado na média ou cortado pela média aparada). "
            "Só para conferência; não muda nenhum cálculo."
        )
        st.markdown(" · ".join(f"**{etapa}**: {n}" for etapa, n in resumo.items() if n))
        opcoes = ["Todos"] + [e for e in ETAPAS if resumo.get(e)]
        escolha = st.selectbox("Mostrar", opcoes, key="funil_filtro")
        tabela = pd.DataFrame(linhas_para_tela([l for l in linhas if escolha == "Todos" or l["Etapa"] == escolha]))
        st.dataframe(
            tabela, hide_index=True, use_container_width=True,
            column_config={
                "Anúncio": st.column_config.LinkColumn("Anúncio", display_text="ver"),
                "Motivo": st.column_config.TextColumn("Motivo", width="large"),
            },
        )
