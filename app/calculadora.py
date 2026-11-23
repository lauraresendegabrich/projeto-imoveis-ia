"""
Calculadora de simulacao do investimento (menu lateral das paginas "Avaliacao de
imovel" e "Leiloes ativos").

Usa a mesma conta da avaliacao (services/leilao.py: conta_investimento, lance_para_roi,
venda_para_empatar). Com os valores padrao (custos de 33%, corretagem de 5%, IR de 15%)
o ROI e igual ao da tela. E so simulacao: nao muda a decisao gravada.

Modo simples: um percentual para os custos antes da venda (a regra do professor).
Modo detalhado: os 33% abertos em itens. Os percentuais (comissao, ITBI, registro,
reserva) sao sobre a arrematacao; dividas, reforma e outros, em R$ (nao dependem do
preco). Os padroes do detalhado somam os mesmos 33%.

Preenchimento: `pedir_simulacao(sugestao)` (botao "Simular" de um card, ou o resultado
de uma avaliacao) guarda os valores; `mostrar_calculadora` aplica uma vez por sugestao
(pelo "id"), antes de criar os campos, e depois a pessoa muda o que quiser.
"""
import streamlit as st

from services.leilao import (
    ALIQUOTA_IR, COMISSAO_LEILOEIRO, CORRETAGEM, CUSTOS_ANTES_DA_VENDA, MODALIDADES_COM_LEILOEIRO,
    ROI_MARGEM_APERTADA, ROI_OPORTUNIDADE, classificar_roi, conta_investimento, html_decisao, lance_para_roi,
    texto_percentual, venda_para_empatar,
)

SIMPLES, DETALHADO = "Simples (regra do professor)", "Detalhado"
ITBI_PADRAO, REGISTRO_PADRAO = 0.03, 0.015

# Campos (chave no session_state -> valor inicial). Percentuais em % (33.0 = 33%).
_INICIAIS = {
    "calc_arrematacao": 0.0, "calc_venda": 0.0, "calc_modo": SIMPLES,
    "calc_custos": CUSTOS_ANTES_DA_VENDA * 100, "calc_corretagem": CORRETAGEM * 100, "calc_ir": ALIQUOTA_IR * 100,
    "calc_comissao": COMISSAO_LEILOEIRO * 100, "calc_itbi": ITBI_PADRAO * 100, "calc_registro": REGISTRO_PADRAO * 100,
    "calc_reserva": (CUSTOS_ANTES_DA_VENDA - COMISSAO_LEILOEIRO - ITBI_PADRAO - REGISTRO_PADRAO) * 100,
    "calc_dividas": 0.0, "calc_reforma": 0.0, "calc_outros": 0.0,
}


def _brl(valor: float) -> str:
    """R$ 1.234.567 (o $ escapado: no markdown do Streamlit vira formula)."""
    return "R\\$ " + f"{valor:,.0f}".replace(",", ".")


def pedir_simulacao(sugestao: dict, forcar: bool = False) -> None:
    """
    Guarda valores para a calculadora: {"id", "arrematacao", "venda", "modalidade",
    "rotulo"}. Pode ser callback de botao (roda antes da pagina). `forcar`: aplica de
    novo mesmo ja aplicada (botao "Simular" clicado outra vez).
    """
    if forcar:
        st.session_state.setdefault("calc_aplicadas", set()).discard(sugestao.get("id"))
    st.session_state["calc_sugestao"] = sugestao


def sugestao_da_avaliacao(leilao: dict | None, id_avaliacao) -> dict | None:
    """Valor minimo da etapa e liquidez de uma avaliacao confiavel (com lance maximo)."""
    if not leilao or leilao.get("lance_maximo") is None or not leilao.get("liquidez") or not leilao.get("valor_minimo"):
        return None
    etapa = f" · {leilao['etapa']}º leilão" if leilao.get("etapa") else ""
    return {"id": f"{id_avaliacao}:{leilao.get('etapa')}", "arrematacao": leilao["valor_minimo"],
            "venda": leilao["liquidez"], "modalidade": leilao.get("modalidade"),
            "rotulo": f"Última avaliação{etapa}"}


def _aplicar_sugestao() -> None:
    """Preenche os campos com a sugestao nova (uma vez por id), antes de cria-los."""
    # Cada sugestao so uma vez: a da avaliacao e pedida a cada rodada da pagina e nao
    # pode desfazer o que a pessoa mudou (nem a de um card simulado depois).
    sugestao = st.session_state.get("calc_sugestao")
    aplicadas = st.session_state.setdefault("calc_aplicadas", set())
    if not sugestao or sugestao.get("id") in aplicadas:
        return
    aplicadas.add(sugestao.get("id"))
    st.session_state["calc_arrematacao"] = float(sugestao["arrematacao"])
    st.session_state["calc_venda"] = float(sugestao["venda"])
    # Sem leiloeiro (Venda Online, Compra Direta): a comissao vai para a reserva, e o
    # total continua 33%.
    com_leiloeiro = sugestao.get("modalidade") in MODALIDADES_COM_LEILOEIRO or not sugestao.get("modalidade")
    comissao = COMISSAO_LEILOEIRO * 100 if com_leiloeiro else 0.0
    st.session_state["calc_comissao"] = comissao
    st.session_state["calc_reserva"] = _INICIAIS["calc_reserva"] + _INICIAIS["calc_comissao"] - comissao
    st.session_state["calc_rotulo"] = sugestao.get("rotulo")


def _restaurar_padroes() -> None:
    """Botao "Voltar aos padrões": percentuais da regra do professor, R$ zerados."""
    for chave, valor in _INICIAIS.items():
        if chave not in ("calc_arrematacao", "calc_venda", "calc_modo"):
            st.session_state[chave] = valor


