"""
Pagina "Leiloes ativos": imoveis de leilao avaliados (vw_leiloes_ativos), do
encerramento mais proximo ao mais distante, com cronometro, a resposta no valor
minimo da etapa atual e a mudanca manual da situacao (vendido, retirado...).

"Ver avaliacao completa" (em cada card) troca a lista pela mesma tela de quando a
avaliacao acaba de rodar, com o resultado gravado no banco (services/detalhe_leilao.py).
"""
import sys
from datetime import timedelta, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.blocos_leilao import mostrar_estimativa_2o_leilao
from app.cronometro import mostrar_cronometro
from app.resultado_tela import fmt_brl, mostrar_avaliacao_leilao, mostrar_resultado
from services import detalhe_leilao, leiloes_ativos
from services.banco import obter_database_url
from services.registro_execucao import ROTULOS_STATUS_ZONA, ROTULOS_TIPO_COMPARAVEL, excel_resultado
from services.leilao import (
    DECISAO_DESCARTAR, DECISAO_MARGEM_APERTADA, DECISAO_OPORTUNIDADE, DECISAO_SEM_ESTIMATIVA, MODALIDADES_CAIXA,
    SITUACAO_ATIVO, SITUACOES_LEILAO, agora_brasilia, html_decisao, texto_cabecalho, texto_lance_descarte,
    texto_lance_maximo, texto_percentual,
)

SEM_AVALIACAO = "Sem avaliação"
DECISOES = [DECISAO_OPORTUNIDADE, DECISAO_MARGEM_APERTADA, DECISAO_DESCARTAR, DECISAO_SEM_ESTIMATIVA, SEM_AVALIACAO]
ENCERRA_EM_BREVE_DIAS = 7
CHAVE_DETALHE = "detalhe_leilao"     # {id_execucao, id_imovel} do card aberto
FUSO_BRASILIA = timezone(timedelta(hours=-3))


def brl(valor) -> str:
    """R$ 1.234.567 (o $ escapado: no markdown do Streamlit vira formula)."""
    return "R\\$ " + f"{float(valor):,.0f}".replace(",", ".")


@st.cache_data(ttl=60, show_spinner=False)
def carregar(database_url: str, incluir_inativos: bool) -> list[dict]:
    return leiloes_ativos.listar_leiloes(database_url, incluir_inativos)


@st.cache_data(ttl=300, show_spinner="Carregando a avaliação...")
def carregar_detalhe(database_url: str, id_execucao: str, id_imovel: int) -> dict:
    return detalhe_leilao.carregar_detalhe(database_url, id_execucao, id_imovel)


def abrir_detalhe(id_execucao: str, id_imovel: int) -> None:
    st.session_state[CHAVE_DETALHE] = {"id_execucao": id_execucao, "id_imovel": id_imovel}


def fechar_detalhe() -> None:
    st.session_state.pop(CHAVE_DETALHE, None)


def data_brasilia(momento) -> str:
    """dd/mm/aaaa hh:mm no horario de Brasilia (data_hora do banco vem com fuso)."""
    if momento.tzinfo is not None:
        momento = momento.astimezone(FUSO_BRASILIA)
    return momento.strftime("%d/%m/%Y %H:%M")


