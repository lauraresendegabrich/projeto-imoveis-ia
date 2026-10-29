"""
Textos da tela de resultado (e do laudo) montados a partir do resultado da avaliacao:
plural das contagens, contagem da zona com o anuncio do proprio imovel, motivo exato
de nao ter valor e o que fazer. Nao muda nenhum calculo: so le o que os agentes gravam.
"""
from __future__ import annotations

from agents.price_liquidity import MIN_AMOSTRAS_CONFIAVEL

TIPOS_TERRENO = ("terrenos", "terreno", "lote", "residential_allotment_land", "allotment_land")

# A imobiliaria mais proxima so aparece (tela e laudo) ate esta distancia do imovel.
# O Agente 4 procura num raio maior (RAIO_IMOBILIARIA); acima disso ela nao e mostrada.
DISTANCIA_MAX_IMOBILIARIA_M = 3000


def contagem(n, singular: str, plural: str) -> str:
    """'1 imóvel', '3 imóveis'."""
    return f"{n} {singular if n == 1 else plural}"


def eh_terreno(c: dict) -> bool:
    return (c.get("propertyType", "") or "").lower() in TIPOS_TERRENO


def _urls_do_alvo(resultado: dict) -> set:
    return {
        c.get("url") for c in (resultado.get("comparaveis") or []) + (resultado.get("terrenos") or [])
        if c.get("eh_anuncio_do_alvo") and c.get("url")
    }


def anuncios_do_alvo_na_zona(resultado: dict, confirmados: list) -> int:
    """Quantos comparaveis da zona sao o anuncio do proprio imovel (saem do calculo)."""
    urls = _urls_do_alvo(resultado)
    return sum(1 for c in confirmados if c.get("eh_anuncio_do_alvo") or (c.get("url") and c.get("url") in urls))


def nota_anuncio_do_alvo(n_alvo: int) -> str:
    """' (1 é o anúncio do próprio imóvel e saiu do cálculo)' ou ''."""
    if n_alvo == 1:
        return " (1 é o anúncio do próprio imóvel e saiu do cálculo)"
    if n_alvo > 1:
        return f" ({n_alvo} são anúncios do próprio imóvel e saíram do cálculo)"
    return ""


def texto_comparaveis_na_zona(n: int, n_alvo: int) -> str:
    """'5 comparáveis na zona (1 é o anúncio do próprio imóvel e saiu do cálculo)'."""
    return f"{contagem(n, 'comparável', 'comparáveis')} na zona" + nota_anuncio_do_alvo(n_alvo)


def anuncios_do_proprio_imovel(resultado: dict) -> tuple[list[str], list[str]]:
    """
    (excluidos, suspeitos): links dos anuncios do proprio imovel que sairam do calculo
    (identidade confirmada) e dos possiveis que continuam no calculo.
    """
    # Os marcados pela pessoa na tela tem aviso proprio (marcados_pela_usuaria).
    excluidos = list(dict.fromkeys(
        c.get("url") or "" for c in (resultado.get("comparaveis") or []) + (resultado.get("terrenos") or [])
        if c.get("eh_anuncio_do_alvo") and not c.get("anuncio_do_alvo_pela_usuaria")
    ))
    usados = ((resultado.get("preco_estimado") or {}).get("comparaveis_usados") or {})
    suspeitos = list(dict.fromkeys(
        u.get("url") or "" for lista in usados.values() for u in lista or []
        if u.get("possivel_anuncio_do_alvo") and not u.get("eh_anuncio_do_alvo")
    ))
    return excluidos, suspeitos


def _reais_txt(v) -> str:
    return f"R$ {float(v):,.0f}".replace(",", ".")


def motivo_parecido_com_o_alvo(alvo: dict, comp: dict) -> str:
    """
    Por que um anuncio parece o do proprio imovel, em uma linha:
    "mesma rua, mesma área (182 m²), mesmos quartos, banheiros e vagas; preço R$ 700.000".
    """
    from agents import identidade
    iguais = []
    rua_a, rua_c = identidade.rua(alvo), identidade.rua(comp)
    if rua_a and rua_c and identidade._nomes_parecidos(rua_a, rua_c):
        iguais.append("mesma rua")
    area_c = identidade._num(identidade.area(comp))
    area_dif = identidade.dif_relativa(identidade.area(alvo), area_c)
    if area_c:
        iguais.append(f"mesma área ({area_c:g} m²)" if area_dif is not None and area_dif <= 0.02
                      else f"área de {area_c:g} m²")
    comodos = []
    for nome, campos in (("quartos", ("quartos", "bedrooms")), ("banheiros", ("banheiros", "bathrooms")),
                         ("vagas", ("vagas", "parkingSpaces"))):
        va, vc = identidade._num(identidade._campo(alvo, *campos)), identidade._num(identidade._campo(comp, *campos))
        if va is not None and vc is not None and int(va) == int(vc):
            comodos.append(nome)
    if comodos:
        texto = comodos[0] if len(comodos) == 1 else ", ".join(comodos[:-1]) + " e " + comodos[-1]
        iguais.append(("mesmas " if comodos[0] == "vagas" else "mesmos ") + texto)
    preco_c = identidade._num(identidade.preco(comp))
    linha = ", ".join(iguais)
    if preco_c:
        linha += ("; " if linha else "") + f"preço {_reais_txt(preco_c)}"
    return linha


