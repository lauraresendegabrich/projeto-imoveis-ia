"""
Interface Web — Precificação Imobiliária (página "Avaliação de imóvel")
=======================================================================

As páginas são declaradas em app/interface.py, que é o arquivo que se roda.

COMO RODAR:
    .venv/Scripts/streamlit.exe run app/interface.py
"""

import streamlit as st
import sys
import os
from pathlib import Path

# Adiciona raiz do projeto ao path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.resultado_tela import mostrar_resultado
from services.cep import buscar_cep, limpar_cep, texto_endereco_cep
from services.detalhe_leilao import resultado_para_gravar
from services.formatos import ler_numero_br
from services.verificacoes import verificar_execucao
from services.textos_tela import anuncios_do_alvo_na_zona, contagem, texto_comparaveis_na_zona
from services.leilao import (
    FORMAS_PAGAMENTO_CAIXA, MODALIDADES_CAIXA, ORIGEM_CAIXA, avaliar_imovel_leilao, contar_status_zona,
    campos_da_modalidade, ler_formulario_leilao, texto_aviso_raio, texto_aviso_zona,
    MODALIDADE_LICITACAO, MODALIDADE_SFI, MODALIDADE_VENDA_ONLINE, TEXTO_GRAVAME,
)
from services.caixa_pagina import ler_pagina_caixa, valores_para_formulario

from dotenv import load_dotenv
load_dotenv()


def buscar_cep_cache(cep):
    """
    buscar_cep guardando so os acertos na sessao: o formulario roda de novo a cada
    clique e nao precisa consultar o CEP toda vez. Falha nao fica guardada, para
    tentar de novo no proximo Enter.
    """
    cache = st.session_state.setdefault("_cache_cep", {})
    if cep in cache:
        return cache[cep], "ok"
    endereco, situacao = buscar_cep(cep)
    if endereco:
        cache[cep] = endereco
    return endereco, situacao




