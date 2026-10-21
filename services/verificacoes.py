"""
Verificacoes automaticas ao final de cada avaliacao
==================================================

Conferem se cada agente funcionou como esperado. Nao mudam nenhum calculo: leem o
resultado de cada agente (o dict `resultado` que a interface monta) e conferem regras.

verificar_execucao(resultado) -> lista de
    {"agente", "verificacao", "esperado", "encontrado", "ok"}
ok: True (passou), False (falhou), "alerta" (pede conferencia, sem ser erro) ou None
(nao verificavel: o agente nao grava o dado).

Mostradas no modo conferencia (MOSTRAR_FUNIL), gravadas no banco (execucoes.verificacoes)
e na aba "Verificacoes" do Excel.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from statistics import mean

from agents import identidade
from agents.price_liquidity import (
    AREA_MINIMA_VALIDA, M2_CONSTRUCAO_MAX, M2_CONSTRUCAO_MIN, MIN_AMOSTRAS_CONFIAVEL, TIPOS_CONDOMINIAIS,
    TIPOS_TERRENO, converter_numero, normalizar_tipo,
)

FATOR_TOPOGRAFIA_ACENTUADA = 0.80   # mesma regra de calcular_valores_m2_terreno (Agente 5)
from app.funil import montar_funil, resumo_funil

LIMITE_AG3 = 10            # o Agente 3 analisa no maximo 10 comparaveis (MAX_COMPARAVEIS_AG3)
TOLERANCIA_REAIS = 1.0     # refazer a conta do Agente 5: diferenca maxima aceita
DESCONTO_LIQUIDEZ = 0.10
# Mesmos niveis de agents/collector.NIVEIS_GEO_PRECISOS, mais a coordenada informada.
NIVEIS_PRECISOS = {"endereco_completo", "rua_numero", "rua", "bairro", "coordenada_informada"}


def _v(agente, verificacao, esperado, encontrado, ok, problema=None) -> dict:
    """`problema`: o que deu errado em uma frase simples (para a tela), quando ok nao e True."""
    return {"agente": agente, "verificacao": verificacao, "esperado": esperado,
            "encontrado": encontrado, "ok": ok,
            "problema": problema if ok is False or ok == "alerta" else None}


def contagem_txt(n, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _norm(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().split())


def _reais(v) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _eh_terreno(c: dict) -> bool:
    return (c.get("cluster") == "terreno"
            or normalizar_tipo(c.get("propertyType") or c.get("tipo") or "") in TIPOS_TERRENO)


def _anuncios(resultado: dict) -> list[dict]:
    """Anuncios do Agente 2 (construidos e terrenos), sem repetir o mesmo objeto."""
    vistos, lista = set(), []
    for c in (resultado.get("comparaveis") or []) + (resultado.get("terrenos") or []):
        chave = c.get("url") or id(c)
        if chave not in vistos:
            vistos.add(chave)
            lista.append(c)
    return lista


def _usados(preco: dict) -> tuple[list, list]:
    u = preco.get("comparaveis_usados") or {}
    return list(u.get("construcao") or []), list(u.get("terreno") or [])


def _m2_terreno(t: dict) -> float | None:
    """
    R$/m2 de um terreno usado, pela mesma regra do Agente 5 (calcular_valores_m2_terreno):
    preco / area; com area invalida (ou sem preco), o preco/m2 do anuncio; topografia
    "acentuado" (aclive/declive) vale 80%.
    """
    preco, area = converter_numero(t.get("preco")), converter_numero(t.get("area"))
    if not preco or not area or area < AREA_MINIMA_VALIDA:
        return converter_numero(t.get("preco_m2_anuncio")) or None
    valor = preco / area
    if "acentuado" in str(t.get("topografia") or "").lower():
        valor *= FATOR_TOPOGRAFIA_ACENTUADA
    return valor


def _media_aparada(valores: list[float]) -> float:
    """TRIMMEAN(0,5) do Excel, escrito de novo aqui (independente do Agente 5)."""
    v = sorted(valores)
    n = len(v)
    cortar = int(n * 0.5)
    cortar -= cortar % 2
    while cortar >= n:
        cortar -= 2
    lado = max(cortar, 0) // 2
    return mean(v[lado:n - lado] if lado else v)


# =============================================================================
# GERAL
# =============================================================================
def _geral(resultado: dict) -> list[dict]:
    saida = []
    linhas = montar_funil(resultado)
    urls = Counter(l["Anúncio"] for l in linhas if l.get("Anúncio"))
    repetidos = [u for u, n in urls.items() if n > 1]
    anuncios = _anuncios(resultado)
    esperado = len(anuncios) + len(resultado.get("duplicatas_descartadas") or [])
    soma = sum(resumo_funil(linhas).values())
    saida.append(_v(
        "Geral", "Cada anúncio aparece em exatamente uma etapa do funil",
        f"{esperado} anúncios, cada um em uma etapa; soma das etapas = {esperado}",
        f"{len(linhas)} linhas; soma das etapas = {soma}; {len(repetidos)} em mais de uma etapa"
        + (f" ({', '.join(repetidos[:3])})" if repetidos else ""),
        not repetidos and soma == len(linhas) == esperado,
        "algum anúncio aparece em mais de uma etapa do funil, ou falta no funil",
    ))

    id_exec = resultado.get("id_execucao")
    if id_exec:
        outros, nomes = [], []
        for nome, chave in (("zona (Agente 2)", "zona_homogenea"), ("Agente 3", "analise_qualitativa"),
                            ("Agente 4", "infraestrutura"), ("Agente 5", "preco_estimado")):
            dados = resultado.get(chave) or {}
            if dados and dados.get("id_execucao") not in (None, id_exec):
                outros.append(f"{nome}: {dados.get('id_execucao')}")
                nomes.append(nome)
        saida.append(_v(
            "Geral", "Os resultados dos Agentes 2 a 5 são desta execução",
            f"id_execucao {id_exec} em todos", "; ".join(outros) or "todos com o id desta execução",
            not outros, f"usou dados de outra avaliação ({', '.join(nomes)})",
        ))
    return saida


# =============================================================================
# AGENTE 1
# =============================================================================
def _agente1(resultado: dict) -> list[dict]:
    alvo = resultado.get("imovel_alvo") or {}
    cidade, uf = _norm(alvo.get("cidade")), _norm(alvo.get("estado"))
    anuncios = _anuncios(resultado)
    outra_cidade, sem_cidade = [], 0
    for c in anuncios:
        cid = _norm(c.get("city") or c.get("cidade"))
        est = _norm(c.get("state") or c.get("estado"))
        if not cid:
            sem_cidade += 1
        elif (cidade and cid != cidade) or (uf and len(est) == 2 and est != uf):
            outra_cidade.append(f"{c.get('city') or c.get('cidade')}/{c.get('state') or c.get('estado') or '?'}")
    saida = [_v(
        "Agente 1", "Todos os anúncios são da cidade/UF pedidas",
        f"{alvo.get('cidade') or '?'}/{alvo.get('estado') or '?'}",
        (f"{len(outra_cidade)} de outra cidade ({', '.join(sorted(set(outra_cidade))[:3])})"
         if outra_cidade else f"todos da cidade pedida") + (f"; {sem_cidade} sem cidade no anúncio" if sem_cidade else ""),
        not outra_cidade if cidade else None,
        f"{contagem_txt(len(outra_cidade), 'anúncio é', 'anúncios são')} de outra cidade "
        f"({', '.join(sorted(set(outra_cidade))[:3])})",
    )]
    id_exec = resultado.get("id_execucao")
    de_outra = [c for c in anuncios if c.get("id_execucao") != id_exec]
    sem_horario = [c for c in anuncios if not c.get("coletado_em")]
    horarios = sorted({c.get("coletado_em") for c in anuncios if c.get("coletado_em")})
    saida.append(_v(
        "Agente 1", "Os dados são desta execução (id_execucao / horário)",
        f"id_execucao {id_exec} e horário da coleta em cada anúncio",
        f"{len(anuncios) - len(de_outra)} de {len(anuncios)} com o id desta execução"
        + (f" (outros: {', '.join(sorted({str(c.get('id_execucao')) for c in de_outra})[:3])})" if de_outra else "")
        + f"; {len(sem_horario)} sem horário"
        + (f"; coletados em {horarios[0]}" if len(horarios) == 1 else
           f"; coletados entre {horarios[0]} e {horarios[-1]}" if horarios else ""),
        bool(id_exec) and not de_outra and not sem_horario,
        f"{contagem_txt(len(de_outra), 'anúncio não é', 'anúncios não são')} desta avaliação" if de_outra
        else "faltou o horário da coleta em parte dos anúncios",
    ))
    saida.append(_fontes(resultado))
    saida.append(_contagem_coleta(resultado, anuncios))
    return saida


def _contagem_coleta(resultado: dict, anuncios: list) -> dict:
    """encontrados = mantidos + repetidos (com os cortados pelo limite por tipo)."""
    nome = "encontrados = mantidos + repetidos"
    esperado = ("encontrados = únicos + repetidos; únicos = mantidos + cortados pelo limite; "
                "mantidos e repetidos iguais aos do resultado")
    c = (resultado.get("resumo_coleta") or {}).get("contagem")
    n_rep_resultado = len(resultado.get("duplicatas_descartadas") or [])
    if not c:
        return _v("Agente 1", nome, esperado,
                  f"não verificável: coleta sem as contagens (mantidos {len(anuncios)}, repetidos {n_rep_resultado})", None)
    ok = (c["antes_dos_repetidos"] == c["unicos"] + c["repetidos_juntados"]
          and c["unicos"] == c["mantidos"] + c["cortados_pelo_limite"]
          and c["repetidos_juntados"] == c["repetidos"] + c["repetidos_dos_cortados"]
          and c["mantidos"] == len(anuncios) and c["repetidos"] == n_rep_resultado)
    encontrado = (
        f"encontrados {c['antes_dos_repetidos']} = {c['unicos']} únicos + {c['repetidos_juntados']} repetidos; "
        f"únicos {c['unicos']} = {c['mantidos']} mantidos + {c['cortados_pelo_limite']} cortados pelo limite "
        f"(com {c['repetidos_dos_cortados']} repetidos deles); no resultado: {len(anuncios)} anúncios e "
        f"{n_rep_resultado} repetidos"
    )
    return _v("Agente 1", nome, esperado, encontrado, ok,
              "a conta de anúncios encontrados, repetidos e mantidos não fecha")


def _fontes(resultado: dict) -> dict:
    """Cada fonte consultada respondeu, ou a falha esta registrada."""
    fontes = (resultado.get("resumo_coleta") or {}).get("fontes")
    nome = "Cada fonte consultada respondeu, ou a falha está registrada"
    esperado = "cada fonte consultada: respondeu, ou falhou com o erro registrado"
    if not fontes:
        return _v("Agente 1", nome, esperado, "não verificável: coleta sem o registro das fontes", None)
    partes, ok = [], True
    for fonte, s in fontes.items():
        rotulo = {"athena": "Athena", "apify": "Apify"}.get(fonte, fonte)
        erros = list(s.get("falhas") or []) + ([s["erro"]] if s.get("erro") else [])
        if not s.get("consultada"):
            partes.append(f"{rotulo}: {s.get('motivo') or 'não consultado'}")
            continue
        if s.get("respondeu"):
            partes.append(f"{rotulo}: respondeu ({s.get('anuncios', 0)} anúncios)"
                          + (f"; falhas registradas: {'; '.join(erros)}" if erros else ""))
        elif erros:
            partes.append(f"{rotulo}: falhou, registrado ({'; '.join(erros)})")
        else:
            ok = False
            partes.append(f"{rotulo}: não respondeu e nenhuma falha foi registrada")
    return _v("Agente 1", nome, esperado, " | ".join(partes), ok,
              "uma fonte de anúncios não respondeu e a falha não ficou registrada")


# =============================================================================
# AGENTE 2
# =============================================================================
def _agente2(resultado: dict) -> list[dict]:
    saida = []
    anuncios = _anuncios(resultado)
    casas = [c for c in anuncios if not _eh_terreno(c)]
    por_status = Counter(c.get("status_julgamento") for c in casas)
    modelos = Counter(f"{c.get('provider_llm') or '?'}/{c.get('modelo_llm')}" for c in casas
                      if c.get("status_julgamento") == "JULGADO_LLM")
    sem_decisao = [c for c in casas
                   if c.get("status_julgamento") in (None, "NAO_JULGADO") or c.get("cluster") not in ("A", "B")]
    falhas_ia = (resultado.get("resumo") or {}).get("llm_nao_julgados", 0)
    saida.append(_v(
        "Agente 2", "Todo imóvel construído tem decisão (pré-classificação, IA ou reserva)",
        f"{len(casas)} com decisão; nenhum sem julgamento",
        f"{por_status.get('REPROVADO_PRE_CLASSIFICACAO', 0)} pela pré-classificação, "
        f"{por_status.get('JULGADO_LLM', 0)} pela IA"
        + (f" ({', '.join(f'{m}: {n}' for m, n in modelos.most_common())})" if modelos else "")
        + f", {por_status.get('FALLBACK_PYTHON', 0)} pela reserva (Python); "
        f"{falhas_ia} falha(s) da IA; {len(sem_decisao)} sem julgamento",
        not sem_decisao, f"{contagem_txt(len(sem_decisao), 'imóvel ficou', 'imóveis ficaram')} sem julgamento",
    ))

    zona = resultado.get("zona_homogenea") or {}
    if zona:
        raio_casas = zona.get("raio_final_m") or (zona.get("zona_homogenea") or {}).get("raio_metros")
        raio_terrenos = zona.get("raio_final_terrenos_m") or raio_casas
        confirmados, vistos = [], set()
        for c in (zona.get("comparaveis_confirmados") or []) + (zona.get("terrenos") or []):
            chave = c.get("url") or id(c)
            if chave in vistos or c.get("incluido_por_fallback_zona"):
                continue
            vistos.add(chave)
            confirmados.append(c)
        fora = []
        for c in confirmados:
            raio = raio_terrenos if _eh_terreno(c) else raio_casas
            dist = c.get("distancia_metros")
            if dist is None or raio is None or float(dist) > float(raio):
                fora.append(f"{dist if dist is not None else 'sem distância'} m (raio {raio})")
        saida.append(_v(
            "Agente 2", "Todo comparável confirmado na zona tem distância ≤ raio usado",
            f"{len(confirmados)} confirmados dentro do raio (casas {raio_casas} m, terrenos {raio_terrenos} m)",
            f"{len(fora)} fora do raio" + (f": {', '.join(fora[:3])}" if fora else ""),
            not fora,
            f"{contagem_txt(len(fora), 'comparável confirmado está', 'comparáveis confirmados estão')} "
            f"fora do raio da zona",
        ))
    else:
        saida.append(_v("Agente 2", "Todo comparável confirmado na zona tem distância ≤ raio usado",
                        "zona calculada", "não verificável: a zona não foi calculada nesta avaliação", None))

    sem_checagem = [c for c in anuncios if not c.get("checagem_alvo")]
    saida.append(_v(
        "Agente 2", "A checagem do próprio anúncio rodou para todos os anúncios",
        f"checagem_alvo em {len(anuncios)} anúncios",
        f"{len(anuncios) - len(sem_checagem)} com checagem; {len(sem_checagem)} sem", not sem_checagem,
        f"a checagem do próprio anúncio não rodou em {contagem_txt(len(sem_checagem), 'anúncio', 'anúncios')}",
    ))
    return saida


# =============================================================================
# AGENTE 3
# =============================================================================
def _agente3(resultado: dict) -> list[dict]:
    ag3 = resultado.get("analise_qualitativa") or {}
    zona = resultado.get("zona_homogenea") or {}
    falhou = any(str(f).startswith("agente3") for f in resultado.get("falhas") or [])
    if zona:
        chegaram = [c for c in zona.get("comparaveis_confirmados") or []
                    if c.get("cluster") == "A" and (c.get("classificacao_zona") == "na_zona"
                                                     or c.get("incluido_por_fallback_zona"))]
    else:
        chegaram = [c for c in resultado.get("comparaveis") or [] if c.get("cluster") == "A"]
    esperado = min(len(chegaram), LIMITE_AG3)
    avaliados = ag3.get("comparaveis") or []
    notas_ruins, sem_analise = [], 0
    for c in avaliados + ([ag3["imovel_alvo"]] if ag3.get("imovel_alvo") else []):
        analise = c.get("analise_qualitativa") or {}
        nota = (analise.get("scores") or {}).get("score_qualitativo")
        if not analise or not analise.get("status"):
            sem_analise += 1
        elif not isinstance(nota, (int, float)) or not 0 <= nota <= 1:
            notas_ruins.append(str(nota))
    if not ag3 and falhou:
        encontrado, ok = "o Agente 3 falhou e a falha está registrada", True
    else:
        encontrado = (f"{len(avaliados)} avaliados de {len(chegaram)} que chegaram (limite de {LIMITE_AG3}); "
                      f"{sem_analise} sem análise; {len(notas_ruins)} nota(s) fora de 0 a 1"
                      + (f" ({', '.join(notas_ruins[:3])})" if notas_ruins else ""))
        ok = len(avaliados) == esperado and not sem_analise and not notas_ruins
    return [_v(
        "Agente 3", "Todo comparável que chegou foi avaliado ou tem falha registrada; notas entre 0 e 1",
        f"{esperado} avaliados (os que chegaram, até {LIMITE_AG3}), notas entre 0 e 1", encontrado, ok,
        "nem todos os comparáveis foram avaliados" if len(avaliados) != esperado or sem_analise
        else "alguma nota de qualidade veio fora do esperado",
    )]


# =============================================================================
# AGENTE 4
# =============================================================================
def _agente4(resultado: dict) -> list[dict]:
    ag4 = resultado.get("infraestrutura") or {}
    preco = resultado.get("preco_estimado") or {}
    nivel = (resultado.get("imovel_alvo") or {}).get("geocodificacao_nivel") or resultado.get("localizacao_alvo")
    nota = (ag4.get("scores") or {}).get("score_final")
    aviso = preco.get("aviso_infraestrutura")
    if ag4 and ag4.get("status") != "endereco_nao_localizado" and nota is not None:
        ok = isinstance(nota, (int, float)) and 0 <= nota <= 1 and (nivel is None or nivel in NIVEIS_PRECISOS)
        encontrado = f"rodou (localização: {nivel or 'não informada'}), nota {nota}"
        problema = "a nota de infraestrutura veio fora do esperado"
    else:
        motivo = "endereço não localizado" if ag4.get("status") == "endereco_nao_localizado" else "falhou"
        ok = bool(aviso)
        encontrado = f"{motivo}; aviso de nota neutra {'dado' if aviso else 'NÃO dado'}"
        problema = "a infraestrutura não foi avaliada e o aviso de nota média não apareceu"
    return [_v(
        "Agente 4", "Rodou com localização precisa, ou o aviso de nota neutra foi dado; nota entre 0 e 1",
        "nota entre 0 e 1 com localização de rua/bairro, ou aviso de nota neutra (0,50)", encontrado, ok, problema,
    )]


# =============================================================================
# AGENTE 5
# =============================================================================
def refazer_conta_agente5(preco: dict) -> float | None:
    """
    Valor medio refeito de forma independente a partir dos comparaveis usados: R$/m2 de
    cada um (descontando o terreno quando o terreno foi separado), media aparada 0,5 e
    area do imovel. None quando nao ha comparaveis para refazer.
    """
    usados_c, usados_t = _usados(preco)
    alvo = preco.get("imovel_alvo") or {}
    area_alvo = float(alvo.get("area_construida_m2") or 0)
    area_terreno_alvo = float(alvo.get("area_terreno_m2") or 0)
    condominial = normalizar_tipo(alvo.get("tipo") or "") in TIPOS_CONDOMINIAIS
    separou = bool((preco.get("calculo_terreno") or {}).get("aplicado")) and not condominial
    if separou:
        m2_terrenos = [v for v in (_m2_terreno(t) for t in usados_t) if v]
        if not m2_terrenos:
            return None
        menor_t, medio_t = min(m2_terrenos), _media_aparada(m2_terrenos)

    def _plausivel(v):
        return M2_CONSTRUCAO_MIN <= v <= M2_CONSTRUCAO_MAX

    serie_min, serie_med = [], []
    for u in usados_c:
        p, a = float(u.get("preco") or 0), float(u.get("area") or 0)
        if p <= 0 or a <= 0:
            continue
        total = p / a
        at = float(u.get("area_terreno") or 0)
        if not separou or at <= 0:
            serie_min.append(total)
            serie_med.append(total)
            continue
        c_min, c_med = p - menor_t * at, p - medio_t * at
        if c_min > 0:
            serie_min.append(c_min / a)
        if c_med > 0:
            serie_med.append(c_med / a)
        if c_min <= 0 and c_med <= 0:
            serie_min.append(total)
            serie_med.append(total)
    valores = [v for v in serie_min if _plausivel(v)]
    if not condominial:
        valores += [v for v in serie_med if _plausivel(v)]
    if not valores:
        return None
    valor = _media_aparada(valores) * area_alvo
    if separou:
        valor += medio_t * area_terreno_alvo
    return valor


def grupos_repetidos_provaveis(usados: list[dict]) -> list[list[dict]]:
    """
    Grupos de usados com o mesmo preco (<=0,5%), a mesma area (<=2%) e a mesma rua
    (nome parecido), com ou sem numero: provavelmente o mesmo imovel em varios anuncios
    que o Agente 1 nao juntou (ou casas iguais de um loteamento).
    """
    pai = list(range(len(usados)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    ruas = [identidade.rua(u) for u in usados]
    for i in range(len(usados)):
        for j in range(i + 1, len(usados)):
            if not ruas[i] or not ruas[j] or not identidade._nomes_parecidos(ruas[i], ruas[j]):
                continue
            dp = identidade.dif_relativa(identidade.preco(usados[i]), identidade.preco(usados[j]))
            da = identidade.dif_relativa(identidade.area(usados[i]), identidade.area(usados[j]))
            if dp is not None and da is not None and dp <= 0.005 and da <= 0.02:
                pai[raiz(i)] = raiz(j)
    grupos = {}
    for i, u in enumerate(usados):
        grupos.setdefault(raiz(i), []).append(u)
    return sorted((g for g in grupos.values() if len(g) >= 2), key=len, reverse=True)


def _repetidos_provaveis(preco: dict) -> dict:
    """Aviso (nao erro): podem ser casas iguais de um loteamento."""
    usados_c, usados_t = _usados(preco)
    grupos = grupos_repetidos_provaveis(usados_c) + grupos_repetidos_provaveis(usados_t)
    if not grupos:
        encontrado = "nenhum grupo"
    else:
        descricao = [
            f"{g[0].get('rua') or '?'} {_reais(float(g[0].get('preco') or 0)).split(',')[0]} / "
            f"{float(g[0].get('area') or 0):.0f} m² ×{len(g)}"
            for g in grupos[:5]
        ]
        encontrado = (f"{len(grupos)} grupo(s), {sum(len(g) for g in grupos)} anúncios: " + "; ".join(descricao)
                      + ("; ..." if len(grupos) > 5 else ""))
    return _v(
        "Agente 1", "Repetidos prováveis entre os usados",
        "nenhum grupo com mesmo preço (≤0,5%), mesma área (≤2%) e mesma rua (com ou sem número)",
        encontrado, "alerta" if grupos else True,
        f"{contagem_txt(len(grupos), 'grupo de anúncios parece', 'grupos de anúncios parecem')} ser o mesmo "
        f"imóvel e conta mais de uma vez no cálculo",
    )


def _provavel_no_calculo(resultado: dict, usados: list[dict]) -> dict:
    """Aviso (nao erro): provavel anuncio do proprio imovel continua no calculo."""
    urls_provaveis = {c.get("url") for c in _anuncios(resultado) if c.get("provavel_anuncio_do_alvo")}
    provaveis = [u for u in usados if u.get("provavel_anuncio_do_alvo") or u.get("url") in urls_provaveis]
    return _v(
        "Agente 5", "Provável anúncio do próprio imóvel no cálculo",
        "nenhum anúncio com o perfil quase todo igual ao do imóvel (mesma rua, área, cômodos e preço até 10%)",
        f"{len(provaveis)}" + (f": {', '.join(str(u.get('url')) for u in provaveis[:3])}" if provaveis else ""),
        "alerta" if provaveis else True,
        "um provável anúncio do próprio imóvel continua no cálculo" if len(provaveis) == 1
        else f"{len(provaveis)} prováveis anúncios do próprio imóvel continuam no cálculo",
    )


def _agente5(resultado: dict) -> list[dict]:
    preco = resultado.get("preco_estimado") or {}
    if not preco:
        return [_v("Agente 5", "Resultado do Agente 5", "resultado presente",
                   "o Agente 5 não devolveu resultado", any(str(f).startswith("agente5")
                                                             for f in resultado.get("falhas") or []),
                   "o cálculo do valor não rodou e a falha não ficou registrada")]
    saida = []
    avaliacao = preco.get("avaliacao_planilha") or {}
    exibido = float(avaliacao.get("valor_medio_imovel") or 0)
    refeito = refazer_conta_agente5(preco)
    if exibido > 0 and refeito is not None:
        dif = abs(refeito - exibido)
        liq = float(avaliacao.get("valor_liquidez") or 0)
        dif_liq = abs(liq - exibido * (1 - DESCONTO_LIQUIDEZ))
        saida.append(_v(
            "Agente 5", "Refazer a conta de forma independente dá o valor exibido",
            f"{_reais(exibido)} (liquidez {_reais(exibido * (1 - DESCONTO_LIQUIDEZ))}), tolerância de R$ 1",
            f"{_reais(refeito)} (diferença {_reais(dif)}; liquidez {_reais(liq)})",
            dif <= TOLERANCIA_REAIS and dif_liq <= TOLERANCIA_REAIS,
            f"a conta refeita dá {_reais(refeito).split(',')[0]}, e o valor mostrado é {_reais(exibido).split(',')[0]}",
        ))
    else:
        saida.append(_v("Agente 5", "Refazer a conta de forma independente dá o valor exibido",
                        "valor calculado", "não verificável: sem valor calculado ou sem comparáveis usados", None))

    saida.append(_repetidos_provaveis(preco))

    usados_c, usados_t = _usados(preco)
    usados = usados_c + usados_t
    zona = resultado.get("zona_homogenea") or {}
    urls_zona = {c.get("url") for chave in ("comparaveis_confirmados", "terrenos", "comparaveis_nao_verificados",
                                             "terrenos_nao_verificados")
                 for c in zona.get(chave) or [] if c.get("url")}
    fora = []
    for u in usados:
        status = u.get("status_zona") or "confirmado"
        if status == "sem_validacao":
            if zona.get("comparaveis_confirmados"):
                fora.append(f"{u.get('url')} (sem validação com zona calculada)")
        elif zona and u.get("url") and u["url"] not in urls_zona:
            fora.append(u.get("url"))
    saida.append(_v(
        "Agente 5", "Todos os comparáveis usados estão na zona",
        f"{len(usados)} usados na zona (confirmados ou com distância não verificada)",
        f"{len(fora)} fora da zona" + (f": {', '.join(map(str, fora[:3]))}" if fora else ""), not fora,
        f"{contagem_txt(len(fora), 'comparável usado está', 'comparáveis usados estão')} fora da zona",
    ))

    saida.append(_provavel_no_calculo(resultado, usados))

    urls_alvo = {c.get("url") for c in _anuncios(resultado) if c.get("eh_anuncio_do_alvo") and c.get("url")}
    alvo_usado = [u.get("url") for u in usados if u.get("eh_anuncio_do_alvo") or u.get("url") in urls_alvo]
    saida.append(_v(
        "Agente 5", "Nenhum anúncio do próprio imóvel entrou nos usados",
        "0 anúncios com eh_anuncio_do_alvo nos usados",
        f"{len(alvo_usado)}" + (f": {', '.join(map(str, alvo_usado[:3]))}" if alvo_usado else ""), not alvo_usado,
        "o anúncio do próprio imóvel entrou no cálculo",
    ))

    alvo_tipo = normalizar_tipo((preco.get("imovel_alvo") or {}).get("tipo") or "")
    separou = bool((preco.get("calculo_terreno") or {}).get("aplicado"))
    if alvo_tipo in TIPOS_TERRENO:
        esperado_t, ok_t = "imóvel é terreno: terrenos usados são o próprio cálculo", True
    elif separou:
        esperado_t = f"terreno separado: pelo menos {MIN_AMOSTRAS_CONFIAVEL} terrenos usados"
        ok_t = len(usados_t) >= MIN_AMOSTRAS_CONFIAVEL
    else:
        esperado_t, ok_t = "terreno não separado: 0 terrenos usados", not usados_t
    saida.append(_v(
        "Agente 5", "Terrenos usados coerentes com a decisão de separar o terreno", esperado_t,
        f"{'separou' if separou else 'não separou'} o terreno; {len(usados_t)} terrenos usados", ok_t,
        f"o terreno foi separado com menos de {MIN_AMOSTRAS_CONFIAVEL} terrenos" if separou
        else "terrenos entraram no cálculo sem o terreno ser separado",
    ))

    status = preco.get("status_avaliacao", "ok")
    confiavel = bool(preco.get("avaliacao_confiavel", True))
    n = len(usados_c)
    outro_motivo = (not preco.get("zona_calculada_nesta_avaliacao", True)
                    or status in ("sem_amostra", "valor_nao_estimado"))
    if alvo_tipo in TIPOS_TERRENO:
        n = len(usados_t)
    deveria_ter_valor = n >= MIN_AMOSTRAS_CONFIAVEL and not outro_motivo
    saida.append(_v(
        "Agente 5", "Sem valor ⇔ menos comparáveis válidos que o mínimo (ou outro motivo registrado)",
        f"{'com valor' if deveria_ter_valor else 'sem valor'} ({n} válidos, mínimo {MIN_AMOSTRAS_CONFIAVEL}"
        + (f"; motivo registrado: {status}" if outro_motivo else "") + ")",
        f"{'com valor' if confiavel else 'sem valor'} (status {status})",
        confiavel == deveria_ter_valor,
        "o valor não saiu, mas havia comparáveis suficientes" if deveria_ter_valor
        else "o valor saiu com menos comparáveis que o mínimo",
    ))
    return saida


def verificar_execucao(resultado: dict) -> list[dict]:
    """Todas as verificacoes, na ordem dos agentes. Nunca levanta excecao."""
    resultado = resultado or {}
    saida = []
    for etapa in (_geral, _agente1, _agente2, _agente3, _agente4, _agente5):
        try:
            saida += etapa(resultado)
        except Exception as exc:   # uma verificacao quebrada nao derruba as outras
            saida.append(_v(etapa.__name__.strip("_").replace("agente", "Agente "), "Verificação não rodou",
                            "verificação sem erro", f"erro: {type(exc).__name__}: {exc}", False,
                            "uma conferência não rodou (erro interno)"))
    return saida


def ordenar_para_tela(verificacoes: list[dict]) -> list[dict]:
    """Falhas primeiro, depois os alertas, as nao verificaveis e as que passaram."""
    ordem = {False: 0, "alerta": 1, None: 2, True: 3}
    return sorted(verificacoes or [], key=lambda v: ordem.get(v.get("ok"), 2))


def icone(ok) -> str:
    return {True: "✅", False: "❌", "alerta": "⚠️"}.get(ok, "⚪")


# =============================================================================
# CONFERENCIA NA TELA: titulo de uma linha e uma frase simples por agente
# =============================================================================
AGENTES = ("Agente 1", "Agente 2", "Agente 3", "Agente 4", "Agente 5")


def _frase_ok(agente: str, resultado: dict) -> str:
    """O que o agente fez, em uma frase (sem fórmulas nem ids)."""
    alvo = resultado.get("imovel_alvo") or {}
    preco = resultado.get("preco_estimado") or {}
    if agente == "Agente 1":
        c = (resultado.get("resumo_coleta") or {}).get("contagem") or {}
        encontrados = c.get("antes_dos_repetidos") or (len(_anuncios(resultado))
                                                       + len(resultado.get("duplicatas_descartadas") or []))
        repetidos = c.get("repetidos_juntados", len(resultado.get("duplicatas_descartadas") or []))
        local = f" de {alvo.get('cidade')}/{alvo.get('estado')}" if alvo.get("cidade") else ""
        return (f"buscou {contagem_txt(encontrados, 'anúncio', 'anúncios')}{local}, todos desta avaliação. "
                f"Juntou {contagem_txt(repetidos, 'anúncio repetido', 'anúncios repetidos')}.")
    if agente == "Agente 2":
        parecidos = (resultado.get("resumo") or {}).get("cluster_a")
        if parecidos is None:
            parecidos = sum(1 for c in resultado.get("comparaveis") or [] if c.get("cluster") == "A")
        zona = resultado.get("zona_homogenea") or {}
        if not zona:
            return (f"separou {contagem_txt(parecidos, 'imóvel parecido', 'imóveis parecidos')} com o seu; "
                    f"a zona do imóvel não foi calculada.")
        perto = sum(1 for c in zona.get("comparaveis_confirmados") or []
                    if not _eh_terreno(c) and not c.get("incluido_por_fallback_zona"))
        raio = zona.get("raio_final_m") or (zona.get("zona_homogenea") or {}).get("raio_metros")
        return (f"separou {contagem_txt(parecidos, 'imóvel parecido', 'imóveis parecidos')} com o seu e "
                f"confirmou {perto} perto do imóvel" + (f" (até {int(raio)} m)." if raio else "."))
    if agente == "Agente 3":
        n = len((resultado.get("analise_qualitativa") or {}).get("comparaveis") or [])
        return f"avaliou fotos e descrição de {contagem_txt(n, 'imóvel', 'imóveis')}."
    if agente == "Agente 4":
        ag4 = resultado.get("infraestrutura") or {}
        nota = (ag4.get("scores") or {}).get("score_final")
        if ag4.get("status") == "endereco_nao_localizado" or nota is None:
            return "não avaliou o entorno (endereço sem localização precisa); usou a infraestrutura como média."
        return f"avaliou o entorno do imóvel (nota {float(nota):.2f}".replace(".", ",") + " de 0 a 1)."
    # Agente 5
    usados = len(_usados(preco)[0])
    if preco.get("avaliacao_confiavel", True) and (preco.get("avaliacao_planilha") or {}).get("valor_medio_imovel"):
        return (f"calculou o valor com {contagem_txt(usados, 'comparável', 'comparáveis')}, "
                f"e a conta refeita confere.")
    from services.textos_tela import motivo_sem_valor
    return f"não calculou o valor: {motivo_sem_valor(resultado, alvo)['motivo'].rstrip('.')}."


def resumo_conferencia(resultado: dict, verificacoes: list[dict] | None = None) -> dict:
    """
    {"titulo": str, "frases": [str]} para o bloco "Conferência" da tela: titulo em uma
    linha e uma frase simples por agente ("⚠️ ..." quando alguma verificacao dele falhou).
    O detalhe tecnico (esperado, encontrado, ids) fica no Excel e no banco.
    """
    verificacoes = verificacoes if verificacoes is not None else verificar_execucao(resultado)
    problemas = [v for v in verificacoes if v.get("ok") is False or v.get("ok") == "alerta"]
    if not problemas:
        titulo = f"Conferência: tudo certo, os {len(AGENTES)} agentes funcionaram como esperado"
    else:
        agentes = list(dict.fromkeys(v["agente"] for v in problemas))
        titulo = f"Conferência: ⚠️ {contagem_txt(len(problemas), 'problema', 'problemas')} ({', '.join(agentes)})"
    frases = []
    for agente in ("Geral",) + AGENTES:
        dele = [v.get("problema") or v.get("verificacao") for v in problemas if v["agente"] == agente]
        if dele:
            frases.append(f"⚠️ {agente if agente != 'Geral' else 'Conferência geral'}: " + "; ".join(dele) + ".")
        elif agente != "Geral":
            try:
                frases.append(f"{agente}: {_frase_ok(agente, resultado)}")
            except Exception:   # a frase e so informativa
                frases.append(f"{agente}: funcionou como esperado.")
    return {"titulo": titulo, "frases": frases}