def suspeitos_do_proprio_imovel(resultado: dict, alvo: dict | None = None) -> list[dict]:
    """
    Possiveis anuncios do proprio imovel que continuam no calculo:
    [{"url", "provavel", "motivo"}], os provaveis primeiro.
    """
    alvo = alvo or resultado.get("imovel_alvo") or {}
    por_url = {c.get("url"): c for c in (resultado.get("comparaveis") or []) + (resultado.get("terrenos") or [])
               if c.get("url")}
    usados = ((resultado.get("preco_estimado") or {}).get("comparaveis_usados") or {})
    saida, vistos = [], set()
    for u in (u for lista in usados.values() for u in lista or []):
        url = u.get("url") or ""
        if not u.get("possivel_anuncio_do_alvo") or u.get("eh_anuncio_do_alvo") or url in vistos:
            continue
        vistos.add(url)
        comp = por_url.get(url) or u
        saida.append({
            "url": url,
            "provavel": bool(u.get("provavel_anuncio_do_alvo") or comp.get("provavel_anuncio_do_alvo")),
            "motivo": motivo_parecido_com_o_alvo(alvo, comp),
        })
    return sorted(saida, key=lambda s: not s["provavel"])


def marcados_pela_usuaria(resultado: dict, alvo: dict | None = None) -> list[dict]:
    """
    Anuncios que a pessoa disse, na tela, que sao do proprio imovel (sairam do calculo):
    [{"url", "motivo"}]. O motivo continua aparecendo (decisao da usuaria, 29/10/2026).
    """
    alvo = alvo or resultado.get("imovel_alvo") or {}
    urls = (resultado.get("preco_estimado") or {}).get("anuncios_do_alvo_pela_usuaria") or []
    por_url = {c.get("url"): c for c in (resultado.get("comparaveis") or []) + (resultado.get("terrenos") or [])
               if c.get("url")}
    return [{"url": u, "motivo": motivo_parecido_com_o_alvo(alvo, por_url.get(u) or {})} for u in urls]


def _metros(v) -> str:
    return f"{int(v):,}".replace(",", ".")


def _m2(valor: float) -> str:
    """35,88 / 100 / 1.000 (m², sem casas decimais quando inteiro)."""
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto[:-3] if texto.endswith(",00") else texto


def motivo_areas_diferentes(resultado: dict, nome: str, nomes: str) -> str | None:
    """
    Nenhum imovel construido passou na comparacao do Agente 2 e todos sairam pela area
    (pre-classificacao, sem IA): diz as areas encontradas. Ex.: imovel de 35,88 m² numa
    cidade onde as casas a venda tem de 100 a 1.000 m². None em qualquer outro caso.
    """
    resumo = (resultado or {}).get("resumo") or {}
    pre = resumo.get("pre_classificacao") or {}
    area_alvo = (pre.get("referencia_alvo") or {}).get("area_construida")
    limite = pre.get("regra_area_percentual")
    if resumo.get("cluster_a") or not area_alvo or not limite:
        return None
    reprovados = [c for c in (resultado.get("comparaveis") or [])
                  if c.get("status_julgamento") == "REPROVADO_PRE_CLASSIFICACAO"]
    areas = []
    for c in reprovados:
        ac = (c.get("pre_classificacao") or {}).get("area_construida") or {}
        if ac.get("candidato") is None or (ac.get("diferenca_percentual") or 0) <= (ac.get("limite_percentual") or limite):
            return None   # saiu por outro motivo (terreno, caracteristica): nao e so a area
        areas.append(float(ac["candidato"]))
    if not areas or len(areas) != pre.get("total_construidos"):
        return None
    lo, hi = area_alvo * (1 - limite / 100), area_alvo * (1 + limite / 100)
    faixa = f"de {_m2(min(areas))} a {_m2(max(areas))} m²" if min(areas) != max(areas) else f"{_m2(areas[0])} m²"
    feminino = nome == "casa"
    if len(areas) == 1:
        quem = f"{'A única' if feminino else 'O único'} {nome} à venda na região tem {faixa}"
    else:
        quem = (f"{'Nenhuma das' if feminino else 'Nenhum dos'} {len(areas)} {nomes} à venda na região tem área "
                f"parecida: {'elas' if feminino else 'eles'} têm {faixa}")
    return (f"{quem}, e o imóvel tem {_m2(area_alvo)} m² (o cálculo aceita de {_m2(round(lo))} a "
            f"{_m2(round(hi))} m², até {limite}% de diferença).")