def _percentual(rotulo: str, chave: str, base: float, ajuda: str | None = None) -> float:
    """Campo em % com o valor em R$ ao lado (sobre `base`). Devolve a fracao (0.33)."""
    valor = st.number_input(rotulo, key=chave, min_value=0.0, max_value=200.0, step=0.5, format="%.1f", help=ajuda)
    if base:
        st.caption(f"= {_brl(base * valor / 100)}")
    return valor / 100


def _reais(rotulo: str, chave: str, ajuda: str | None = None) -> float:
    return st.number_input(rotulo, key=chave, min_value=0.0, step=1000.0, format="%.0f", help=ajuda)


def parametros_detalhados(itens_pct: dict, itens_reais: dict) -> tuple[float, float]:
    """(custos_pct, custos_fixos) do modo detalhado: soma dos % e soma dos R$."""
    return sum(itens_pct.values()), sum(itens_reais.values())


def mostrar_calculadora() -> None:
    """A calculadora inteira (chamar dentro de `with st.sidebar:`)."""
    for chave, valor in _INICIAIS.items():
        st.session_state.setdefault(chave, valor)
    _aplicar_sugestao()

    st.markdown("### 🧮 Simular investimento")
    if st.session_state.get("calc_rotulo"):
        st.caption(f"Preenchida com: {st.session_state['calc_rotulo']}. Mude o que quiser.")
    else:
        st.caption("Use o botão 🧮 Simular de um imóvel, ou digite os valores.")

    arrematacao = _reais("Arrematação (R$)", "calc_arrematacao", "Quanto você paga no leilão (o lance).")
    st.caption(f"= {_brl(arrematacao)}")
    venda = _reais("Venda (R$)", "calc_venda",
                   "Por quanto você vende depois. Na avaliação é o valor de liquidez (90% do valor de mercado).")
    st.caption(f"= {_brl(venda)}")

    modo = st.radio("Custos antes da venda", [SIMPLES, DETALHADO], key="calc_modo", horizontal=False)
    if modo == SIMPLES:
        custos_pct = _percentual("Custos antes da venda (%)", "calc_custos", arrematacao,
                                 "Sobre a arrematação: comissão do leiloeiro, ITBI, registro, dívidas, reforma...")
        custos_fixos = 0.0
    else:
        st.caption("Os padrões somam 33%, como na regra do professor. Ao informar dívidas ou reforma em R\\$, "
                   "diminua a reserva.")
        itens_pct = {
            "comissao": _percentual("Comissão do leiloeiro (%)", "calc_comissao", arrematacao,
                                    "5% no Leilão SFI e na Licitação; 0% na Venda Online e na Compra Direta."),
            "itbi": _percentual("ITBI (%)", "calc_itbi", arrematacao, "Imposto da prefeitura; varia por cidade."),
            "registro": _percentual("Escritura e registro (%)", "calc_registro", arrematacao),
            "reserva": _percentual("Reserva para imprevistos (%)", "calc_reserva", arrematacao),
        }
        itens_reais = {
            "dividas": _reais("Dívidas: IPTU, condomínio (R$)", "calc_dividas"),
            "reforma": _reais("Reforma (R$)", "calc_reforma"),
            "outros": _reais("Outros: desocupação, advogado (R$)", "calc_outros"),
        }
        custos_pct, custos_fixos = parametros_detalhados(itens_pct, itens_reais)
        st.caption(f"Total: {texto_percentual(custos_pct, 1)} da arrematação + {_brl(custos_fixos)}")

    with st.expander("Venda: corretagem e IR"):
        corretagem_pct = _percentual("Corretagem (% da venda)", "calc_corretagem", venda)
        ir_pct = _percentual("IR (% do lucro)", "calc_ir", 0, "Sobre venda − custos antes da venda.")
    st.button("↺ Voltar aos padrões", on_click=_restaurar_padroes, use_container_width=True)

    if not arrematacao or not venda:
        st.info("Preencha a arrematação e a venda para ver o ROI.")
        return

    parametros = {"custos_pct": custos_pct, "corretagem_pct": corretagem_pct, "ir_pct": ir_pct,
                  "custos_fixos": custos_fixos}
    conta = conta_investimento(arrematacao, venda, **parametros)
    st.markdown(html_decisao(classificar_roi(conta["roi"]), "1.05rem"), unsafe_allow_html=True)
    st.metric("ROI", texto_percentual(conta["roi"]))
    st.markdown(
        f"Custos antes da venda: **{_brl(conta['custos_antes_da_venda'])}**  \n"
        f"Venda: {_brl(venda)}  \n"
        f"− Corretagem: {_brl(conta['corretagem'])}  \n"
        f"− IR: {_brl(conta['ir'])}  \n"
        f"**Resultado: {_brl(conta['resultado'])}**"
    )
    lance_30 = lance_para_roi(venda, ROI_OPORTUNIDADE, **parametros)
    lance_15 = lance_para_roi(venda, ROI_MARGEM_APERTADA, **parametros)
    st.markdown(
        f"Lance até **{_brl(lance_30)}** para {texto_percentual(ROI_OPORTUNIDADE, 0)} (Oportunidade)  \n"
        f"Lance até **{_brl(lance_15)}** para {texto_percentual(ROI_MARGEM_APERTADA, 0)} (Margem apertada)  \n"
        f"Venda mínima sem prejuízo: **{_brl(venda_para_empatar(arrematacao, **parametros))}**"
    )
    st.caption("Simulação: não muda a decisão da avaliação.")