def mostrar_registro_antigo(detalhe: dict) -> None:
    """
    Avaliacao sem resultado_completo (anterior a migracao 006): o cartao do leilao, os
    valores e os comparaveis gravados, e o Excel.
    """
    import pandas as pd
    execucao = detalhe["execucao"]
    st.info("Esta avaliação foi feita antes de o sistema guardar a tela completa. Abaixo está o que "
            "ficou gravado; para ver os agentes, o laudo e o resto, avalie o imóvel de novo.")
    mostrar_avaliacao_leilao(detalhe["leilao"])
    confiavel = execucao.get("status_agente5") == "ok"
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("💰 Valor Médio Estimado", fmt_brl(execucao.get("valor_mercado")) if confiavel else "—")
    col_b.metric("⚡ Valor de Liquidez (-10%)", fmt_brl(execucao.get("liquidez")) if confiavel else "—")
    col_c.metric("⏱️ Tempo Estimado de Venda", (execucao.get("tempo_venda") or "?") if confiavel else "—")
    comparaveis = sorted(detalhe["comparaveis"], key=lambda c: (not c.get("entrou_no_calculo"), c.get("tipo") or ""))
    if comparaveis:
        st.markdown(f"**🏘️ Anúncios comparáveis gravados ({len(comparaveis)})**")
        st.markdown(pd.DataFrame([{
            "Tipo": ROTULOS_TIPO_COMPARAVEL.get(c.get("tipo"), c.get("tipo")),
            "No cálculo": "Sim" if c.get("entrou_no_calculo") else "Não",
            "Localização": ROTULOS_STATUS_ZONA.get(c.get("status_zona"), c.get("status_zona") or "-"),
            "Preço": fmt_brl(c["preco"]) if c.get("preco") else "-",
            "Área": f"{c['area']:.0f}m²" if c.get("area") else "-",
            "Rua": c.get("endereco") or "-",
            "Bairro": c.get("bairro") or "-",
            "Anúncio": f"[ver]({c['link']})" if c.get("link") else "-",
        } for c in comparaveis]).to_markdown(index=False), unsafe_allow_html=True)
    st.download_button(
        label="📥 Baixar resultado (Excel)",
        data=excel_resultado(execucao, detalhe["comparaveis"]),
        file_name=f"resultado_{execucao.get('cidade') or ''}_{execucao.get('bairro') or ''}.xlsx".replace(" ", "_"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def mostrar_detalhe(database_url: str, escolhido: dict) -> None:
    """A avaliacao completa do card aberto, no lugar da lista."""
    st.button("← Voltar aos leilões", on_click=fechar_detalhe)
    # Abre no topo (o clique foi no meio da lista).
    components.html("<script>try{window.parent.document.querySelector('[data-testid=\"stMain\"]')"
                    ".scrollTo(0,0)}catch(e){}</script>", height=0)
    try:
        dados = carregar_detalhe(database_url, escolhido["id_execucao"], escolhido["id_imovel"])
    except Exception as exc:
        st.error(f"Não foi possível ler a avaliação no banco agora ({type(exc).__name__}). Tente de novo em instantes.")
        return
    detalhe = detalhe_leilao.montar_detalhe(dados)
    if detalhe is None:
        st.warning("Avaliação não encontrada no banco.")
        return
    execucao = detalhe["execucao"]
    endereco = ", ".join(x for x in (execucao.get("endereco"), execucao.get("bairro")) if x)
    cidade = "/".join(x for x in (execucao.get("cidade"), execucao.get("uf")) if x)
    st.subheader(" · ".join(x for x in (endereco, cidade) if x) or "Avaliação")
    if execucao.get("data_hora"):
        st.caption(f"Avaliado em {data_brasilia(execucao['data_hora'])}. O cartão do leilão usa a etapa "
                   f"atual; o resto é o resultado do dia da avaliação.")
    if detalhe["resultado"] is not None:
        resultado = detalhe["resultado"]
        mostrar_resultado(resultado, resultado.get("imovel_alvo") or {}, detalhe["tela"] or {})
    else:
        mostrar_registro_antigo(detalhe)


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
                mostrar_estimativa_2o_leilao(l.get("estimativa_2o_leilao"), brl)
                if l.get("recalculado"):
                    st.caption(f"⚠️ Avaliado no {l['etapa_avaliada']}º leilão: a resposta foi refeita com o valor "
                               f"do {l['etapa']}º leilão (mesma liquidez).")
                if l.get("avaliado_em"):
                    st.caption(f"Avaliado em {l['avaliado_em'].strftime('%d/%m/%Y')}")
                st.button("🔎 Ver avaliação completa", key=f"detalhe_{l['id']}", on_click=abrir_detalhe,
                          args=(l["ultima_execucao"], l["id"]), use_container_width=True)
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

if st.session_state.get(CHAVE_DETALHE):
    mostrar_detalhe(database_url, st.session_state[CHAVE_DETALHE])
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