def motivo_sem_valor(resultado: dict, imovel_alvo: dict | None = None) -> dict:
    """
    Motivo exato de a avaliacao nao ter valor confiavel e o que da para fazer:
    {"motivo": str, "fazer": [str]}. Ex.: "Faltou 1 casa para o mínimo de 5."
    """
    resultado = resultado or {}
    imovel_alvo = imovel_alvo or {}
    preco = resultado.get("preco_estimado") or {}
    status = preco.get("status_avaliacao", "ok")
    usados = preco.get("comparaveis_usados") or {}
    n_constr = len(usados.get("construcao") or [])
    zona = resultado.get("zona_homogenea") or {}
    confirmados = zona.get("comparaveis_confirmados") or []
    n_alvo = anuncios_do_alvo_na_zona(resultado, confirmados) or len(anuncios_do_proprio_imovel(resultado)[0])
    eh_casa = str(imovel_alvo.get("tipo") or "").lower() in ("house", "casa")
    nome, nomes = ("casa", "casas") if eh_casa else ("apartamento", "apartamentos")
    minimo = MIN_AMOSTRAS_CONFIAVEL

    if not preco.get("zona_calculada_nesta_avaliacao", True):
        motivo = ("A zona homogênea (quais anúncios estão perto do imóvel) não foi calculada nesta "
                  "avaliação, e sem ela o valor não é estimado.")
        return {"motivo": motivo, "fazer": ["Avalie o imóvel de novo."]}

    if status == "amostra_insuficiente" and n_constr < minimo:
        falta = minimo - n_constr
        parecidos = ("parecida", "parecidas") if eh_casa else ("parecido", "parecidos")
        motivo = (f"{'Faltou' if falta == 1 else 'Faltaram'} {contagem(falta, nome, nomes)} para o mínimo "
                  f"de {minimo}: só {contagem(n_constr, f'{nome} {parecidos[0]}', f'{nomes} {parecidos[1]}')} "
                  f"perto do imóvel {'entrou' if n_constr == 1 else 'entraram'} no cálculo.")
        if n_constr == 0:
            motivo = motivo_areas_diferentes(resultado, nome, nomes) or (
                f"Faltaram {minimo} {nomes} para o mínimo de {minimo}: "
                f"{'nenhuma' if eh_casa else 'nenhum'} perto do imóvel entrou no cálculo.")
    elif status == "amostra_insuficiente":
        motivo = next((a for a in preco.get("avisos") or [] if a.startswith("Amostra insuficiente")),
                      "Amostra insuficiente para uma estimativa confiável.")
    elif status == "sem_amostra":
        cluster_a = (resultado.get("resumo") or {}).get("cluster_a")
        if not cluster_a:
            motivo = motivo_areas_diferentes(resultado, nome, nomes) or (
                f"Nenhum anúncio parecido com o imóvel foi encontrado na busca (mínimo de {minimo}).")
        else:
            motivo = (f"Nenhum dos {contagem(cluster_a, 'anúncio parecido', 'anúncios parecidos')} ficou perto do "
                      f"imóvel (na zona homogênea); o mínimo é {minimo}.")
            if cluster_a == 1:
                motivo = f"O único anúncio parecido não ficou perto do imóvel (na zona homogênea); o mínimo é {minimo}."
    elif status == "valor_nao_estimado":
        motivo = "O cálculo deu valor zero."
    else:
        motivo = "Os dados disponíveis não permitiram um cálculo consistente."

    if n_alvo and status in ("amostra_insuficiente", "sem_amostra"):
        motivo += (" O anúncio do próprio imóvel saiu do cálculo." if n_alvo == 1 else
                   f" {n_alvo} anúncios do próprio imóvel saíram do cálculo.")

    fazer = []
    if status == "valor_nao_estimado" or (status in ("amostra_insuficiente", "sem_amostra") and n_constr == 0
                                          and motivo_areas_diferentes(resultado, nome, nomes)):
        fazer.append("Confira a área construída informada.")
    amp = zona.get("ampliacao_raio") or {}
    raio_final = zona.get("raio_final_m")
    if amp.get("ampliado") and raio_final:
        limite = amp.get("limite_m", 1500)
        fazer.append(f"O raio já foi ampliado até {_metros(raio_final)} m"
                     + (" (o máximo)." if raio_final >= limite else "."))
    escopo = next((c.get("escopo_busca") for c in resultado.get("comparaveis") or [] if c.get("escopo_busca")), None)
    if escopo == "cidade":
        fazer.append("A busca já incluiu a cidade toda.")
    if eh_casa and not imovel_alvo.get("area_terreno"):
        fazer.append("Informe a área do terreno: sem ela o cálculo usa só o m² total das casas e fica menos preciso.")
    return {"motivo": motivo, "fazer": fazer}


