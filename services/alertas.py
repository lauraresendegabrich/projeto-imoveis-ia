"""
Alertas automaticos de cada avaliacao
=====================================

Regras simples (sem IA e sem mudar nenhum calculo) que apontam avaliacoes que
merecem atencao: poucos comparaveis, comparaveis fora da zona, precos espalhados,
divergencia com o valor de avaliacao CAIXA, decisao apertada, possivel anuncio do
proprio imovel no calculo, falha de agente, amostra concentrada num mesmo
empreendimento, terrenos fora do padrao e possiveis repetidos que ficaram no calculo.

Gravados no banco (coluna execucoes.alertas) para quem for analisar os resultados
filtrar as avaliacoes que precisam ser olhadas. Nao aparecem na tela.

Cada alerta registra o motivo exato:
  codigo    identificador do alerta
  mensagem  frase com os numeros reais e o limite usado
  valor     o numero que disparou o alerta
  limite    o limite comparado
  detalhe   o que causou (anuncios com endereco e link, erros, valores extremos)

Os limites abaixo sao um ponto de partida, para ajustar com o uso.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median, pstdev

from agents.identidade import numero as numero_endereco

# Limites (unico lugar).
LIMITE_POUCOS_COMPARAVEIS = 4          # 3 a 4 comparaveis: no limite do minimo de 3
LIMITE_PRECOS_ESPALHADOS = 0.40        # coeficiente de variacao do R$/m2 usado
LIMITE_DIFERENCA_AVALIACAO_CAIXA = 0.40  # valor de mercado vs avaliacao CAIXA
LIMITE_DECISAO_APERTADA = 0.05         # |sobra| em relacao ao valor minimo
LIMITE_AMOSTRA_CONCENTRADA = 0.30      # parcela das casas com a mesma area ou o mesmo preco
MIN_AMOSTRA_CONCENTRADA = 6            # abaixo disso, coincidencias sao normais
LIMITE_TERRENO_M2_FORA = 4             # R$/m2 abaixo de mediana/4 ou acima de mediana*4
LIMITE_TERRENO_AREA_FORA = 10          # area acima de 10x a mediana (gleba)


def _brl(valor) -> str:
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


def _anuncio(c: dict) -> dict:
    """Identificacao de um comparavel no detalhe do alerta."""
    return {
        "endereco": c.get("rua") or None,
        "bairro": c.get("bairro") or None,
        "preco": c.get("preco"),
        "area": c.get("area"),
        "portal": c.get("portal") or None,
        "status_zona": c.get("status_zona"),
        "link": c.get("url") or None,
    }


def _alerta(codigo: str, mensagem: str, valor=None, limite=None, detalhe=None) -> dict:
    return {"codigo": codigo, "mensagem": mensagem, "valor": valor, "limite": limite, "detalhe": detalhe}


def calcular_alertas(execucao: dict, resultado_ag5: dict | None, falhas: list | None = None) -> list[dict]:
    """Lista de alertas da avaliacao (vazia quando nada chama atencao)."""
    ag5 = resultado_ag5 or {}
    alertas = []
    estimativa_ok = execucao.get("status_agente5") == "ok"
    usados = ag5.get("comparaveis_usados") or {}
    usados_todos = (usados.get("construcao") or []) + (usados.get("terreno") or [])

    # 1. Poucos comparaveis (so faz sentido com estimativa; com menos de 3 o status
    #    ja e amostra_insuficiente e a decisao e "Sem estimativa").
    if estimativa_ok:
        n_construcao = execucao.get("qtd_comparaveis_construcao") or 0
        if 0 < n_construcao <= LIMITE_POUCOS_COMPARAVEIS:
            alertas.append(_alerta(
                "poucos_comparaveis",
                f"Só {n_construcao} comparáveis de construção entraram no cálculo "
                f"(alerta até {LIMITE_POUCOS_COMPARAVEIS}; mínimo exigido: 3). Um anúncio a mais "
                f"ou a menos muda bastante o valor.",
                n_construcao, LIMITE_POUCOS_COMPARAVEIS,
                [_anuncio(c) for c in usados.get("construcao") or []],
            ))
        separa_terreno = bool((ag5.get("calculo_terreno") or {}).get("aplicado"))
        n_terreno = execucao.get("qtd_terrenos") or 0
        if separa_terreno and 0 < n_terreno <= LIMITE_POUCOS_COMPARAVEIS:
            alertas.append(_alerta(
                "poucos_terrenos",
                f"Só {n_terreno} terrenos entraram no cálculo do m² do terreno "
                f"(alerta até {LIMITE_POUCOS_COMPARAVEIS}).",
                n_terreno, LIMITE_POUCOS_COMPARAVEIS,
                [_anuncio(c) for c in usados.get("terreno") or []],
            ))

    # 2. Comparaveis fora da zona confirmada (fallback ou sem validacao de distancia).
    fora = [c for c in usados_todos if c.get("status_zona") in ("fallback", "sem_validacao")]
    n_fora = len(fora) or (execucao.get("usados_por_fallback") or 0)
    if n_fora:
        sem_validacao = sum(1 for c in fora if c.get("status_zona") == "sem_validacao")
        motivo = (
            "sem verificação de distância (o endereço do imóvel não foi localizado no mapa)"
            if sem_validacao and sem_validacao == len(fora) else
            "anexados por fallback (menos de 3 confirmados dentro do raio da zona)"
        )
        alertas.append(_alerta(
            "fora_da_zona",
            f"{n_fora} de {len(usados_todos) or '?'} comparáveis do cálculo não foram confirmados "
            f"na zona homogênea: {motivo}.",
            n_fora, 0, [_anuncio(c) for c in fora],
        ))

    # 3. Precos espalhados: coeficiente de variacao do R$/m2 de construcao usado
    #    (um valor por comparavel; ja sem os descartados pela faixa de sanidade).
    valores_m2 = [v for v in (ag5.get("auditoria") or {}).get("m2_construcao_min_terreno") or [] if v and v > 0]
    if estimativa_ok and len(valores_m2) >= 3:
        media = mean(valores_m2)
        cv = pstdev(valores_m2) / media
        if cv > LIMITE_PRECOS_ESPALHADOS:
            alertas.append(_alerta(
                "precos_espalhados",
                f"O R$/m² dos comparáveis vai de {_brl(min(valores_m2))} a {_brl(max(valores_m2))} "
                f"(média {_brl(media)}); variação de {cv:.0%}, acima do limite de "
                f"{LIMITE_PRECOS_ESPALHADOS:.0%}.",
                round(cv, 3), LIMITE_PRECOS_ESPALHADOS,
                {"menor_m2": round(min(valores_m2), 2), "maior_m2": round(max(valores_m2), 2),
                 "media_m2": round(media, 2), "quantidade": len(valores_m2)},
            ))

    # 4. Valor de mercado muito diferente do valor de avaliacao CAIXA (se informado).
    mercado, avaliacao = execucao.get("valor_mercado"), execucao.get("valor_avaliacao")
    if estimativa_ok and mercado and avaliacao:
        diferenca = (mercado - avaliacao) / avaliacao
        if abs(diferenca) > LIMITE_DIFERENCA_AVALIACAO_CAIXA:
            alertas.append(_alerta(
                "diferente_avaliacao_caixa",
                f"Valor de mercado {_brl(mercado)} está {abs(diferenca):.0%} "
                f"{'acima' if diferenca > 0 else 'abaixo'} do valor de avaliação CAIXA "
                f"({_brl(avaliacao)}); limite: {LIMITE_DIFERENCA_AVALIACAO_CAIXA:.0%}.",
                round(diferenca, 3), LIMITE_DIFERENCA_AVALIACAO_CAIXA,
                {"valor_mercado": mercado, "valor_avaliacao_caixa": avaliacao},
            ))

    # 5. Decisao apertada: sobra ou falta pequena em relacao ao valor minimo.
    sobra, minimo = execucao.get("sobra"), execucao.get("valor_minimo")
    if sobra is not None and minimo:
        relativo = abs(sobra) / minimo
        if relativo < LIMITE_DECISAO_APERTADA:
            alertas.append(_alerta(
                "decisao_apertada",
                f"{'Sobra' if sobra >= 0 else 'Falta'} de {_brl(abs(sobra))}, só {relativo:.1%} do "
                f"valor mínimo ({_brl(minimo)}); limite: {LIMITE_DECISAO_APERTADA:.0%}. A decisão "
                f"pode mudar em outra execução.",
                round(relativo, 4), LIMITE_DECISAO_APERTADA,
                {"lance_maximo": execucao.get("lance_maximo"), "valor_minimo": minimo, "sobra": sobra},
            ))

    # 6. Possivel anuncio do proprio imovel dentro da media.
    possiveis = [c for c in usados_todos if c.get("possivel_anuncio_do_alvo")]
    if possiveis:
        alertas.append(_alerta(
            "possivel_alvo_no_calculo",
            f"{len(possiveis)} anúncio(s) com perfil do próprio imóvel (mesmo bairro e área, preço "
            f"ou cômodos parecidos, ou mesmo prédio) entraram no cálculo.",
            len(possiveis), 0, [_anuncio(c) for c in possiveis],
        ))

    # 7. Falha de algum agente nesta avaliacao.
    if falhas:
        agentes = sorted({str(f).split(":", 1)[0] for f in falhas})
        alertas.append(_alerta(
            "falha_de_agente",
            f"Falha em: {', '.join(agentes)}. A nota de qualidade, a infraestrutura ou o tempo "
            f"de venda podem estar incompletos.",
            len(falhas), 0, list(falhas),
        ))

    # 8. Amostra concentrada: muitas casas com exatamente a mesma area ou o mesmo
    #    preco costumam ser um mesmo empreendimento (casas novas iguais), que pode
    #    nao representar o imovel avaliado.
    construcao = usados.get("construcao") or []
    if len(construcao) >= MIN_AMOSTRA_CONCENTRADA:
        eh_apto = "apart" in str(execucao.get("tipo") or "").lower()
        exemplo = "unidades iguais do mesmo prédio ou lançamento" if eh_apto else "casas novas iguais"
        for campo, nome, fmt in (("area", "a mesma área", lambda v: f"{v:g} m²"), ("preco", "o mesmo preço", _brl)):
            valores = [round(float(c[campo])) for c in construcao if c.get(campo)]
            if not valores:
                continue
            valor, qtd = Counter(valores).most_common(1)[0]
            parcela = qtd / len(construcao)
            if qtd >= 3 and parcela >= LIMITE_AMOSTRA_CONCENTRADA:
                iguais = [c for c in construcao if c.get(campo) and round(float(c[campo])) == valor]
                alertas.append(_alerta(
                    "amostra_concentrada",
                    f"{qtd} de {len(construcao)} comparáveis ({parcela:.0%}) têm exatamente {nome} "
                    f"({fmt(valor)}); limite: {LIMITE_AMOSTRA_CONCENTRADA:.0%}. Pode ser um mesmo "
                    f"empreendimento dominando a amostra (ex.: {exemplo}), diferente do imóvel avaliado.",
                    round(parcela, 3), LIMITE_AMOSTRA_CONCENTRADA,
                    {"campo": campo, "valor": valor, "quantidade": qtd, "total": len(construcao),
                     "anuncios": [_anuncio(c) for c in iguais]},
                ))

    # 9. Terrenos fora do padrao: R$/m2 muito abaixo/acima da mediana (provavel preco
    #    digitado errado) ou area de gleba. A media sem extremos absorve, mas o
    #    cenario conservador usa o MENOR R$/m2 do terreno.
    terrenos = [c for c in usados.get("terreno") or [] if c.get("preco") and c.get("area")]
    if len(terrenos) >= 3:
        m2 = [float(c["preco"]) / float(c["area"]) for c in terrenos]
        med_m2 = median(m2)
        med_area = median(float(c["area"]) for c in terrenos)
        fora_padrao = []
        for c, v in zip(terrenos, m2):
            motivos = []
            if v < med_m2 / LIMITE_TERRENO_M2_FORA:
                motivos.append(f"R$/m² {_brl(v)}, muito abaixo da mediana")
            elif v > med_m2 * LIMITE_TERRENO_M2_FORA:
                motivos.append(f"R$/m² {_brl(v)}, muito acima da mediana")
            if float(c["area"]) > med_area * LIMITE_TERRENO_AREA_FORA:
                motivos.append(f"área de {float(c['area']):,.0f} m²".replace(",", ".") + ", muito maior que a mediana")
            if motivos:
                fora_padrao.append({**_anuncio(c), "valor_m2": round(v, 2), "motivo": "; ".join(motivos)})
        if fora_padrao:
            menor_vem_daqui = min(m2) < med_m2 / LIMITE_TERRENO_M2_FORA
            alertas.append(_alerta(
                "terreno_fora_do_padrao",
                f"{len(fora_padrao)} de {len(terrenos)} terrenos estão fora do padrão (R$/m² abaixo de "
                f"1/{LIMITE_TERRENO_M2_FORA} ou acima de {LIMITE_TERRENO_M2_FORA}x a mediana de "
                f"{_brl(med_m2)}, ou área acima de {LIMITE_TERRENO_AREA_FORA}x a mediana). "
                + ("O cenário conservador usa o menor R$/m², que vem desses anúncios: não é confiável."
                   if menor_vem_daqui else "A média sem extremos tende a absorver."),
                len(fora_padrao), 0,
                {"mediana_m2": round(med_m2, 2), "mediana_area": round(med_area, 2), "anuncios": fora_padrao},
            ))

    # 10. Possiveis repetidos que ficaram no calculo: mesmo preco, mesma area e mesmo
    #     numero de endereco, mas sem prova para juntar (ex.: varias casas iguais num
    #     mesmo loteamento, anunciadas por imobiliarias diferentes).
    grupos_rep = defaultdict(list)
    for tipo_lista in ("construcao", "terreno"):
        for c in usados.get(tipo_lista) or []:
            num = numero_endereco({"rua": c.get("rua")})
            if num and c.get("preco") and c.get("area"):
                grupos_rep[(tipo_lista, num, round(float(c["preco"])), round(float(c["area"])))].append(c)
    repetidos = [g for g in grupos_rep.values() if len(g) >= 2]
    if repetidos:
        n_anuncios = sum(len(g) for g in repetidos)
        alertas.append(_alerta(
            "possivel_repetido_no_calculo",
            f"{n_anuncios} anúncios em {len(repetidos)} grupo(s) têm o mesmo preço, a mesma área e o "
            f"mesmo número de endereço e continuam no cálculo. Podem ser o mesmo imóvel (sem prova "
            f"para descartar) ou casas iguais de um mesmo loteamento.",
            n_anuncios, 0,
            [{"preco": k[2], "area": k[3], "numero": k[1], "anuncios": [_anuncio(c) for c in g]}
             for k, g in grupos_rep.items() if len(g) >= 2],
        ))

    return alertas