ESTADOS_BR = ["", "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
              "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
BANCOS_LEILAO = [ORIGEM_CAIXA]

# Campos do formulario (chave no session_state -> valor inicial). O CEP e a pagina da
# CAIXA preenchem escrevendo nessas chaves.
VALORES_INICIAIS_FORMULARIO = {
    "f_cep": "", "f_rua": "", "f_numero": "", "f_bairro": "", "f_cidade": "", "f_uf": "",
    "f_tipo": "Casa", "f_area": "", "f_quartos": 0, "f_vagas": None, "f_terreno": "", "f_banheiros": 0,
    "f_preco": "", "f_descricao": "", "f_fotos": "", "f_link_anuncio": "",
    "f_banco": ORIGEM_CAIXA, "f_modalidade": "",
    "f_valor_minimo": "", "f_valor_minimo_1": "", "f_data_1_leilao": "", "f_valor_minimo_2": "",
    "f_data_2_leilao": "", "f_data_encerramento": "", "f_valor_avaliacao": "", "f_numero_imovel": "",
    "f_link_caixa": "", "f_edital": "", "f_numero_item": "", "f_leiloeiro": "", "f_matricula": "",
    "f_averbacao": "", "f_gravame": False, "f_gravame_texto": "", "f_formas_pagamento": [],
    "f_regras_despesas": "",
}


def ler_dados_caixa():
    """
    Botao "Ler dados" (callback: roda antes de a tela ser montada, entao pode
    preencher os campos). Le a pagina salva ou o texto colado e preenche o
    formulario. Antes, limpa os campos: nada de um imovel anterior fica misturado.
    """
    arquivo = st.session_state.get("caixa_arquivo")
    if arquivo is not None:
        bruto = arquivo.getvalue()
        try:
            conteudo = bruto.decode("utf-8")
        except UnicodeDecodeError:
            conteudo = bruto.decode("latin-1")
    else:
        conteudo = st.session_state.get("caixa_texto") or ""
    if not conteudo.strip():
        st.session_state["caixa_lida"] = {"ok": False, "erro": "Envie a página salva ou cole o texto da página."}
        return
    lida = ler_pagina_caixa(conteudo)
    if lida["ok"]:
        for chave, inicial in VALORES_INICIAIS_FORMULARIO.items():
            st.session_state[chave] = list(inicial) if isinstance(inicial, list) else inicial
        valores = valores_para_formulario(lida["campos"])
        for chave, valor in valores.items():
            st.session_state[chave] = valor
        cep = limpar_cep(lida["campos"].get("cep") or "")
        if cep:
            # O CEP da pagina nao deve sobrescrever o endereco lido da CAIXA.
            st.session_state["f_cep"] = lida["campos"]["cep"]
            st.session_state["_cep_aplicado"] = cep
        lida["preenchidos"] = len(valores)
    st.session_state["caixa_lida"] = lida


def mostrar_resumo_caixa(lida):
    """Resumo do que foi lido da pagina da CAIXA: o que faltou e os avisos."""
    if not lida:
        return
    if not lida["ok"]:
        st.error(lida["erro"])
        return
    st.success(f"Dados lidos da CAIXA — confira antes de avaliar ({lida.get('preenchidos', 0)} campos preenchidos).")
    if lida["nao_encontrados"]:
        st.warning("Não encontrado na página (preencha à mão, se tiver): " + ", ".join(lida["nao_encontrados"]) + ".")
    for aviso in lida["avisos"]:
        st.warning(aviso)
    if lida["campos"].get("gravame"):
        st.error(f"⚠️ {lida['campos'].get('gravame_texto') or TEXTO_GRAVAME}")


def montar_resultado_final(ctx, resultado_ag5, id_registro=None):
    """
    Fim da avaliacao, depois do Agente 5: aviso da zona, avaliacao de leilao,
    resultado da tela, verificacoes e registro no banco (em segundo plano).

    ctx: o que os agentes 1 a 4 produziram (montado no fluxo e guardado na sessao).
    id_registro: id da linha no banco; outro quando o calculo e refeito pela resposta
    "Este anuncio e do seu imovel?" (os arquivos dos agentes continuam com o id da avaliacao).
    """
    import logging as _log_resumo
    id_execucao = ctx["id_execucao"]
    escopo_busca = ctx["escopo_busca"]
    tempos = ctx["tempos"]

    # ── RESUMO DA EXECUCAO (log para auditoria) ───────────────────
    _lr = _log_resumo.getLogger("pipeline")
    _lr.info("")
    _lr.info("=" * 55)
    _lr.info("  RESUMO DA EXECUCAO")
    _lr.info("=" * 55)
    _lr.info(f"  Agente 1 (coleta): {tempos['agente1']:.1f}s")
    _lr.info(f"  Agente 2 (clustering): {tempos['agente2']:.1f}s")
    _lr.info(f"  Agente 3+4 (paralelo): {tempos['agentes3e4']:.1f}s")
    _lr.info(f"  Tempo total: {tempos['total']:.1f}s")
    # Comparaveis usados por situacao da zona (os nao verificados contam para o minimo).
    contagem_zona = contar_status_zona(resultado_ag5)
    aviso_zona = texto_aviso_zona(contagem_zona, escopo_busca)
    _lr.info(
        f"  Usados no calculo: {contagem_zona['confirmado']} confirmados | "
        f"{contagem_zona['fallback']} zona_nao_verificada (contam para o minimo de 5) | "
        f"{contagem_zona['sem_validacao']} sem_validacao (socorro) | escopo_busca={escopo_busca}"
    )
    _lr.info("=" * 55)

    # Avaliacao de leilao: so depois do Agente 5, com os valores do formulario
    # (nunca passaram por nenhum agente). A etapa atual (1o/2o leilao) sai pela data.
    dados_leilao = ctx["dados_leilao"]
    leilao_entrada = leilao = None
    if dados_leilao:
        leilao_entrada = {**dados_leilao, "origem": dados_leilao["banco"],
                          "codigo_caixa": dados_leilao.get("numero_imovel")}
        leilao = avaliar_imovel_leilao(resultado_ag5, dados_leilao)
    if leilao is not None:
        leilao["aviso_zona"] = aviso_zona
        # Endereco nao localizado com precisao de rua/bairro: o calculo segue, mas o
        # aviso fica junto da decisao para nao passar despercebido.
        leilao["alvo_sem_localizacao"] = ctx["alvo_sem_localizacao"]

    imoveis_coletados = ctx["imoveis_coletados"]
    resultado = {
        "status": "completo",
        "id_execucao": id_execucao,
        "aviso_zona": aviso_zona,
        "aviso_raio": texto_aviso_raio(ctx["zona_resultado"]),
        "leilao_entrada": leilao_entrada,
        "leilao": leilao,
        "duplicatas_descartadas": ctx["duplicatas_descartadas"],
        "comparaveis": ctx["comparaveis"],
        "terrenos": ctx["terrenos"],
        "zona_homogenea": ctx["zona_resultado"],
        "analise_qualitativa": ctx["resultado_ag3"],
        "infraestrutura": ctx["resultado_ag4"],
        "preco_estimado": resultado_ag5,
        "resumo": ctx["resumo"],
        # Para as verificacoes automaticas (services/verificacoes.py).
        "imovel_alvo": ctx["imovel_alvo"],
        # Situacao de cada fonte e contagens da coleta (Agente 1).
        "resumo_coleta": imoveis_coletados[0].get("resumo_coleta") if imoveis_coletados else None,
        "falhas": ctx["falhas"],
        "localizacao_alvo": ctx["localizacao_alvo"],
    }
    # Verificacoes automaticas: leem o resultado de cada agente e conferem regras
    # (nao mudam nenhum calculo). Tela (modo conferencia), banco e Excel.
    resultado["verificacoes"] = verificar_execucao(resultado)

    # Grava a avaliacao no banco (Neon) em segundo plano: a tela nao espera e uma
    # falha do banco so vira aviso no log (services/banco.py).
    try:
        from services.registro_execucao import montar_registro
        from services.banco import gravar_em_segundo_plano
        entrada_usuario = ctx["entrada_usuario"]
        if id_registro:
            # Calculo refeito pela resposta da pessoa: linha nova no banco, ligada a original.
            entrada_usuario = {**(entrada_usuario or {}), "refeita_de": id_execucao,
                               "anuncios_do_alvo_pela_usuaria": resultado_ag5.get("anuncios_do_alvo_pela_usuaria")}
        registro_execucao, registro_comparaveis = montar_registro(
            id_execucao=id_registro or id_execucao,
            imovel_alvo=ctx["imovel_alvo"],
            leilao_entrada=leilao_entrada,
            leilao=leilao,
            imoveis_coletados=imoveis_coletados,
            resultado_ag2=ctx["resultado_ag2"],
            zona_resultado=ctx["zona_resultado"],
            resultado_ag3=ctx["resultado_ag3"],
            resultado_ag4=ctx["resultado_ag4"],
            resultado_ag5=resultado_ag5,
            tempos=tempos,
            falhas=ctx["falhas"],
            localizacao_alvo=ctx["localizacao_alvo"],
            entrada_usuario=entrada_usuario,
        )
        # Guardado no resultado (sessao) para o botao de exportar Excel: mesmo
        # conteudo gravado no banco.
        registro_execucao["verificacoes"] = resultado["verificacoes"]
        # Para o "Ver avaliacao completa" da pagina "Leiloes ativos" (migracao 006).
        registro_execucao["resultado_completo"] = resultado_para_gravar(resultado, ctx["tela_resultado"])
        resultado["registro"] = {"execucao": registro_execucao, "comparaveis": registro_comparaveis}
        gravar_em_segundo_plano(registro_execucao, registro_comparaveis)
    except Exception as e:
        _log_resumo.getLogger("pipeline").warning(f"[Banco] registro nao montado: {type(e).__name__}: {e}")
    return resultado


def _marcar_anuncio_do_alvo_na_tela(ctx, url, e_do_alvo):
    """Marca/desmarca o anuncio nas listas da tela (as tabelas mostram "seu anuncio")."""
    listas = [ctx["comparaveis"], ctx["terrenos"],
              (ctx["zona_resultado"] or {}).get("comparaveis_confirmados") or []]
    for lista in listas:
        for c in lista or []:
            if c.get("url") != url:
                continue
            if e_do_alvo:
                c["eh_anuncio_do_alvo"] = True
                c["anuncio_do_alvo_pela_usuaria"] = True
            elif c.get("anuncio_do_alvo_pela_usuaria"):
                c["eh_anuncio_do_alvo"] = False
                c.pop("anuncio_do_alvo_pela_usuaria", None)


def responder_anuncio_do_alvo(url, e_do_alvo):
    """
    Botao "Sim, este anuncio e do meu imovel" (ou "Nao e do meu imovel"): refaz o
    Agente 5 sem (ou com) o anuncio e o fim da avaliacao. Os agentes 1 a 4 nao rodam
    de novo: o Agente 5 le os arquivos desta avaliacao (id_execucao). Se outra
    avaliacao ja rodou depois, os arquivos sao dela e o calculo nao e refeito.
    """
    from agents.execucao import novo_id_execucao
    from agents.price_liquidity import estimar_preco
    ctx = st.session_state.get("contexto_avaliacao")
    resultado = st.session_state.get("resultado") or {}
    if not ctx:
        return
    urls = list((resultado.get("preco_estimado") or {}).get("anuncios_do_alvo_pela_usuaria") or [])
    if e_do_alvo and url not in urls:
        urls.append(url)
    elif not e_do_alvo and url in urls:
        urls.remove(url)
    imovel_alvo = {**ctx["imovel_alvo"], "escopo_busca": ctx["escopo_busca"]}
    novo_ag5 = estimar_preco(imovel_alvo_extra=imovel_alvo, id_execucao=ctx["id_execucao"],
                             urls_do_alvo_pela_usuaria=urls)
    if not novo_ag5.get("zona_calculada_nesta_avaliacao", True):
        resultado["erro_refazer_calculo"] = (
            "Não foi possível refazer o cálculo: outra avaliação rodou depois desta e os dados "
            "dela substituíram os desta. Avalie o imóvel de novo para responder."
        )
        return
    _marcar_anuncio_do_alvo_na_tela(ctx, url, e_do_alvo)
    st.session_state["resultado"] = montar_resultado_final(ctx, novo_ag5, id_registro=novo_id_execucao())


# Streamlit Cloud: carrega secrets como variáveis de ambiente
try:
    for key, value in st.secrets.items():
        if isinstance(value, str):
            os.environ[key] = value
except Exception:
    pass  # Roda local sem secrets

# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================

st.set_page_config(
    page_title="Precificação Imobiliária IA",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# SIDEBAR — FORMULÁRIO
# ============================================================

with st.sidebar:
    st.title("🏠 Avaliação de Imóvel")
    st.caption("Preencha os dados do imóvel que deseja avaliar")

    # Valores iniciais dos campos (chaves no session_state): o CEP e a pagina da CAIXA
    # preenchem os campos escrevendo nessas chaves.
    for _chave, _inicial in VALORES_INICIAIS_FORMULARIO.items():
        st.session_state.setdefault(_chave, _inicial)

    # ── PAGINA DA CAIXA (fora do formulario: preenche os campos antes de avaliar) ──
    # O site da CAIXA bloqueia acesso automatico (CAPTCHA): a pessoa salva a pagina
    # ou copia o texto dela no navegador (services/caixa_pagina.py).
    with st.expander("📄 Preencher com a página da CAIXA", expanded=bool(st.session_state.get("caixa_lida"))):
        st.caption(
            "Abra a página do imóvel no site da CAIXA e salve (Ctrl+S) ou copie o texto "
            "(Ctrl+A, Ctrl+C). O app não abre o link: o site da CAIXA bloqueia acesso automático."
        )
        st.file_uploader("Página salva (.html)", type=["html", "htm"], key="caixa_arquivo")
        st.text_area("ou cole o texto da página", key="caixa_texto", height=80)
        st.button("Ler dados", on_click=ler_dados_caixa, use_container_width=True)
        mostrar_resumo_caixa(st.session_state.get("caixa_lida"))

    # ── BUSCA POR CEP ─────────────────────────────────────────
    st.markdown("**🔎 Buscar por CEP:**")
    cep_input = st.text_input(
        "CEP (opcional)", max_chars=10, placeholder="13015-100", key="f_cep",
        help="Digite o CEP e aperte Enter para preencher rua, bairro, cidade e UF.",
    )
    if cep_input.strip():
        cep_limpo = limpar_cep(cep_input)
        if not cep_limpo:
            st.warning("CEP deve ter 8 dígitos.")
        else:
            endereco_cep, situacao_cep = buscar_cep_cache(cep_limpo)
            if endereco_cep:
                # So preenche quando o CEP muda: nao apaga o que a pessoa (ou a pagina
                # da CAIXA) ja colocou nos campos.
                if st.session_state.get("_cep_aplicado") != cep_limpo:
                    for _campo, _chave in (("rua", "f_rua"), ("bairro", "f_bairro"), ("cidade", "f_cidade"),
                                           ("estado", "f_uf")):
                        if endereco_cep.get(_campo):
                            st.session_state[_chave] = endereco_cep[_campo]
                    st.session_state["_cep_aplicado"] = cep_limpo
                st.success(f"✅ {texto_endereco_cep(endereco_cep)}")
            elif situacao_cep == "nao_encontrado":
                st.warning("CEP não encontrado.")
            else:
                st.warning("Não foi possível consultar o CEP agora. Preencha o endereço manualmente.")

    # ── LEILAO: banco e modalidade (fora do formulario: os campos do leilao mudam
    # conforme a modalidade, e dentro do st.form so mudariam depois do envio) ──
    st.markdown("**🔨 Leilão** (opcional)")
    banco_leilao = st.selectbox("Banco", BANCOS_LEILAO, key="f_banco")
    modalidade_caixa = st.selectbox(
        "Modalidade", [""] + MODALIDADES_CAIXA, key="f_modalidade",
        format_func=lambda m: m or "Não é leilão",
    )

    st.divider()

    with st.form("imovel_form"):
        st.markdown("**📍 Localização**")
        rua = st.text_input("Rua", key="f_rua")
        numero = st.text_input("Número", key="f_numero")
        bairro = st.text_input("Bairro", key="f_bairro")
        cidade = st.text_input("Cidade", key="f_cidade")
        # UF em linha propria (antes ao lado da cidade): legivel com a barra lateral estreita.
        estado = st.selectbox("UF", ESTADOS_BR, key="f_uf")

        st.markdown("**🏗️ Características**")
        tipo = st.selectbox("Tipo", ["Casa", "Apartamento"], key="f_tipo")
        col_a, col_b = st.columns(2)
        with col_a:
            # Campo de texto (e nao number_input) para aceitar o jeito brasileiro:
            # "179", "179,5", "1.250,75". Lido depois do envio por ler_numero_br.
            texto_area = st.text_input("Área construída (m²)", placeholder="Ex.: 179,50", key="f_area")
            quartos = st.number_input("Quartos", min_value=0, key="f_quartos")
            # Comeca vazio: vazio = nao informado, 0 = sem vaga (a checagem do proprio
            # anuncio so compara vagas quando foram informadas).
            vagas = st.number_input("Vagas", min_value=0, placeholder="Não informado", key="f_vagas")
        with col_b:
            texto_area_terreno = st.text_input(
                "Terreno (m²)", placeholder="Ex.: 300" if tipo == "Casa" else "Apartamento: deixe vazio",
                key="f_terreno",
            )
            banheiros = st.number_input("Banheiros", min_value=0, key="f_banheiros")
            # Texto (e nao number_input) para aceitar "1.200.000" e "1.200.000,00".
            texto_preco_anunciado = st.text_input("Preço (R$, opcional)", placeholder="Ex.: 1.200.000",
                                                  key="f_preco")
        st.caption("Casa: sem a área do terreno, o cálculo usa só o m² total das casas e fica menos preciso.")

        st.markdown("**📝 Descrição** (opcional)")
        descricao = st.text_area("Descrição do imóvel", height=80, key="f_descricao")

        st.markdown("**📸 Fotos do imóvel** (opcional, máx. 8)")
        st.caption("Cole os links diretos das fotos, um por linha")
        fotos_texto = st.text_area("Links das fotos", height=80, key="f_fotos",
                                   help="Cole até 8 URLs de imagens (uma por linha). Ex: https://...imovel.jpg")
        # So para reconhecer o anuncio do proprio imovel entre os comparaveis (Ag2):
        # nao entra em nenhum prompt.
        link_anuncio = st.text_input(
            "Link do anúncio deste imóvel (se tiver)", key="f_link_anuncio",
            placeholder="Ex.: https://www.vivareal.com.br/imovel/...-id-2903862416/",
            help="Se o imóvel estiver anunciado num portal, o anúncio dele fica fora da comparação.",
        )

        # Leilao: estes valores NAO entram no imovel_alvo nem em nenhum agente (preco
        # de leilao fica bem abaixo do mercado e distorceria os comparaveis). So sao
        # usados depois do Agente 5, em services/leilao.py. Valores e datas como texto
        # para aceitar o jeito brasileiro ("323.158,50", "30/11/2026 10:00").
        if modalidade_caixa:
            st.markdown(f"**🔨 {banco_leilao} · {modalidade_caixa}**")
            if modalidade_caixa == MODALIDADE_SFI:
                st.text_input("Valor mínimo do 1º leilão (R$)", placeholder="Ex.: 224.000,00", key="f_valor_minimo_1")
                st.text_input("Data e hora do 1º leilão", placeholder="Ex.: 30/11/2026 10:00", key="f_data_1_leilao")
                st.text_input("Valor mínimo do 2º leilão (R$)", placeholder="Ex.: 296.523,50", key="f_valor_minimo_2",
                              help="No 2º leilão o mínimo é a dívida: pode ser maior que o do 1º.")
                st.text_input("Data e hora do 2º leilão", placeholder="Ex.: 04/12/2026 10:00", key="f_data_2_leilao")
            else:
                st.text_input("Valor mínimo de venda (R$)", placeholder="Ex.: 323.158,00", key="f_valor_minimo",
                              help="Valor mínimo de venda que aparece no site da CAIXA.")
                if modalidade_caixa == MODALIDADE_LICITACAO:
                    st.text_input("Data e hora da licitação", placeholder="Ex.: 04/11/2026 10:00",
                                  key="f_data_encerramento")
                elif modalidade_caixa == MODALIDADE_VENDA_ONLINE:
                    st.text_input("Data e hora do encerramento", placeholder="Ex.: 26/10/2026 18:00",
                                  key="f_data_encerramento", help="É a data do cronômetro no site da CAIXA.")
                else:
                    st.caption("Compra Direta: sem data de encerramento (a primeira proposta vence).")
            st.text_input("Valor de avaliação (R$)", placeholder="Ex.: 410.000,00", key="f_valor_avaliacao",
                          help="Só informativo: não entra em nenhum cálculo.")
            st.text_input("Número do imóvel", placeholder="Ex.: 855552271653-1", key="f_numero_imovel")
            st.text_input("Link do imóvel no site do banco", key="f_link_caixa")
            if modalidade_caixa in (MODALIDADE_SFI, MODALIDADE_LICITACAO):
                st.text_input("Edital", placeholder="Ex.: 0052/0226 - CPA/RE", key="f_edital")
                st.text_input("Número do item", key="f_numero_item")
                st.text_input("Leiloeiro(a)", key="f_leiloeiro")
            st.text_input("Matrícula", key="f_matricula")
            st.text_input("Averbação dos leilões negativos", placeholder="Ex.: Averbado", key="f_averbacao")
            st.checkbox("Imóvel com gravame/penhora/indisponibilidade na matrícula", key="f_gravame")
            st.text_area("Aviso de gravame (texto da CAIXA)", height=68, key="f_gravame_texto")
            # So registrados (banco e Excel): nao entram em nenhum calculo.
            st.multiselect("Formas de pagamento aceitas", FORMAS_PAGAMENTO_CAIXA, key="f_formas_pagamento",
                           help="Conforme a página do imóvel. Só é registrado.")
            st.text_area("Regras de despesas (condomínio, tributos)", height=80, key="f_regras_despesas",
                         placeholder="Cole o texto da CAIXA. Ex.: Condomínio: sob responsabilidade do comprador...",
                         help="Só é registrado.")

        submitted = st.form_submit_button("🚀 Avaliar Imóvel", use_container_width=True)

# Campos do formulario mostrados no resultado e no laudo (app/resultado_tela.py), e
# gravados com ele para o "Ver avaliacao completa" de "Leiloes ativos".
tela_resultado = {
    "rua": rua, "numero": numero, "bairro": bairro, "cidade": cidade, "estado": estado,
    "tipo": tipo, "quartos": quartos, "banheiros": banheiros, "vagas": vagas,
}

# ============================================================
# ÁREA PRINCIPAL — RESULTADOS
# ============================================================

st.title("📊 Precificação Imobiliária com IA")
st.markdown("Sistema multiagente que estima o valor do seu imóvel com base em dados reais do mercado.")


# Area dos resultados: ao clicar em "Avaliar Imovel" ela e apagada antes de comecar,
# para o resultado da avaliacao anterior nao ficar na tela durante a nova.
area_principal = st.empty()
if submitted:
    st.session_state.pop("resultado", None)
    st.session_state.pop("imovel_alvo_dados", None)
    area_principal.empty()

with area_principal.container():
    # ============================================================
    # EXECUÇÃO DO PIPELINE
    # ============================================================

    if not submitted:
        # Tela inicial
        st.info("👈 Preencha os dados do imóvel na barra lateral e clique em **Avaliar Imóvel** para começar.")

        col_info1, col_info2, col_info3 = st.columns(3)
        with col_info1:
            st.markdown("### 🔍 Coleta")
            st.write("Reúne imóveis similares à venda na mesma região, a partir de uma base de dados de anúncios e de coleta complementar quando necessário")
        with col_info2:
            st.markdown("### 🧠 Análise")
            st.write("Avalia qualidade, infraestrutura e padrão da vizinhança")
        with col_info3:
            st.markdown("### 💰 Preço")
            st.write("Calcula valor de mercado e tempo estimado de venda")

        st.divider()
        st.caption("O sistema usa uma base de dados de anúncios como fonte principal e complementa com coleta em tempo real quando há poucos imóveis na região.")

    elif submitted:
        # Validação dos campos obrigatórios
        erros_validacao = []
        if not rua.strip():
            erros_validacao.append("Rua é obrigatória")
        if not bairro.strip():
            erros_validacao.append("Bairro é obrigatório")
        if not cidade.strip():
            erros_validacao.append("Cidade é obrigatória")
        if not estado.strip():
            erros_validacao.append("Estado é obrigatório")
        # Areas digitadas como texto (aceita "179,5" e "1.250,75").
        area, area_terreno = 0.0, 0.0
        try:
            area = ler_numero_br(texto_area) or 0.0
        except ValueError:
            erros_validacao.append(f"Área construída inválida: \"{texto_area}\" (use, por exemplo, 179,50)")
            area = -1.0   # evita repetir o aviso de area obrigatoria
        try:
            area_terreno = ler_numero_br(texto_area_terreno) or 0.0
        except ValueError:
            erros_validacao.append(f"Terreno inválido: \"{texto_area_terreno}\" (use, por exemplo, 300 ou 312,50)")
        if area == 0:
            erros_validacao.append("Área construída deve ser maior que zero")
        preco_anunciado = 0.0
        try:
            preco_anunciado = ler_numero_br(texto_preco_anunciado) or 0.0
        except ValueError:
            erros_validacao.append(
                f"Preço inválido: \"{texto_preco_anunciado}\" (use, por exemplo, 1.200.000 ou 1.200.000,00)"
            )
        if quartos <= 0:
            erros_validacao.append("Número de quartos deve ser maior que zero")

        # Leilao: so os campos da modalidade escolhida, lidos do jeito brasileiro
        # ("296.523,50", "30/11/2026 10:00"). Os nomes dos campos do formulario (f_...)
        # viram os nomes de services/leilao.py.
        textos_leilao = {
            campo: st.session_state.get(chave) for campo, chave in (
                ("valor_minimo", "f_valor_minimo"), ("valor_minimo_1", "f_valor_minimo_1"),
                ("valor_minimo_2", "f_valor_minimo_2"), ("valor_avaliacao", "f_valor_avaliacao"),
                ("data_1_leilao", "f_data_1_leilao"), ("data_2_leilao", "f_data_2_leilao"),
                ("data_encerramento", "f_data_encerramento"), ("numero_imovel", "f_numero_imovel"),
                ("link", "f_link_caixa"), ("edital", "f_edital"), ("numero_item", "f_numero_item"),
                ("leiloeiro", "f_leiloeiro"), ("matricula", "f_matricula"),
                ("averbacao_leiloes_negativos", "f_averbacao"), ("gravame", "f_gravame"),
                ("gravame_texto", "f_gravame_texto"), ("formas_pagamento", "f_formas_pagamento"),
                ("regras_despesas", "f_regras_despesas"),
            )
        }
        dados_leilao, erros_leilao = ler_formulario_leilao(textos_leilao, banco_leilao, modalidade_caixa)
        erros_validacao += erros_leilao

        if erros_validacao:
            st.error("❌ **Corrija os campos abaixo para iniciar a avaliação:**")
            for erro in erros_validacao:
                st.warning(f"• {erro}")
            st.stop()

        # Tudo o que o formulario mandou, como foi digitado e como foi lido, para o banco
        # (coluna entrada_usuario): explica depois casos como "o anuncio do proprio imovel
        # entrou no calculo" sem depender do que ficou na tela.
        entrada_usuario = {
            "cep": cep_input or None,
            "rua": rua, "numero": numero, "bairro": bairro, "cidade": cidade, "estado": estado,
            "tipo": tipo,
            "area_digitada": texto_area, "area_lida": area,
            "terreno_digitado": texto_area_terreno, "terreno_lido": area_terreno,
            "quartos": int(quartos), "banheiros": int(banheiros), "vagas": int(vagas) if vagas is not None else None,
            "preco_digitado": texto_preco_anunciado, "preco_lido": preco_anunciado or None,
            "descricao": descricao or None, "descricao_caracteres": len(descricao or ""),
            "fotos": [l.strip() for l in (fotos_texto or "").splitlines() if l.strip()],
            "link_anuncio": link_anuncio.strip() or None,
            "leilao": {
                "banco": banco_leilao,
                "modalidade": modalidade_caixa or None,
                "digitado": {campo: texto for campo, texto in textos_leilao.items()
                             if campo in campos_da_modalidade(modalidade_caixa)} if modalidade_caixa else None,
                "lido_da_pagina_caixa": bool((st.session_state.get("caixa_lida") or {}).get("ok")),
            },
        }

        # Monta o dict do imóvel alvo
        tipo_map = {"Casa": "house", "Apartamento": "apartment"}
        property_type_map = {"Casa": "Casas", "Apartamento": "Apartamentos"}

        imovel_alvo = {
            "rua": rua,
            "numero": numero,
            "bairro": bairro,
            "cidade": cidade,
            "estado": estado,
            "localizacao": f"{cidade}, {estado}",
            "tipo": tipo_map[tipo],
            "propertyType": property_type_map[tipo],
            "area": area,
            "area_terreno": area_terreno if area_terreno > 0 else None,
            "bedrooms": quartos,
            "bathrooms": banheiros,
            "parkingSpaces": vagas,
            "neighborhood": bairro,
            "street": rua,
            "description": descricao or (
                f"{tipo} com {area}m², {quartos} quartos, {banheiros} banheiros"
                + (f", {vagas} vagas" if vagas is not None else "") + f" - {bairro}, {cidade}/{estado}"
            ),
            # Texto generico gerado acima: nao serve de prova de identidade no Ag2.
            "descricao_gerada": not descricao,
            "images": [],
            # Prova mais forte de que um comparavel e o anuncio do proprio imovel (Ag2).
            "link_anuncio": link_anuncio.strip() or None,
        }

        # Processa fotos: links diretos informados pelo usuario
        import logging as _log_fotos
        _logger = _log_fotos.getLogger(__name__)

        fotos_informadas = [url.strip() for url in fotos_texto.strip().split("\n") if url.strip()] if fotos_texto.strip() else []
        _logger.info(f"  [fotos] URLs informadas pelo usuario: {len(fotos_informadas)}")

        # Valida URLs (deve começar com http)
        fotos_validas = [url for url in fotos_informadas if url.startswith("http")][:8]
        _logger.info(f"  [fotos] URLs validas: {len(fotos_validas)}")

        imovel_alvo["images"] = fotos_validas
        _logger.info(f"  [fotos] Fotos selecionadas: {len(fotos_validas)}")

        if not fotos_validas:
            _logger.info("  [fotos] Imovel alvo sem imagens — analise visual nao sera realizada")

        if preco_anunciado > 0:
            imovel_alvo["price"] = preco_anunciado
            imovel_alvo["pricePerSqm"] = preco_anunciado / area if area > 0 else 0

        # Importa os agentes
        import os
        import time
        import threading
        from agents.collector import _mesma_rua, coletar_imoveis
        from agents.comparables import identificar_comparaveis, analisar_zona_homogenea
        from agents.text_analyzer import analisar_comparaveis
        from agents.infra_evaluator import avaliar_infraestrutura
        from agents.price_liquidity import estimar_preco
        from agents.execucao import novo_id_execucao
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Identifica esta avaliacao nos JSONs que os agentes trocam: os Agentes 3/4/5
        # ignoram arquivos de avaliacoes anteriores (ver agents/execucao.py).
        id_execucao = novo_id_execucao()
        # Limite de chamadas da TomTom (ultima tentativa de geocodificacao) e por avaliacao.
        from agents.comparables import reiniciar_contagem_tomtom
        reiniciar_contagem_tomtom()
        # Falhas desta avaliacao, gravadas no banco (a tela continua mostrando os avisos).
        falhas_execucao = []

        # ==============================================================
        # GEOCODIFICAÇÃO ÚNICA DO ALVO (persistida pra todos os agentes)
        # ==============================================================
        # Mesma geocodificacao do Agente 2: tenta endereco completo -> rua+numero -> rua
        # -> bairro e recusa resultados com precisao de cidade (o Google/Nominatim
        # devolvem o centro da cidade quando nao acham a rua; antes isso era aceito).
        alvo_sem_localizacao = False
        # Gravado no banco para contar depois quantas avaliacoes ficaram sem localizacao.
        localizacao_alvo = "coordenada_informada"
        if not imovel_alvo.get("lat") or not imovel_alvo.get("lon"):
            from agents.comparables import _geocodificar_com_fallback
            endereco_geo = ", ".join(p for p in (rua, numero, bairro, cidade, estado, "Brasil") if p)
            _logger.info(f"[Geo][Alvo] endereco={endereco_geo}")
            _lat, _lon, _nivel_geo, _endereco_usado = _geocodificar_com_fallback(
                endereco_principal=endereco_geo, rua=rua, numero=numero, bairro=bairro,
                cidade=cidade, estado=estado, permitir_cidade=False,
            )
            if _lat is not None and _lon is not None:
                imovel_alvo["lat"] = _lat
                imovel_alvo["lon"] = _lon
                imovel_alvo["geocodificacao_nivel"] = _nivel_geo
                localizacao_alvo = _nivel_geo
                _logger.info(
                    f"[Geo][Alvo] lat={_lat:.6f} | lon={_lon:.6f} | nivel={_nivel_geo} | "
                    f"endereco_usado={_endereco_usado!r} | geocodificacao_nova=true"
                )
            else:
                alvo_sem_localizacao = True
                localizacao_alvo = "nao_localizado"
                _logger.warning("[Geo][Alvo] Nao foi possivel localizar o alvo com precisao de rua ou bairro")
        else:
            _logger.info(f"[Geo][Alvo] lat={imovel_alvo['lat']} | lon={imovel_alvo['lon']} | geocodificacao_nova=false (ja existente)")

        st.divider()
        # Trocados ao terminar ou ao interromper: nao ficam junto do resultado.
        cabecalho = st.empty()
        cabecalho.subheader("⏳ Avaliação em andamento")
        aviso_cancelar = st.empty()
        aviso_cancelar.caption("Para cancelar, pressione F5.")

        progress = st.progress(0)
        status_box = st.empty()
        log_area = st.container()
        if tipo == "Casa" and not area_terreno:
            with log_area:
                st.info("ℹ️ Sem a área do terreno, o cálculo usa só o m² total das casas e fica menos preciso.")
        if alvo_sem_localizacao:
            with log_area:
                st.warning(
                    "⚠️ Não foi possível localizar o endereço no mapa com precisão de rua ou bairro. "
                    "A distância dos comparáveis até o imóvel não será verificada, e o valor fica menos preciso."
                )

        inicio_total = time.time()

        # ==============================================================
        # ETAPA 1 — Coleta de imóveis na região (~2 min)
        # ==============================================================
        with log_area:
            st.write(f"**Agente Coletor** — Pesquisando imóveis à venda perto do seu, em **{bairro}, {cidade}/{estado}**...")

        # Roda coleta em thread separada para poder atualizar o contador
        resultado_coleta = [None]
        def _coletar():
            resultado_coleta[0] = coletar_imoveis(
                localizacao=imovel_alvo["localizacao"],
                tipo_imovel=imovel_alvo["tipo"],
                bairro=imovel_alvo.get("bairro", ""),
                rua=imovel_alvo.get("rua", ""),
                # Coordenada e precisao da localizacao feita acima: com rua ou bairro,
                # o Agente 1 traz tambem os anuncios mais proximos do imovel.
                lat_alvo=imovel_alvo.get("lat"),
                lon_alvo=imovel_alvo.get("lon"),
                nivel_geo_alvo=imovel_alvo.get("geocodificacao_nivel"),
                # Gravado em cada anuncio (verificacoes: dados desta execucao).
                id_execucao=id_execucao,
            )

        t1 = time.time()
        thread_coleta = threading.Thread(target=_coletar)
        thread_coleta.start()

        # Contador regressivo enquanto coleta
        tempo_estimado_ag1 = 120  # ~2 minutos
        while thread_coleta.is_alive():
            elapsed = time.time() - t1
            restante = max(0, tempo_estimado_ag1 - elapsed)
            pct = min(18, int(5 + (elapsed / tempo_estimado_ag1) * 15))
            progress.progress(pct)
            if restante > 0:
                if restante > 90:
                    status_box.info(f"🔍 **Agente Coletor de Dados** | Consultando a base de dados de anúncios... Faltam ~{int(restante)}s")
                elif restante > 60:
                    status_box.info(f"🔍 **Agente Coletor de Dados** | Lendo anúncios de casas e terrenos... Faltam ~{int(restante)}s")
                elif restante > 30:
                    status_box.info(f"🔍 **Agente Coletor de Dados** | Extraindo preços, áreas e fotos... Faltam ~{int(restante)}s")
                else:
                    status_box.info(f"🔍 **Agente Coletor de Dados** | Organizando imóveis encontrados... Faltam ~{int(restante)}s")
            else:
                status_box.info("🔍 **Agente Coletor de Dados** | Finalizando... quase pronto!")
            time.sleep(2)

        thread_coleta.join()
        imoveis_coletados = resultado_coleta[0] or []
        tempo_ag1 = time.time() - t1

        if not imoveis_coletados:
            status_box.error("❌ Nenhum imóvel encontrado na região. Tente outro bairro ou cidade maior.")
            cabecalho.subheader("❌ Avaliação interrompida")
            aviso_cancelar.empty()
            st.stop()

        progress.progress(20)
        # O Ag1 junta o mesmo imovel anunciado em varios portais/imobiliarias: cada
        # representante guarda os anuncios descartados em "duplicatas".
        duplicatas_descartadas = [
            {
                "Mantido": im.get("source") or "-",
                "Preço": im.get("price") or im.get("preco"),
                "Área": im.get("area") or im.get("area_construida"),
                "Anúncio mantido": im.get("url") or "",
                "Descartado": dup.get("source") or dup.get("portal") or "-",
                "Anúncio descartado": dup.get("url") or "",
                "Motivo": str(dup.get("motivo") or "").split("(")[0],
            }
            for im in imoveis_coletados
            for dup in (im.get("duplicatas") or [])
        ]
        with log_area:
            st.success(f"✅ {contagem(len(imoveis_coletados), 'imóvel à venda encontrado', 'imóveis à venda encontrados')} na região")
            if duplicatas_descartadas:
                st.caption(
                    f"ℹ️ {contagem(len(duplicatas_descartadas), 'anúncio repetido', 'anúncios repetidos')} do mesmo imóvel "
                    f"(em outro portal ou por outra imobiliária) "
                    f"{'foi descartado' if len(duplicatas_descartadas) == 1 else 'foram descartados'}."
                )
            # Mostra o que a busca (Agente 1) realmente fez: o escopo vem dela, e a
            # contagem na rua usa a mesma comparacao da busca (sem acento/maiusculas).
            # Antes a tela comparava os nomes letra por letra e dizia "cidade toda"
            # quando o bairro so estava escrito sem acento (ITAJUBA x Itajubá).
            escopo_busca = imoveis_coletados[0].get("escopo_busca")
            n_proximidade = sum(1 for im in imoveis_coletados if im.get("origem_busca") == "proximidade")
            if n_proximidade:
                st.caption(
                    f"ℹ️ {contagem(n_proximidade, 'anúncio veio', 'anúncios vieram')} por proximidade (até 1,5 km do "
                    f"imóvel, fora da rua e do bairro). Só entram no cálculo se estiverem dentro da zona do imóvel."
                )
            n_resto_cidade = sum(1 for im in imoveis_coletados if im.get("origem_busca") == "cidade")
            if n_resto_cidade:
                st.caption(
                    f"ℹ️ {contagem(n_resto_cidade, 'anúncio veio', 'anúncios vieram')} do resto da cidade (poucos "
                    f"anúncios perto do imóvel). Só entram no cálculo se estiverem dentro da zona do imóvel."
                )
            if (rua or bairro) and escopo_busca == "cidade":
                local = " / ".join(x for x in (rua, bairro) if x)
                st.caption(f"ℹ️ Nenhum imóvel encontrado em {local}. Usando imóveis da cidade toda.")
            elif rua and escopo_busca in ("rua+bairro", "rua+bairro+proximidade"):
                na_rua = sum(1 for im in imoveis_coletados if _mesma_rua(im.get("street") or im.get("rua"), rua))
                if na_rua > 0:
                    st.caption(f"ℹ️ {contagem(na_rua, 'imóvel encontrado', 'imóveis encontrados')} na mesma rua ({rua})")
                elif bairro:
                    st.caption(f"ℹ️ Nenhum imóvel encontrado na mesma rua ({rua}). Usando imóveis do bairro {bairro}.")

        # ==============================================================
        # ETAPA 2 — Identificação dos comparáveis (~30s)
        # ==============================================================
        status_box.info("📊 **Etapa 2/5 — Agente Identificador de Comparáveis** | Tempo estimado: ~30 segundos")
        progress.progress(25)
        with log_area:
            st.write("**Agente Identificador** — Comparando os imóveis encontrados com o seu para identificar os mais parecidos...")

        t2 = time.time()
        resultado_ag2 = identificar_comparaveis(
            imovel_alvo=imovel_alvo,
            imoveis_coletados=imoveis_coletados,
            usar_llm=True,
            id_execucao=id_execucao,
        )
        tempo_ag2_cluster = time.time() - t2

        comparaveis = resultado_ag2.get("comparaveis", [])
        terrenos = resultado_ag2.get("terrenos", [])
        resumo = resultado_ag2.get("resumo", {})

        with log_area:
            st.success(f"✅ {contagem(resumo.get('cluster_a', 0), 'imóvel parecido', 'imóveis parecidos')} com o seu (mesma faixa de área e quartos)")

        if not comparaveis:
            status_box.error("❌ Nenhum imóvel comparável encontrado. O bairro pode ter poucos anúncios.")
            cabecalho.subheader("❌ Avaliação interrompida")
            aviso_cancelar.empty()
            st.stop()

        # Zona homogênea (~30s)
        zona_resultado = None
        if os.getenv("GOOGLE_MAPS_KEY"):
            status_box.info("📊 **Etapa 2/5 — Agente Identificador de Comparáveis** | Validando localização...")
            progress.progress(35)
            with log_area:
                st.write("**Agente Identificador** — Verificando quais estão na mesma vizinhança (zona homogênea)...")
            try:
                t2z = time.time()
                endereco = f"{rua}, {numero}, {bairro}, {cidade}, {estado}"
                zona_resultado = analisar_zona_homogenea(
                    endereco_alvo=endereco,
                    imoveis=[c for c in comparaveis if c.get("cluster") == "A"] + terrenos,
                    cidade=cidade,
                    estado=estado,
                    lat_alvo_precomp=imovel_alvo.get("lat"),
                    lon_alvo_precomp=imovel_alvo.get("lon"),
                    id_execucao=id_execucao,
                )
                confirmados = zona_resultado.get("comparaveis_confirmados", [])
                fora = zona_resultado.get("fora_zona", [])
                tempo_zona = time.time() - t2z
                total_analisados_zona = len(confirmados) + len(fora)
                raio_usado = (
                    zona_resultado.get("raio_final_m")
                    or zona_resultado.get("zona_homogenea", {}).get("raio_sugerido_metros")
                    or zona_resultado.get("zona_homogenea", {}).get("raio_metros") or 500
                )
                with log_area:
                    # Separa comparaveis e terrenos na zona pra log claro
                    terrenos_na_zona = [c for c in confirmados if (c.get("propertyType", "") or "").lower() in ("terrenos", "terreno", "lote", "residential_allotment_land", "allotment_land")]
                    comparaveis_na_zona = [c for c in confirmados if c not in terrenos_na_zona]
                    # Explica a diferenca para a contagem do calculo quando o anuncio do
                    # proprio imovel esta na zona (ele sai do calculo no Agente 5).
                    n_alvo_zona = anuncios_do_alvo_na_zona(
                        {"comparaveis": comparaveis, "terrenos": terrenos}, comparaveis_na_zona
                    )
                    st.success(
                        f"✅ Zona homogênea definida (raio {raio_usado} m): "
                        f"**{texto_comparaveis_na_zona(len(comparaveis_na_zona), n_alvo_zona)}** e "
                        f"**{contagem(len(terrenos_na_zona), 'terreno', 'terrenos')}**"
                    )
                    if texto_aviso_raio(zona_resultado):
                        st.caption(f"ℹ️ {texto_aviso_raio(zona_resultado)}")
                    if len(fora) > len(confirmados):
                        st.caption("ℹ️ Muitos imóveis foram descartados porque estão longe. O sistema só usa imóveis próximos para garantir que o valor reflete a sua vizinhança.")
            except Exception as e:
                falhas_execucao.append(f"zona_homogenea: {type(e).__name__}: {e}")
                with log_area:
                    st.warning(f"⚠️ Validação geográfica indisponível — continuando sem ela ({type(e).__name__}: {e})")

        progress.progress(45)

        # ==============================================================
        # ETAPAS 3 e 4 — Análise de qualidade + infraestrutura (~3 min)
        # ==============================================================
        progress.progress(50)
        with log_area:
            st.write("**Agente Analisador** — Avaliando qualidade dos imóveis (fotos e descrição)")
            st.write("**Agente Avaliador de Infraestrutura** — Mapeando o que tem perto (escolas, hospitais, comércio, transporte)")

        resultado_ag3 = {}
        resultado_ag4 = {}
        ag4_pronto = [False]
        ag3_pronto = [False]

        t34 = time.time()
        tempo_estimado_ag34 = 180  # ~3 minutos

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_ag3 = executor.submit(analisar_comparaveis, imovel_alvo, id_execucao=id_execucao)
            future_ag4 = executor.submit(avaliar_infraestrutura, id_execucao=id_execucao)

            # Contador enquanto espera
            while not (future_ag3.done() and future_ag4.done()):
                elapsed = time.time() - t34
                restante = max(0, tempo_estimado_ag34 - elapsed)
                pct = min(84, int(50 + (elapsed / tempo_estimado_ag34) * 35))
                progress.progress(pct)

                msgs = []
                if future_ag4.done() and not ag4_pronto[0]:
                    ag4_pronto[0] = True
                if future_ag3.done() and not ag3_pronto[0]:
                    ag3_pronto[0] = True

                if ag4_pronto[0] and not ag3_pronto[0]:
                    if restante > 60:
                        status_box.info(f"🔄 Infraestrutura ✅ | **Agente Analisador** analisando fotos dos imóveis... Faltam ~{int(restante)}s")
                    else:
                        status_box.info(f"🔄 Infraestrutura ✅ | **Agente Analisador** avaliando acabamento e conservação... Faltam ~{int(restante)}s")
                elif not ag4_pronto[0] and not ag3_pronto[0]:
                    if restante > 120:
                        status_box.info(f"🔄 **Agente Analisador + Agente Avaliador** | Buscando escolas, hospitais e comércio no entorno... Faltam ~{int(restante)}s")
                    elif restante > 60:
                        status_box.info(f"🔄 **Agente Analisador + Agente Avaliador** | Analisando fotos e descrições dos imóveis... Faltam ~{int(restante)}s")
                    else:
                        status_box.info(f"🔄 **Agente Analisador + Agente Avaliador** | Calculando scores de qualidade e infraestrutura... Faltam ~{int(restante)}s")
                else:
                    break

                time.sleep(3)

            # Coleta resultados
            try:
                resultado_ag4 = future_ag4.result()
                score_infra = resultado_ag4.get("scores", {}).get("score_final", 0)
                classif = resultado_ag4.get("scores", {}).get("classificacao_infraestrutura", "?")
                with log_area:
                    if resultado_ag4.get("status") == "endereco_nao_localizado":
                        st.warning(f"⚠️ {resultado_ag4.get('mensagem')}")
                    else:
                        st.success(f"✅ Mapeou escolas, hospitais, comércio e transporte no entorno. Classificação: **{classif}**")
                    if classif == "insuficiente":
                        st.caption("ℹ️ Classificação insuficiente indica pouco comércio, transporte ou serviços no raio de 1500m. Comum em bairros residenciais afastados.")
            except Exception as e:
                falhas_execucao.append(f"agente4: {type(e).__name__}: {e}")
                with log_area:
                    st.warning("⚠️ Agente Avaliador de Infraestrutura indisponível")

            try:
                resultado_ag3 = future_ag3.result()
                score_qual = resultado_ag3.get("resumo", {}).get("score_qualitativo_medio", 0)
                total_analisados = resultado_ag3.get("resumo", {}).get("total_analisados", 0)
                with log_area:
                    st.success(f"✅ Avaliou fotos e descrição de **{contagem(total_analisados, 'imóvel', 'imóveis')}** (estado de conservação, padrão de acabamento)")
                    if total_analisados <= 3:
                        st.caption("ℹ️ Poucos imóveis avaliados — o bairro tem poucos anúncios próximos ao seu endereço. O valor estimado pode ser menos preciso.")
            except Exception as e:
                falhas_execucao.append(f"agente3: {type(e).__name__}: {e}")
                with log_area:
                    st.warning("⚠️ Agente Analisador indisponível")

        tempo_ag34 = time.time() - t34
        progress.progress(85)

        # ==============================================================
        # ETAPA 5 — Cálculo do preço (instantâneo)
        # ==============================================================
        status_box.info("💰 **Etapa 5/5 — Agente Estimador de Preço e Liquidez** | Finalizando...")
        progress.progress(90)
        with log_area:
            st.write("**Agente Estimador de Preço** — Calculando o valor do seu imóvel com base nos preços da vizinhança...")

        resultado_ag5 = {}
        escopo_busca = imoveis_coletados[0].get("escopo_busca") if imoveis_coletados else None
        imovel_alvo["escopo_busca"] = escopo_busca   # so para o log do Agente 5
        try:
            resultado_ag5 = estimar_preco(imovel_alvo_extra=imovel_alvo, id_execucao=id_execucao)
            valor = (resultado_ag5.get("avaliacao_planilha") or resultado_ag5.get("avaliacao", {})).get("valor_medio_imovel", 0)
            liquidez_val = (resultado_ag5.get("avaliacao_planilha") or resultado_ag5.get("avaliacao", {})).get("valor_liquidez_arredondado", 0)
            tempo_venda = (resultado_ag5.get("liquidez_experimental") or resultado_ag5.get("liquidez", {})).get("tempo_estimado", "?")
            with log_area:
                if resultado_ag5.get("avaliacao_confiavel", True):
                    st.success("✅ Preço calculado")
                else:
                    st.warning("⚠️ Sem anúncios suficientes para um valor confiável (veja o motivo no resultado)")
        except Exception as e:
            falhas_execucao.append(f"agente5: {type(e).__name__}: {e}")
            with log_area:
                st.warning(f"⚠️ Agente Estimador indisponível")

        tempo_total = time.time() - inicio_total
        # Fim: o cabecalho vira "concluida" e saem a barra, o status e o aviso do F5.
        progress.empty()
        status_box.empty()
        aviso_cancelar.empty()
        cabecalho.subheader(f"✅ Avaliação concluída em {tempo_total:.0f} segundos")

        # Monta resultado para exibição
        # Enriquece resumo com dados da coleta
        resumo["total_coletados"] = len(imoveis_coletados)
        resumo["tempo_coleta_s"] = round(tempo_ag1, 1)
        # Conta portais (normaliza nomes)
        portais_count = {}
        for im in imoveis_coletados:
            # Os agentes gravam a origem em "source"; nenhum produz "portal".
            origem = str(im.get("source") or "").strip() or "Banco próprio"
            origem_lower = origem.lower()
            if "vivareal" in origem_lower or "viva real" in origem_lower:
                origem = "VivaReal"
            elif "lugar" in origem_lower:
                origem = "LugarCerto"
            elif "athena" in origem_lower or "s3" in origem_lower:
                origem = "Banco próprio"
            portais_count[origem] = portais_count.get(origem, 0) + 1
        resumo["portais"] = portais_count
        # Conta na rua vs bairro
        na_rua_count = sum(1 for im in imoveis_coletados if rua and rua.lower() in (im.get("street") or im.get("rua") or "").lower())
        resumo["na_rua"] = na_rua_count

        resumo["duplicatas_descartadas"] = len(duplicatas_descartadas)

        # Tudo o que o fim do fluxo usa (resultado, leilao, verificacoes, banco). Fica na
        # sessao: roda de novo quando a pessoa responde "Este anuncio e do seu imovel?".
        contexto = {
            "id_execucao": id_execucao, "imovel_alvo": imovel_alvo, "imoveis_coletados": imoveis_coletados,
            "escopo_busca": escopo_busca, "resumo": resumo, "duplicatas_descartadas": duplicatas_descartadas,
            "dados_leilao": dados_leilao, "alvo_sem_localizacao": alvo_sem_localizacao,
            "comparaveis": comparaveis, "terrenos": terrenos, "zona_resultado": zona_resultado,
            "resultado_ag2": resultado_ag2, "resultado_ag3": resultado_ag3, "resultado_ag4": resultado_ag4,
            "falhas": falhas_execucao, "localizacao_alvo": localizacao_alvo,
            "entrada_usuario": entrada_usuario, "tela_resultado": tela_resultado,
            "tempos": {
                "total": round(tempo_total, 1),
                "agente1": round(tempo_ag1, 1),
                "agente2": round(tempo_ag2_cluster, 1),
                "zona": round(locals().get("tempo_zona", 0.0), 1),
                "agentes3e4": round(tempo_ag34, 1),
            },
        }
        resultado = montar_resultado_final(contexto, resultado_ag5)

        # Salva no session_state pra não perder no rerun
        st.session_state["resultado"] = resultado
        st.session_state["imovel_alvo_dados"] = imovel_alvo
        st.session_state["contexto_avaliacao"] = contexto

    # Recupera resultado salvo (pra quando faz download sem perder)
    if "resultado" in st.session_state:
        resultado = st.session_state["resultado"]
        imovel_alvo_export = st.session_state.get("imovel_alvo_dados", {})

        # ============================================================
        # RESULTADO
        # ============================================================

        mostrar_resultado(resultado, imovel_alvo_export, tela_resultado,
                          ao_responder_anuncio_do_alvo=responder_anuncio_do_alvo)