def motivo_terreno_fora(preco: dict) -> str:
    """Por que o terreno nao entrou no calculo do Agente 5 (passo a passo da tela)."""
    from agents.price_liquidity import TIPOS_CONDOMINIAIS, normalizar_tipo
    preco = preco or {}
    alvo = preco.get("imovel_alvo") or {}
    if normalizar_tipo(alvo.get("tipo") or "") in TIPOS_CONDOMINIAIS:
        return "o imóvel é apartamento, e o terreno não entra no cálculo"
    if not alvo.get("area_terreno_m2"):
        return "terreno do imóvel não informado"
    n = ((preco.get("valor_m2_zona_homogenea") or {}).get("terreno") or {}).get("quantidade_amostras", 0)
    if preco.get("aviso_terreno") or 0 < n < MIN_AMOSTRAS_CONFIAVEL:
        return f"só {contagem(n, 'terreno', 'terrenos')} à venda na região (mínimo de {MIN_AMOSTRAS_CONFIAVEL})"
    return "não há terrenos comparáveis na zona"


def imobiliaria_proxima(infra: dict) -> dict | None:
    """A imobiliaria do Agente 4, so se estiver a ate DISTANCIA_MAX_IMOBILIARIA_M.
    Sem distancia conhecida tambem fica de fora (nao da para garantir os 3 km)."""
    imob = (infra or {}).get("imobiliaria_proxima") or {}
    if not imob.get("encontrada"):
        return None
    try:
        dist = float(imob.get("distancia_metros"))
    except (TypeError, ValueError):
        return None
    return imob if dist <= DISTANCIA_MAX_IMOBILIARIA_M else None


def texto_sem_imobiliaria() -> str:
    """'Nenhuma imobiliária encontrada a até 3 km'."""
    km = DISTANCIA_MAX_IMOBILIARIA_M / 1000
    return f"Nenhuma imobiliária encontrada a até {km:g} km".replace(".", ",")


def linhas_laudo_imobiliaria(infra: dict) -> list[str]:
    """Linhas do bloco 'Imobiliária mais próxima' no laudo TXT."""
    imob = imobiliaria_proxima(infra)
    if not imob:
        return [texto_sem_imobiliaria() + "."]
    linhas = [imob.get("nome") or "?"]
    for rotulo, campo in (("Telefone", "telefone"), ("E-mail", "email"), ("Site", "website"),
                          ("Horário", "opening_hours")):
        if imob.get(campo):
            linhas.append(f"{rotulo}: {imob[campo]}")
    endereco = imob.get("endereco") or "endereço não informado"
    linhas.append(f"Endereço: {endereco} ({_metros(float(imob['distancia_metros']))} m do imóvel)")
    return linhas


def linhas_referencia(resultado: dict) -> list[dict]:
    """Comparaveis validos (sem valor confiavel) para mostrar como referencia."""
    usados = ((resultado.get("preco_estimado") or {}).get("comparaveis_usados") or {})
    linhas = []
    for u in usados.get("construcao") or []:
        try:
            preco, area = float(u.get("preco") or 0), float(u.get("area") or 0)
        except (TypeError, ValueError):
            continue
        if preco <= 0 or area <= 0:
            continue
        linhas.append({"preco": preco, "area": area, "m2": preco / area, "url": u.get("url") or "",
                       "rua": u.get("rua") or "", "bairro": u.get("bairro") or ""})
    return sorted(linhas, key=lambda l: l["m2"])
