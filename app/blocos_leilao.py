"""
Blocos de tela do leilao usados no cartao do resultado (app/paginas/avaliacao.py) e
na pagina "Leiloes ativos" (app/paginas/leiloes_ativos.py).
"""
from __future__ import annotations

from services.leilao import (
    html_decisao, texto_lance_descarte, texto_lance_maximo, texto_percentual, titulo_estimativa_2o_leilao,
)


def mostrar_estimativa_2o_leilao(estimativa: dict | None, fmt_brl) -> None:
    """
    "E no 2º leilão?": resposta, ROI e lance pagando o minimo do 2o leilao, com a mesma
    liquidez. So no Leilao SFI, enquanto o imovel esta no 1o leilao.
    """
    if not estimativa:
        return
    import streamlit as st
    with st.container(border=True):
        st.markdown(f"**{titulo_estimativa_2o_leilao(estimativa)}**")
        st.markdown(html_decisao(estimativa["decisao"], "1rem"), unsafe_allow_html=True)
        st.markdown(f"ROI pagando o mínimo de {fmt_brl(estimativa['valor_minimo'])}: "
                    f"**{texto_percentual(estimativa['roi'])}**")
        st.markdown(texto_lance_maximo(estimativa, fmt_brl))
        st.caption(texto_lance_descarte(estimativa, fmt_brl))
