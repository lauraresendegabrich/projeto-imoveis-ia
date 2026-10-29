"""
Alertas automaticos de cada avaliacao
=====================================

Regras simples (sem IA e sem mudar nenhum calculo) que apontam avaliacoes que
merecem atencao: poucos comparaveis, comparaveis fora da zona, precos espalhados,
divergencia com o valor de avaliacao CAIXA, decisao apertada, possivel anuncio do
proprio imovel no calculo, falha de agente, amostra concentrada num mesmo
empreendimento, terrenos fora do padrao, possiveis repetidos que ficaram no calculo
e mesmo imovel com areas diferentes entre portais.

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

from agents.comparables import MIN_CONFIRMADOS_ZONA
from agents.identidade import numero as numero_endereco
from agents.price_liquidity import MIN_AMOSTRAS_CONFIAVEL

# Limites (unico lugar).
LIMITE_POUCOS_COMPARAVEIS = 6          # 5 a 6 comparaveis: no limite do minimo de 5
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

    # 1. Poucos comparaveis (so faz sentido com estimativa; abaixo do minimo o status
    #    ja e amostra_insuficiente e a decisao e "Sem estimativa").
    if estimativa_ok:
        n_construcao = execucao.get("qtd_comparaveis_construcao") or 0
        if 0 < n_construcao <= LIMITE_POUCOS_COMPARAVEIS:
            alertas.append(_alerta(
                "poucos_comparaveis",
                f"Só {n_construcao} comparáveis de construção entraram no cálculo "
                f"(alerta até {LIMITE_POUCOS_COMPARAVEIS}; mínimo exigido: {MIN_AMOSTRAS_CONFIAVEL}). Um anúncio a mais "
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

    # 2. Comparaveis com a distancia nao verificada (fallback ou sem validacao). Nao
    #    estao comprovadamente longe: so nao foi possivel medir. Contam para o minimo.
    fora = [c for c in usados_todos if c.get("status_zona") in ("fallback", "sem_validacao")]
    n_fora = len(fora) or (execucao.get("usados_por_fallback") or 0)
    if n_fora:
        sem_validacao = sum(1 for c in fora if c.get("status_zona") == "sem_validacao")
        motivo = (
            "usados sem verificação de distância (nenhum comparável confirmado dentro da zona, "
            "ou endereço do imóvel não localizado no mapa)"
            if sem_validacao and sem_validacao == len(fora) else
            f"sem localização exata no anúncio, completaram a amostra porque havia menos de "
            f"{MIN_CONFIRMADOS_ZONA} confirmados dentro do raio da zona"
        )
        alertas.append(_alerta(
            "fora_da_zona",
            f"{n_fora} de {len(usados_todos) or '?'} comparáveis do cálculo estão com a distância "
            f"não verificada (podem estar perto ou longe; contam para o mínimo de "
            f"{MIN_CONFIRMADOS_ZONA}): {motivo}.",
            n_fora, 0, [_anuncio(c) for c in fora],
        ))

    # 2b. Fora da zona, no mesmo bairro ate 2,5 km (distancia medida): completaram a amostra.
    mesmo_bairro = [c for c in usados_todos if c.get("status_zona") == "mesmo_bairro"]
    if mesmo_bairro:
        alertas.append(_alerta(
            "mesmo_bairro_fora_da_zona",
            f"{len(mesmo_bairro)} de {len(usados_todos)} comparáveis do cálculo estão fora da zona "
            f"homogênea, no mesmo bairro do imóvel, a até 2,5 km: entraram porque havia menos de "
            f"{MIN_CONFIRMADOS_ZONA} confirmados dentro do raio da zona.",
            len(mesmo_bairro), 0, [_anuncio(c) for c in mesmo_bairro],
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
            (f"1 anúncio com perfil do próprio imóvel (mesmo bairro e área, preço ou cômodos "
             f"parecidos, ou mesmo prédio) entrou no cálculo." if len(possiveis) == 1 else
             f"{len(possiveis)} anúncios com perfil do próprio imóvel (mesmo bairro e área, preço "
             f"ou cômodos parecidos, ou mesmo prédio) entraram no cálculo."),
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
                    # Mesmo texto na tela, no laudo e no Excel (a regra nao mudou).
                    f"Amostra concentrada: {qtd} dos {len(construcao)} imóveis usados no cálculo "
                    f"({parcela:.0%}) têm exatamente {nome}: {fmt(valor)}. Isso costuma indicar um "
                    f"mesmo empreendimento (casas novas iguais ou unidades de um lançamento) dominando "
                    f"a amostra. O valor fica puxado para o preço desse empreendimento, que pode ser "
                    f"diferente do imóvel avaliado. Confira os anúncios abaixo.",
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
            alertas.append(_alerta(
                "terreno_fora_do_padrao",
                # Mesmo texto na tela, no laudo e no Excel (a regra nao mudou).
                f"Terreno fora do padrão: {len(fora_padrao)} dos {len(terrenos)} terrenos usados no "
                f"cálculo têm preço por m² muito diferente dos outros (menos de 1/4 ou mais de 4 vezes "
                f"o valor típico de {_brl(med_m2)}/m²) ou área muito maior que a dos demais (gleba ou "
                f"fazenda). Pode ser preço digitado errado no anúncio ou um terreno de outro tipo. O "
                f"cálculo usa a média sem os extremos, o que costuma diminuir o efeito, mas confira "
                f"esses anúncios.",
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
            f"Possível repetido no cálculo: {n_anuncios} anúncios, em "
            f"{'1 grupo' if len(repetidos) == 1 else f'{len(repetidos)} grupos'}, têm o "
            f"mesmo preço, a mesma área e o mesmo número de endereço e continuam no cálculo. Podem "
            f"ser o mesmo imóvel anunciado mais de uma vez (sem prova suficiente para juntar) ou "
            f"casas iguais de um mesmo condomínio ou loteamento. Se forem o mesmo imóvel, ele está "
            f"pesando mais de uma vez na média. Confira os anúncios.",
            n_anuncios, 0,
            [{"preco": k[2], "area": k[3], "numero": k[1], "anuncios": [_anuncio(c) for c in g]}
             for k, g in grupos_rep.items() if len(g) >= 2],
        ))

    # 11. Mesmo imovel com areas diferentes entre portais (Ag1 juntou os anuncios):
    #     casa/apto ja usa a menor area; terreno mantem a do anuncio que ficou.
    divergentes = [c for c in usados_todos if c.get("areas_entre_portais")]
    if divergentes:
        detalhe = []
        for c in divergentes:
            areas_txt = " · ".join(
                f"{a.get('portal') or '?'} {a['area']:g} m²" for a in c["areas_entre_portais"]
            )
            usada = f"usada {float(c['area']):g} m²" if c.get("area") else ""
            detalhe.append({**_anuncio(c), "motivo": f"{areas_txt}; {usada}".strip("; "),
                            "areas_entre_portais": c["areas_entre_portais"]})
        alertas.append(_alerta(
            "area_diferente_entre_portais",
            (f"Área diferente entre portais: 1 imóvel usado no cálculo aparece "
             if len(divergentes) == 1 else
             f"Área diferente entre portais: {len(divergentes)} imóveis usados no cálculo aparecem ")
            + f"em mais de um portal com áreas diferentes (mais de 5%). Foi usada a menor área, porque "
            f"o erro mais comum é um portal mostrar a área do terreno no lugar da área construída. "
            f"Se a área certa for a maior, o valor do m² desse imóvel está mais alto do que deveria. "
            f"Confira os anúncios.",
            len(divergentes), 0.05, detalhe,
        ))

    # 12. Provavel lancamento: varios anuncios iguais de imobiliarias diferentes que o
    #     Agente 1 juntou como 1 imovel (a regra de repetidos nao muda).
    lancamentos = [c for c in usados.get("construcao") or [] if c.get("provavel_lancamento")]
    if lancamentos:
        alertas.append(_alerta(
            "provavel_lancamento",
            " ".join(
                f"{c['provavel_lancamento']['anuncios']} anúncios iguais (mesmo preço e área, "
                f"imobiliárias diferentes; provável lançamento) foram contados como 1 imóvel."
                for c in lancamentos
            ),
            sum(c["provavel_lancamento"]["anuncios"] for c in lancamentos), 5,
            [{**_anuncio(c), "motivo": f"{c['provavel_lancamento']['anuncios']} anúncios de "
                                       f"{c['provavel_lancamento']['imobiliarias']} imobiliárias"}
             for c in lancamentos],
        ))

    # 13. Mesma casa (rua, numero, area, quartos) anunciada por imobiliarias diferentes
    #     com precos diferentes: o Agente 1 juntou e usou a mediana dos precos.
    juntadas = [c for c in usados_todos if c.get("precos_entre_imobiliarias")]
    if juntadas:
        frases, detalhe = [], []
        for c in juntadas:
            precos = [p["preco"] for p in c["precos_entre_imobiliarias"] if p.get("preco")]
            area_txt = f" ({float(c['area']):g} m²)" if c.get("area") else ""
            frases.append(
                f"A casa da {c.get('rua') or 'mesma rua e número'}{area_txt} aparece em "
                f"{len(c['precos_entre_imobiliarias'])} anúncios de imobiliárias diferentes, com preços "
                f"de {_brl(min(precos))} a {_brl(max(precos))}. Contou como 1 imóvel, com o preço do "
                f"meio (mediana): {_brl(float(c.get('preco') or 0))}."
            )
            for p in c["precos_entre_imobiliarias"]:
                detalhe.append({**_anuncio(c), "preco": p.get("preco"), "portal": p.get("portal"),
                                "link": p.get("url"), "motivo": p.get("anunciante") or "-"})
        alertas.append(_alerta(
            "mesma_casa_precos_diferentes",
            "Mesma casa com preços diferentes: " + " ".join(frases),
            sum(len(c["precos_entre_imobiliarias"]) for c in juntadas), 0, detalhe,
        ))

    return alertas
