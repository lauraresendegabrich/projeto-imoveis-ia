"""
Interface Web — Precificação Imobiliária
=========================================

Arquivo que se roda (e o principal no Streamlit Cloud). Só declara as páginas e o
nome de cada uma no menu; o conteúdo fica em app/paginas/.

COMO RODAR:
    .venv/Scripts/streamlit.exe run app/interface.py
"""
import streamlit as st

# Caminhos relativos a este arquivo (o Streamlit resolve a partir do arquivo principal).
st.navigation([
    st.Page("paginas/avaliacao.py", title="Avaliação de imóvel", icon="🏠", default=True),
    st.Page("paginas/leiloes_ativos.py", title="Leilões ativos", icon="🔨"),
]).run()
