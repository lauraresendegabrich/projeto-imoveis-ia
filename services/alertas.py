"""
Alertas automaticos de cada avaliacao
=====================================

Regras simples (sem IA e sem mudar nenhum calculo) que apontam avaliacoes que
merecem atencao: poucos comparaveis, comparaveis fora da zona, precos espalhados,
divergencia com o valor de avaliacao CAIXA, decisao apertada, possivel anuncio do
proprio imovel no calculo e falha de agente.

Gravados no banco (coluna execucoes.alertas) para quem for analisar os resultados
filtrar as avaliacoes que precisam ser olhadas. Nao aparecem na tela.

Os limites abaixo sao um ponto de partida, para ajustar com o uso.
"""
from __future__ import annotations

from statistics import mean, pstdev

# Limites (unico lugar).
LIMITE_POUCOS_COMPARAVEIS = 4          # 3 a 4 comparaveis: no limite do minimo de 3
LIMITE_PRECOS_ESPALHADOS = 0.40        # coeficiente de variacao do R$/m2 usado
LIMITE_DIFERENCA_AVALIACAO_CAIXA = 0.40  # valor de mercado vs avaliacao CAIXA
LIMITE_DECISAO_APERTADA = 0.05         # |sobra| em relacao ao valor minimo


def _alerta(codigo: str, mensagem: str, valor=None) -> dict:
    return {"codigo": codigo, "mensagem": mensagem, "valor": valor}


def calcular_alertas(execucao: dict, resultado_ag5: dict | None, falhas: list | None = None) -> list[dict]:
    """Lista de alertas da avaliacao (vazia quando nada chama atencao)."""
    ag5 = resultado_ag5 or {}
    alertas = []
    estimativa_ok = execucao.get("status_agente5") == "ok"

    # 1. Poucos comparaveis (so faz sentido com estimativa; com menos de 3 o status
    #    ja e amostra_insuficiente e a decisao e "Sem estimativa").
    if estimativa_ok:
        n_construcao = execucao.get("qtd_comparaveis_construcao") or 0
        if 0 < n_construcao <= LIMITE_POUCOS_COMPARAVEIS:
            alertas.append(_alerta(
                "poucos_comparaveis",
                f"Só {n_construcao} comparáveis de construção no cálculo; um anúncio muda muito o valor.",
                n_construcao,
            ))
        separa_terreno = bool((ag5.get("calculo_terreno") or {}).get("aplicado"))
        n_terreno = execucao.get("qtd_terrenos") or 0
        if separa_terreno and 0 < n_terreno <= LIMITE_POUCOS_COMPARAVEIS:
            alertas.append(_alerta(
                "poucos_terrenos",
                f"Só {n_terreno} terrenos no cálculo do m² do terreno.",
                n_terreno,
            ))

    # 2. Comparaveis fora da zona confirmada (fallback ou sem validacao de distancia).
    fora = execucao.get("usados_por_fallback") or 0
    if fora:
        alertas.append(_alerta(
            "fora_da_zona",
            f"{fora} comparável(is) do cálculo não confirmado(s) na zona homogênea.",
            fora,
        ))

    # 3. Precos espalhados: coeficiente de variacao do R$/m2 de construcao usado
    #    (um valor por comparavel; ja sem os descartados pela faixa de sanidade).
    valores_m2 = [v for v in (ag5.get("auditoria") or {}).get("m2_construcao_min_terreno") or [] if v and v > 0]
    if estimativa_ok and len(valores_m2) >= 3:
        cv = pstdev(valores_m2) / mean(valores_m2)
        if cv > LIMITE_PRECOS_ESPALHADOS:
            alertas.append(_alerta(
                "precos_espalhados",
                f"O R$/m² dos comparáveis varia muito (coeficiente de variação {cv:.0%}).",
                round(cv, 3),
            ))

    # 4. Valor de mercado muito diferente do valor de avaliacao CAIXA (se informado).
    mercado, avaliacao = execucao.get("valor_mercado"), execucao.get("valor_avaliacao")
    if estimativa_ok and mercado and avaliacao:
        diferenca = (mercado - avaliacao) / avaliacao
        if abs(diferenca) > LIMITE_DIFERENCA_AVALIACAO_CAIXA:
            alertas.append(_alerta(
                "diferente_avaliacao_caixa",
                f"Valor de mercado {diferenca:+.0%} em relação ao valor de avaliação CAIXA.",
                round(diferenca, 3),
            ))

    # 5. Decisao apertada: sobra ou falta pequena em relacao ao valor minimo.
    sobra, minimo = execucao.get("sobra"), execucao.get("valor_minimo")
    if sobra is not None and minimo:
        relativo = abs(sobra) / minimo
        if relativo < LIMITE_DECISAO_APERTADA:
            alertas.append(_alerta(
                "decisao_apertada",
                f"{'Sobra' if sobra >= 0 else 'Falta'} de só {relativo:.1%} do valor mínimo; "
                f"a decisão pode mudar em outra execução.",
                round(relativo, 4),
            ))

    # 6. Possivel anuncio do proprio imovel dentro da media.
    usados = ag5.get("comparaveis_usados") or {}
    possiveis = sum(
        1 for c in (usados.get("construcao") or []) + (usados.get("terreno") or [])
        if c.get("possivel_anuncio_do_alvo")
    )
    if possiveis:
        alertas.append(_alerta(
            "possivel_alvo_no_calculo",
            f"{possiveis} anúncio(s) com perfil do próprio imóvel entraram no cálculo.",
            possiveis,
        ))

    # 7. Falha de algum agente nesta avaliacao.
    if falhas:
        alertas.append(_alerta(
            "falha_de_agente",
            "Algum agente falhou nesta avaliação; veja a coluna falhas.",
            len(falhas),
        ))

    return alertas
