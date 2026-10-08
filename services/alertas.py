"""
Alertas automaticos de cada avaliacao
=====================================

Regras simples (sem IA e sem mudar nenhum calculo) que apontam avaliacoes que
merecem atencao: poucos comparaveis, comparaveis fora da zona, precos espalhados,
divergencia com o valor de avaliacao CAIXA, decisao apertada, possivel anuncio do
proprio imovel no calculo e falha de agente.

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

from statistics import mean, pstdev

# Limites (unico lugar).
LIMITE_POUCOS_COMPARAVEIS = 4          # 3 a 4 comparaveis: no limite do minimo de 3
LIMITE_PRECOS_ESPALHADOS = 0.40        # coeficiente de variacao do R$/m2 usado
LIMITE_DIFERENCA_AVALIACAO_CAIXA = 0.40  # valor de mercado vs avaliacao CAIXA
LIMITE_DECISAO_APERTADA = 0.05         # |sobra| em relacao ao valor minimo


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

    return alertas
