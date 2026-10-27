"""
Pagina "Leiloes ativos": imoveis de leilao avaliados (vw_leiloes_ativos), do
encerramento mais proximo ao mais distante, com cronometro, a resposta no valor
minimo da etapa atual e a mudanca manual da situacao (vendido, retirado...).
"""
import sys
from datetime import timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.cronometro import mostrar_cronometro
from services import leiloes_ativos
from services.banco import obter_database_url
from services.leilao import (
    DECISAO_DESCARTAR, DECISAO_MARGEM_APERTADA, DECISAO_OPORTUNIDADE, DECISAO_SEM_ESTIMATIVA, MODALIDADES_CAIXA,
    SITUACAO_ATIVO, SITUACOES_LEILAO, agora_brasilia, html_decisao, texto_cabecalho, texto_lance_descarte,
    texto_lance_maximo, texto_percentual,
)

SEM_AVALIACAO = "Sem avaliação"
DECISOES = [DECISAO_OPORTUNIDADE, DECISAO_MARGEM_APERTADA, DECISAO_DESCARTAR, DECISAO_SEM_ESTIMATIVA, SEM_AVALIACAO]
ENCERRA_EM_BREVE_DIAS = 7


def brl(valor) -> str:
    """R$ 1.234.567 (o $ escapado: no markdown do Streamlit vira formula)."""
    return "R\\$ " + f"{float(valor):,.0f}".replace(",", ".")


@st.cache_data(ttl=60, show_spinner=False)
def carregar(database_url: str, incluir_inativos: bool) -> list[dict]:
    return leiloes_ativos.listar_leiloes(database_url, incluir_inativos)


def salvar_situacao(id_imovel: int) -> None:
    """Callback do botao "Salvar": grava a situacao e recarrega a lista."""
    nova = st.session_state[f"situacao_{id_imovel}"]
    try:
        mudou = leiloes_ativos.marcar_situacao(obter_database_url(), id_imovel, nova)
        st.session_state["mensagem_leiloes"] = (
            ("ok", f"Situação alterada para \"{nova}\".") if mudou else ("erro", "Imóvel não encontrado no banco.")
        )
    except Exception as exc:
        st.session_state["mensagem_leiloes"] = ("erro", f"Não foi possível salvar: {type(exc).__name__}.")
    carregar.clear()


def mostrar_imovel(l: dict) -> None:
    with st.container(border=True):
        col_info, col_resposta = st.columns([3, 2])
        with col_info:
            numero = f" · nº {l['numero_imovel']}" if l.get("numero_imovel") else ""
            link = f" · [ver no site]({l['link']})" if l.get("link") else ""
            st.markdown(f"**{texto_cabecalho(l)}**{numero}{link}")
            endereco = ", ".join(x for x in (l.get("endereco"), l.get("bairro")) if x)
            cidade = "/".join(x for x in (l.get("cidade"), l.get("uf")) if x)
            st.caption(" · ".join(x for x in ((l.get("tipo") or "").capitalize(), endereco, cidade) if x))
            if l.get("encerramento"):
                mostrar_cronometro(l)
            else:
                st.caption("Compra Direta: sem data de encerramento (a primeira proposta vence).")
            if l.get("gravame"):
                st.error(f"⚠️ {l.get('gravame_texto') or 'Gravame/penhora averbada na matrícula.'}")
            if not l.get("ativo"):
                st.caption(f"Situação: {l.get('situacao')}" + (" · prazo encerrado" if l.get("encerrado") else ""))
        with col_resposta:
            if not l.get("ultima_execucao"):
                st.markdown(html_decisao(SEM_AVALIACAO, "1.05rem"), unsafe_allow_html=True)
            else:
                st.markdown(html_decisao(l["decisao"], "1.05rem"), unsafe_allow_html=True)
                if l.get("roi") is not None:
                    st.markdown(f"ROI pagando o valor mínimo: **{texto_percentual(l['roi'])}** · "
                                f"mínimo {brl(l['valor_minimo_atual'])}")
                    st.markdown(f"**{texto_lance_maximo(l, brl)}**")
                    st.caption(texto_lance_descarte(l, brl))
                if l.get("recalculado"):
                    st.caption(f"⚠️ Avaliado no {l['etapa_avaliada']}º leilão: a resposta foi refeita com o valor "
                               f"do {l['etapa']}º leilão (mesma liquidez).")
                if l.get("avaliado_em"):
                    st.caption(f"Avaliado em {l['avaliado_em'].strftime('%d/%m/%Y')}")
            col_sit, col_botao = st.columns([3, 2])
            with col_sit:
                st.selectbox("Situação", SITUACOES_LEILAO, key=f"situacao_{l['id']}",
                             index=SITUACOES_LEILAO.index(l.get("situacao") or SITUACAO_ATIVO))
            with col_botao:
                st.button("Salvar", key=f"salvar_{l['id']}", on_click=salvar_situacao, args=(l["id"],),
                          use_container_width=True)


st.set_page_config(page_title="Leilões ativos", page_icon="🔨", layout="wide")
st.title("🔨 Leilões ativos")
st.caption("Imóveis de leilão avaliados, do encerramento mais próximo ao mais distante. "
           "A resposta usa o valor mínimo da etapa atual e a liquidez da última avaliação.")

mensagem = st.session_state.pop("mensagem_leiloes", None)
if mensagem:
    (st.success if mensagem[0] == "ok" else st.error)(mensagem[1])

database_url = obter_database_url()
if not database_url:
    st.warning("Banco não configurado (DATABASE_URL): não há leilões para mostrar.")
    st.stop()

incluir_inativos = st.toggle("Mostrar também os encerrados, vendidos, retirados e suspensos")
try:
    linhas = [leiloes_ativos.preparar_linha(l) for l in carregar(database_url, incluir_inativos)]
except Exception as exc:
    st.error(f"Não foi possível ler os leilões no banco agora ({type(exc).__name__}). Tente de novo em instantes.")
    st.stop()

col_d, col_m, col_u = st.columns(3)
with col_d:
    decisoes = st.multiselect("Resposta", DECISOES, placeholder="Todas")
with col_m:
    modalidades = st.multiselect("Modalidade", MODALIDADES_CAIXA, placeholder="Todas")
with col_u:
    ufs = st.multiselect("UF", sorted({l["uf"] for l in linhas if l.get("uf")}), placeholder="Todas")
filtradas = leiloes_ativos.filtrar(linhas, decisoes, modalidades, ufs)

agora = agora_brasilia()
em_breve = sum(1 for l in filtradas if l.get("encerramento") and not l.get("encerrado")
               and l["encerramento"] - agora <= timedelta(days=ENCERRA_EM_BREVE_DIAS))
col1, col2, col3 = st.columns(3)
col1.metric("Imóveis", len(filtradas))
col2.metric("Oportunidades", sum(1 for l in filtradas if l.get("decisao") == DECISAO_OPORTUNIDADE))
col3.metric(f"Encerram em até {ENCERRA_EM_BREVE_DIAS} dias", em_breve)

if not filtradas:
    st.info("Nenhum leilão para mostrar. Os imóveis aparecem aqui depois de avaliados com a modalidade "
            "e o número do imóvel preenchidos.")
for linha in filtradas:
    mostrar_imovel(linha)
