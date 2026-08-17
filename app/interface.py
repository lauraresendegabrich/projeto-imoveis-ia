"""
Interface Web — Precificação Imobiliária
=========================================

COMO RODAR:
    .venv/Scripts/streamlit.exe run app/interface.py
"""

import streamlit as st
import sys
import os
from pathlib import Path

# Adiciona raiz do projeto ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

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

    # ── BUSCA POR CEP ─────────────────────────────────────────
    st.markdown("**🔎 Buscar por CEP:**")
    cep_input = st.text_input("CEP (opcional)", value="", max_chars=9, placeholder="13015-100")
    preset = {}
    if cep_input and len(cep_input.replace("-", "")) == 8:
        import requests
        try:
            cep_limpo = cep_input.replace("-", "")
            r = requests.get(f"https://viacep.com.br/ws/{cep_limpo}/json/", timeout=5)
            if r.status_code == 200:
                dados_cep = r.json()
                if not dados_cep.get("erro"):
                    preset = {
                        "rua": dados_cep.get("logradouro", ""),
                        "bairro": dados_cep.get("bairro", ""),
                        "cidade": dados_cep.get("localidade", ""),
                        "estado": dados_cep.get("uf", ""),
                    }
                    st.success(f"✅ {dados_cep.get('logradouro', '')}, {dados_cep.get('bairro', '')}, {dados_cep.get('localidade', '')}/{dados_cep.get('uf', '')}")
                else:
                    st.warning("CEP não encontrado")
        except Exception:
            pass

    st.divider()

    with st.form("imovel_form"):
        st.markdown("**📍 Localização**")
        rua = st.text_input("Rua", value=preset.get("rua", ""))
        numero = st.text_input("Número", value=preset.get("numero", ""))
        bairro = st.text_input("Bairro", value=preset.get("bairro", ""))
        col_cidade, col_estado = st.columns([3, 1])
        with col_cidade:
            cidade = st.text_input("Cidade", value=preset.get("cidade", ""))
        with col_estado:
            estados_br = ["", "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
            estado_default = preset.get("estado", "")
            estado_idx = estados_br.index(estado_default) if estado_default in estados_br else 0
            estado = st.selectbox("UF", estados_br, index=estado_idx)

        st.markdown("**🏗️ Características**")
        tipo = st.selectbox("Tipo", ["Casa", "Apartamento"], index=["Casa", "Apartamento"].index(preset.get("tipo", "Casa")))
        col_a, col_b = st.columns(2)
        with col_a:
            area = st.number_input("Área construída (m²)", min_value=0, value=preset.get("area", 0))
            quartos = st.number_input("Quartos", min_value=0, value=preset.get("quartos", 0))
            vagas = st.number_input("Vagas", min_value=0, value=preset.get("vagas", 0))
        with col_b:
            terreno_default = 0 if tipo == "Apartamento" else preset.get("area_terreno", 0)
            area_terreno = st.number_input("Terreno (m²)", min_value=0, value=terreno_default)
            banheiros = st.number_input("Banheiros", min_value=0, value=preset.get("banheiros", 0))
            preco_anunciado = st.number_input("Preço (R$, opcional)", min_value=0, value=0, step=1000)

        st.markdown("**📝 Descrição** (opcional)")
        descricao = st.text_area("Descrição do imóvel", value="", height=80)

        st.markdown("**📸 Fotos do imóvel** (opcional, máx. 8)")
        st.caption("Adicione fotos para uma avaliação mais precisa.")
        link_anuncio = st.text_input("Link do anúncio (extrai fotos automaticamente)", value="", help="Cole o link do VivaReal/ZAP e as fotos serão extraídas")
        fotos_texto = st.text_area("Ou cole links das fotos (um por linha)", value="", height=60)

        submitted = st.form_submit_button("🚀 Avaliar Imóvel", use_container_width=True)

# ============================================================
# ÁREA PRINCIPAL — RESULTADOS
# ============================================================

st.title("📊 Precificação Imobiliária com IA")
st.markdown("Sistema multiagente que estima o valor do seu imóvel com base em dados reais do mercado.")


# ============================================================
# EXECUÇÃO DO PIPELINE
# ============================================================

if not submitted:
    # Tela inicial
    st.info("👈 Preencha os dados do imóvel na barra lateral e clique em **Avaliar Imóvel** para começar.")

    col_info1, col_info2, col_info3 = st.columns(3)
    with col_info1:
        st.markdown("### 🔍 Coleta")
        st.write("Busca imóveis similares à venda na mesma região")
    with col_info2:
        st.markdown("### 🧠 Análise")
        st.write("Avalia qualidade, infraestrutura e padrão da vizinhança")
    with col_info3:
        st.markdown("### 💰 Preço")
        st.write("Calcula valor de mercado e tempo estimado de venda")

    st.divider()
    st.caption("Cidades disponíveis no banco: Campinas, Indaiatuba, Guarulhos, Americana, Cotia, Jacareí, Bauru, Barueri, Atibaia, Itu (SP). Outras cidades usam coleta em tempo real.")

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
    if area <= 0:
        erros_validacao.append("Área construída deve ser maior que zero")
    if quartos <= 0:
        erros_validacao.append("Número de quartos deve ser maior que zero")

    if erros_validacao:
        st.error("❌ **Preencha todos os campos obrigatórios para iniciar a avaliação:**")
        for erro in erros_validacao:
            st.warning(f"• {erro}")
        st.stop()

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
        "description": descricao or f"{tipo} com {area}m², {quartos} quartos, {banheiros} banheiros, {vagas} vagas - {bairro}, {cidade}/{estado}",
        "images": [],
    }

    # Processa fotos conforme opção escolhida
    fotos_final = []
    if link_anuncio and ("vivareal" in link_anuncio or "zap" in link_anuncio):
        # Extrai fotos do link do anúncio
        import requests as req_fotos
        import re as re_fotos
        try:
            r = req_fotos.get(link_anuncio, timeout=10)
            if r.status_code == 200:
                hashes = re_fotos.findall(r'resizedimgs\.vivareal\.com/img/vr-listing/([a-f0-9]{32})/', r.text)
                hashes_unicos = list(dict.fromkeys(hashes))
                fotos_final = [
                    f"https://resizedimgs.vivareal.com/img/vr-listing/{h}/imovel.webp?action=fit-in&dimension=870x653"
                    for h in hashes_unicos[:8]
                ]
        except Exception:
            pass
    elif fotos_texto.strip():
        fotos_final = [url.strip() for url in fotos_texto.strip().split("\n") if url.strip()][:8]

    imovel_alvo["images"] = fotos_final

    if preco_anunciado > 0:
        imovel_alvo["price"] = preco_anunciado
        imovel_alvo["pricePerSqm"] = preco_anunciado / area if area > 0 else 0

    # Importa os agentes
    import os
    import time
    import threading
    from agents.collector import coletar_imoveis
    from agents.comparables import identificar_comparaveis, analisar_zona_homogenea
    from agents.text_analyzer import analisar_comparaveis
    from agents.infra_evaluator import avaliar_infraestrutura
    from agents.price_liquidity import estimar_preco
    from concurrent.futures import ThreadPoolExecutor, as_completed

    st.divider()
    st.subheader("⏳ Avaliação em andamento")
    st.caption("Para cancelar, pressione F5.")

    progress = st.progress(0)
    status_box = st.empty()
    log_area = st.container()

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
                status_box.info(f"🔍 **Agente Coletor de Dados** | Acessando portais imobiliários... Faltam ~{int(restante)}s")
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
        st.stop()

    progress.progress(20)
    with log_area:
        st.success(f"✅ {len(imoveis_coletados)} imóveis à venda encontrados na região")
        # Avisa se não encontrou na rua ou bairro
        if rua and imoveis_coletados:
            na_rua = sum(1 for im in imoveis_coletados if rua.lower() in (im.get("street") or im.get("rua") or "").lower())
            if na_rua > 0:
                st.caption(f"ℹ️ {na_rua} imóveis encontrados na mesma rua ({rua})")
            else:
                st.caption(f"ℹ️ Nenhum imóvel encontrado na mesma rua ({rua}). Usando imóveis do bairro.")
        if bairro and imoveis_coletados:
            no_bairro = sum(1 for im in imoveis_coletados if bairro.lower() in (im.get("neighborhood") or im.get("bairro") or "").lower())
            if no_bairro == 0:
                st.caption(f"ℹ️ Nenhum imóvel encontrado no bairro {bairro}. Usando imóveis da cidade toda.")

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
    )
    tempo_ag2_cluster = time.time() - t2

    comparaveis = resultado_ag2.get("comparaveis", [])
    terrenos = resultado_ag2.get("terrenos", [])
    resumo = resultado_ag2.get("resumo", {})

    with log_area:
        st.success(f"✅ {resumo.get('cluster_a', 0)} imóveis parecidos com o seu (mesma faixa de área, quartos e preço)")

    if not comparaveis:
        status_box.error("❌ Nenhum imóvel comparável encontrado. O bairro pode ter poucos anúncios.")
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
            )
            confirmados = zona_resultado.get("comparaveis_confirmados", [])
            fora = zona_resultado.get("fora_zona", [])
            tempo_zona = time.time() - t2z
            total_analisados_zona = len(confirmados) + len(fora)
            raio_usado = zona_resultado.get("zona_homogenea", {}).get("raio_sugerido_metros") or zona_resultado.get("zona_homogenea", {}).get("raio_metros") or 700
            with log_area:
                st.success(f"✅ Zona homogênea definida: **{len(confirmados)}** de {total_analisados_zona} imóveis estão na vizinhança (raio {raio_usado}m), {len(fora)} descartados por distância")
                if len(fora) > len(confirmados):
                    st.caption("ℹ️ Muitos imóveis foram descartados porque estão longe. O sistema só usa imóveis próximos para garantir que o valor reflete a sua vizinhança.")
        except Exception as e:
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
        future_ag3 = executor.submit(analisar_comparaveis, imovel_alvo)
        future_ag4 = executor.submit(avaliar_infraestrutura)

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
                st.success(f"✅ Mapeou escolas, hospitais, comércio e transporte no entorno. Classificação: **{classif}**")
                if classif == "insuficiente":
                    st.caption("ℹ️ Classificação insuficiente indica pouco comércio, transporte ou serviços no raio de 1500m. Comum em bairros residenciais afastados.")
        except Exception as e:
            with log_area:
                st.warning("⚠️ Agente Avaliador de Infraestrutura indisponível")

        try:
            resultado_ag3 = future_ag3.result()
            score_qual = resultado_ag3.get("resumo", {}).get("score_qualitativo_medio", 0)
            total_analisados = resultado_ag3.get("resumo", {}).get("total_analisados", 0)
            with log_area:
                st.success(f"✅ Avaliou fotos e descrição de **{total_analisados} imóveis** (estado de conservação, padrão de acabamento)")
                if total_analisados <= 3:
                    st.caption("ℹ️ Poucos imóveis avaliados — o bairro tem poucos anúncios próximos ao seu endereço. O valor estimado pode ser menos preciso.")
        except Exception as e:
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
    try:
        resultado_ag5 = estimar_preco(imovel_alvo_extra=imovel_alvo)
        valor = (resultado_ag5.get("avaliacao_planilha") or resultado_ag5.get("avaliacao", {})).get("valor_medio_imovel", 0)
        liquidez_val = (resultado_ag5.get("avaliacao_planilha") or resultado_ag5.get("avaliacao", {})).get("valor_liquidez_arredondado", 0)
        tempo_venda = (resultado_ag5.get("liquidez_experimental") or resultado_ag5.get("liquidez", {})).get("tempo_estimado", "?")
        with log_area:
            st.success(f"✅ Avaliação concluída!")
    except Exception as e:
        with log_area:
            st.warning(f"⚠️ Agente Estimador indisponível")

    tempo_total = time.time() - inicio_total
    progress.progress(100)
    status_box.success(f"🎉 **Avaliação concluída em {tempo_total:.0f} segundos!**")

    # Monta resultado para exibição
    resultado = {
        "status": "completo",
        "comparaveis": comparaveis,
        "terrenos": terrenos,
        "zona_homogenea": zona_resultado,
        "analise_qualitativa": resultado_ag3,
        "infraestrutura": resultado_ag4,
        "preco_estimado": resultado_ag5,
        "resumo": resumo,
    }

    # Salva no session_state pra não perder no rerun
    st.session_state["resultado"] = resultado
    st.session_state["imovel_alvo_dados"] = imovel_alvo

# Recupera resultado salvo (pra quando faz download sem perder)
if "resultado" in st.session_state and not submitted:
    resultado = st.session_state["resultado"]
    imovel_alvo = st.session_state.get("imovel_alvo_dados", {})

if "resultado" in st.session_state:
    resultado = st.session_state["resultado"]
    imovel_alvo_export = st.session_state.get("imovel_alvo_dados", {})

    # ============================================================
    # RESULTADO
    # ============================================================

    st.divider()
    st.subheader("📊 Resultado da Avaliação")

    # Preço estimado
    preco = resultado.get("preco_estimado", {})
    if preco and isinstance(preco, dict):
        avaliacao = preco.get("avaliacao_planilha") or preco.get("avaliacao", {})
        liquidez_info = preco.get("liquidez_experimental") or preco.get("liquidez", {})

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            valor_medio = avaliacao.get("valor_medio_imovel", 0)
            st.metric("💰 Valor Médio Estimado", f"R$ {valor_medio:,.0f}")
        with col_b:
            valor_liq = avaliacao.get("valor_liquidez", 0)
            st.metric("⚡ Valor de Liquidez (-10%)", f"R$ {valor_liq:,.2f}")
        with col_c:
            tempo = liquidez_info.get("tempo_estimado", "?")
            st.metric("⏱️ Tempo Estimado de Venda", tempo)

        # ==============================================================
        # COMO CHEGAMOS NESTE VALOR
        # ==============================================================
        st.divider()
        st.subheader("📖 Como chegamos neste valor")

        zona = resultado.get("zona_homogenea", {})
        zh = zona.get("zona_homogenea", {}) if zona else {}
        raio = zh.get("raio_metros") or zh.get("raio_sugerido_metros") or 400
        confirmados = zona.get("comparaveis_confirmados", []) if zona else []
        fora_zona = zona.get("fora_zona", []) if zona else []
        ag3_data = resultado.get("analise_qualitativa", {})
        resumo3 = ag3_data.get("resumo", {}) if ag3_data else {}
        infra_data = resultado.get("infraestrutura", {})
        scores_infra = infra_data.get("scores", {}) if infra_data else {}
        resumo_infra = scores_infra  # classificacao esta dentro de scores, nao em resumo_scores
        preco_data = resultado.get("preco_estimado", {})
        calc_constr = preco_data.get("calculo_construcao", {}) if preco_data else {}
        imovel_alvo_info = preco_data.get("imovel_alvo", {}) if preco_data else {}

        # Ag.1
        total_encontrados = resultado.get("resumo", {}).get("total_coletados", len(confirmados) + len(fora_zona))
        with st.expander("🔍 Agente Coletor de Dados"):
            st.write(f"Encontramos **{total_encontrados}** imóveis à venda no bairro {bairro}, {cidade}/{estado}.")

        # Ag.2
        cluster_a = resultado.get("resumo", {}).get("cluster_a", len(confirmados))
        cluster_b = resultado.get("resumo", {}).get("cluster_b", 0)
        terrenos_sep = resultado.get("resumo", {}).get("terrenos_excluidos", 0)
        with st.expander("📊 Agente Identificador de Comparáveis"):
            st.write(f"Dos {total_encontrados} imóveis encontrados:")
            if terrenos_sep > 0:
                st.write(f"- {terrenos_sep} são terrenos (separados para cálculo do m² do terreno — não entram na comparação)")
                st.write(f"- {total_encontrados - terrenos_sep} foram analisados pela inteligência artificial para identificar os mais parecidos com o seu")
            else:
                st.write(f"- Todos foram analisados pela inteligência artificial para identificar os mais parecidos com o seu")
            st.write(f"- **{cluster_a}** foram classificados como comparáveis (perfil similar ao seu)")
            if cluster_b > 0:
                st.write(f"- {cluster_b} foram descartados (perfil muito diferente: área, quartos ou padrão incompatível)")
            st.write(f"- Zona homogênea: **{len(confirmados)}** de {len(confirmados) + len(fora_zona)} analisados estão na mesma vizinhança (raio de {raio}m), {len(fora_zona)} descartados por distância")

            # Detalhes da zona homogênea
            st.markdown("---")
            st.caption("Zona homogênea — vizinhança com padrão construtivo parecido")
            if zh:
                st.write(f"- Raio utilizado: **{raio} metros**")
                st.write(f"- Padrão construtivo: {zh.get('padrao_construtivo', 'não disponível')}")
                st.write(f"- Homogeneidade visual: {zh.get('homogeneidade_visual', 'não disponível')}")
                st.write(f"- Densidade urbana: {zh.get('densidade_urbana', 'não disponível')}")
                justificativa_zh = zh.get("justificativa_raio") or zh.get("descricao_zona_homogenea", "")
                if "<think>" in str(justificativa_zh):
                    justificativa_zh = ""
                if justificativa_zh:
                    st.write(f"- Justificativa: {justificativa_zh}")

            # Imagem de satélite
            import os
            img_path = "data/satelite_zona_homogenea_ag2.png"
            if os.path.exists(img_path):
                st.image(img_path, caption="Imagem de satélite com marcador no imóvel alvo", use_container_width=True)

            # Tabela de comparáveis
            st.markdown("---")
            st.caption("Imóveis usados no cálculo")
            # Usa comparáveis do Ag.3 (têm análise qualitativa) se disponível
            ag3_comps = resultado.get("analise_qualitativa", {})
            comparaveis_tabela = ag3_comps.get("comparaveis", []) if ag3_comps else []
            # Fallback: zona homogênea (sem análise qualitativa)
            if not comparaveis_tabela:
                zona_data = resultado.get("zona_homogenea", {})
                comparaveis_tabela = zona_data.get("comparaveis_confirmados", []) if zona_data else resultado.get("comparaveis", [])
            if comparaveis_tabela:
                import pandas as pd
                dados_tabela = []
                for comp in comparaveis_tabela:
                    url_comp = comp.get("url", "")
                    link = f"[ver]({url_comp})" if url_comp else ""
                    analise = comp.get("analise_qualitativa", {})
                    estado_cons = analise.get("estado_conservacao", "-")
                    padrao_tab = analise.get("padrao_acabamento", "-")
                    score_q = analise.get("scores", {}).get("score_qualitativo", "-")
                    # Preço: tenta price (float) ou preco (string do Athena)
                    preco_val = comp.get("price") or comp.get("preco") or 0
                    try:
                        preco_val = float(preco_val)
                    except (ValueError, TypeError):
                        preco_val = 0
                    dados_tabela.append({
                        "Preço": f"R$ {preco_val:,.0f}" if preco_val else "-",
                        "Área": f"{comp.get('area') or comp.get('area_construida', 0)}m²",
                        "Quartos": comp.get("bedrooms") or comp.get("quartos", "?"),
                        "Bairro": comp.get("neighborhood") or comp.get("bairro", "?"),
                        "Estado": estado_cons,
                        "Padrão": padrao_tab,
                        "Score": score_q,
                        "Anúncio": link,
                    })
                df = pd.DataFrame(dados_tabela)
                st.markdown(df.to_markdown(index=False), unsafe_allow_html=True)

                # Gráfico scatter: Preço × Área (com valor estimado do alvo)
                precos_scatter = []
                areas_scatter = []
                nomes_scatter = []
                for c in comparaveis_tabela:
                    p = c.get("price") or c.get("preco") or 0
                    a = c.get("area") or c.get("area_construida") or 0
                    try:
                        p = float(p)
                        a = float(a)
                        if p > 0 and a > 0:
                            precos_scatter.append(p)
                            areas_scatter.append(a)
                            rua_c = c.get("street") or c.get("rua") or c.get("neighborhood") or "?"
                            nomes_scatter.append(rua_c[:25])
                    except (ValueError, TypeError):
                        pass
                if precos_scatter:
                    import plotly.graph_objects as go
                    fig = go.Figure()
                    # Comparáveis
                    fig.add_trace(go.Scatter(
                        x=areas_scatter, y=precos_scatter,
                        mode="markers",
                        marker=dict(size=10, color="#636EFA"),
                        text=nomes_scatter,
                        hovertemplate="<b>%{text}</b><br>Área: %{x}m²<br>Preço: R$ %{y:,.0f}<extra></extra>",
                        name="Comparáveis",
                    ))
                    # Valor estimado do alvo
                    area_alvo = imovel_alvo.get("area", 0) or 0
                    valor_est = (resultado.get("preco_estimado", {}).get("avaliacao_planilha") or {}).get("valor_medio_imovel", 0)
                    if area_alvo and valor_est:
                        fig.add_trace(go.Scatter(
                            x=[float(area_alvo)], y=[float(valor_est)],
                            mode="markers",
                            marker=dict(size=14, color="#EF553B", symbol="diamond"),
                            hovertemplate="<b>Seu imóvel</b><br>Área: %{x}m²<br>Valor estimado: R$ %{y:,.0f}<extra></extra>",
                            name="Valor estimado",
                        ))
                    # Linha de tendência se 3+ pontos
                    if len(precos_scatter) >= 3:
                        import numpy as np
                        z = np.polyfit(areas_scatter, precos_scatter, 1)
                        x_line = [min(areas_scatter) * 0.9, max(areas_scatter) * 1.1]
                        y_line = [z[0] * x + z[1] for x in x_line]
                        fig.add_trace(go.Scatter(
                            x=x_line, y=y_line,
                            mode="lines",
                            line=dict(dash="dash", color="gray", width=1),
                            name="Tendência",
                            hoverinfo="skip",
                        ))
                    fig.update_layout(
                        xaxis_title="Área (m²)",
                        yaxis_title="Preço (R$)",
                        height=300,
                        margin=dict(l=20, r=20, t=30, b=20),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    )
                    st.plotly_chart(fig, use_container_width=True)

        # Ag.3
        score_medio = resumo3.get("score_qualitativo_medio", 0) or 0
        total_analisados = resumo3.get("total_analisados", 0) or 0
        alvo_analise = ag3_data.get("imovel_alvo", {}).get("analise_qualitativa", {}) if ag3_data else {}
        estado_alvo = alvo_analise.get("estado_conservacao", "?")
        padrao_alvo = alvo_analise.get("padrao_acabamento", "?")
        with st.expander("📝 Agente Analisador de Qualidade"):
            # Análise do imóvel alvo (destaque principal)
            if alvo_analise:
                score_alvo = alvo_analise.get("scores", {}).get("score_qualitativo", "?")
                classif_alvo = alvo_analise.get("classificacao_qualitativa", "?")
                st.markdown(f"**Seu imóvel:** estado **{estado_alvo}** | padrão **{padrao_alvo}** | score **{score_alvo}** ({classif_alvo})")

                # Justificativa
                justificativa = alvo_analise.get("justificativa", "")
                if justificativa:
                    st.info(f"💡 {justificativa}")

                # Pontos positivos
                positivos = alvo_analise.get("pontos_positivos", [])
                if positivos:
                    st.markdown("✅ **Pontos positivos:**")
                    for p in positivos:
                        st.markdown(f"- {p}")

                # Pontos negativos
                negativos = alvo_analise.get("pontos_negativos", [])
                if negativos:
                    st.markdown("⚠️ **Pontos de atenção:**")
                    for n in negativos:
                        st.markdown(f"- {n}")

                # Observações
                observacoes = alvo_analise.get("observacoes", [])
                if observacoes:
                    for obs in observacoes:
                        st.caption(f"ℹ️ {obs}")

            # Resumo da vizinhança
            if total_analisados > 0:
                st.markdown("---")
                n_label = "imóvel" if total_analisados == 1 else "imóveis"
                st.caption(f"📊 Vizinhança: {total_analisados} {n_label} analisado{'s' if total_analisados > 1 else ''} | Score médio da região: {score_medio:.2f}")

        # Ag.4
        score_final_infra = scores_infra.get("score_final", 0) or 0
        classif_infra = resumo_infra.get("classificacao_infraestrutura", "?")
        with st.expander("🏥 Agente Avaliador de Infraestrutura"):
            st.write(f"O entorno do seu imóvel tem infraestrutura **{classif_infra}** (score {score_final_infra:.2f}).")

            # Explicação do score
            if score_final_infra >= 0.70:
                st.success("Região com excelente infraestrutura — tem escolas, hospitais, comércio e transporte perto.")
            elif score_final_infra >= 0.50:
                st.info("Região com boa infraestrutura — tem o básico por perto, mas pode faltar algo em alguma categoria.")
            elif score_final_infra >= 0.30:
                st.warning("Região com infraestrutura regular — poucas opções de serviços no entorno.")
            else:
                st.error("Região com infraestrutura insuficiente — pouco comércio, transporte ou serviços próximos.")

            # Gráfico radar
            infra_full = resultado.get("infraestrutura", {})
            if infra_full:
                scores_cat = {k: v for k, v in infra_full.get("scores", {}).items() if isinstance(v, (int, float)) and k != "score_final"}
                if scores_cat:
                    import plotly.graph_objects as go
                    categorias = list(scores_cat.keys())
                    valores_radar = list(scores_cat.values())
                    fig = go.Figure(data=go.Scatterpolar(
                        r=valores_radar + [valores_radar[0]],
                        theta=categorias + [categorias[0]],
                        fill="toself",
                        name="Infraestrutura"
                    ))
                    fig.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                        showlegend=False, height=300, margin=dict(l=40, r=40, t=20, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # POIs por faixa
                pois = infra_full.get("pois_por_faixa", {})
                if pois:
                    st.markdown("---")
                    st.caption("O que tem perto")
                    for faixa_nome, faixa_label in [("microentorno_imediato", "0 a 400m"), ("entorno_caminhavel", "401 a 800m"), ("infraestrutura_ampliada", "801 a 1500m")]:
                        faixa = pois.get(faixa_nome, {})
                        total_faixa = sum(len(v) for v in faixa.values() if isinstance(v, list))
                        if total_faixa > 0:
                            st.markdown(f"**{faixa_label} ({total_faixa} pontos):**")
                            for cat, items in faixa.items():
                                if items and isinstance(items, list):
                                    nomes = [f"{p.get('nome', '?')} ({p.get('distancia_metros', '?')}m)" for p in items[:5]]
                                    st.write(f"  {cat}: {', '.join(nomes)}")

        # Ag.5
        m2_ref = calc_constr.get("valor_m2_referencia", 0) or 0
        padrao_usado = calc_constr.get("padrao_usado", "todos os comparáveis")
        area_calc = calc_constr.get("area_construida_m2", 0) or 0
        valor_med = avaliacao.get("valor_medio_imovel", 0)
        valor_liq = avaliacao.get("valor_liquidez", 0)
        with st.expander("💰 Agente Estimador de Preço"):
            st.write(f"Com base nos imóveis da vizinhança de padrão **{padrao_usado}**, o valor médio do m² é **R$ {m2_ref:,.2f}**.")
            st.write(f"Para o seu imóvel de {area_calc:.0f}m²:")
            st.write(f"- Valor médio estimado: **R$ {valor_med:,.0f}**")
            st.write(f"- Valor de liquidez (-10%): **R$ {valor_liq:,.0f}**")
            st.write(f"- Tempo estimado de venda: **{tempo}**")

            # Detalhes do cálculo
            st.markdown("---")
            st.caption("Detalhes do cálculo:")
            col_d, col_e = st.columns(2)
            with col_d:
                st.markdown("**Terreno**")
                calc_terreno = preco.get("calculo_terreno", {})
                st.write(f"- Aplicado: {'Sim' if calc_terreno.get('aplicado') else 'Não'}")
                st.write(f"- M² referência: R$ {calc_terreno.get('valor_m2_referencia', 0):,.2f}")
                st.write(f"- Área: {calc_terreno.get('area_terreno_m2', 0)} m²")
                st.write(f"- Valor médio: R$ {calc_terreno.get('valor_terreno_medio', 0):,.2f}")
            with col_e:
                st.markdown("**Construção**")
                calc_constr_det = preco.get("calculo_construcao", {})
                st.write(f"- Padrão: {calc_constr_det.get('padrao_usado', '?')}")
                st.write(f"- M² referência: R$ {calc_constr_det.get('valor_m2_referencia', 0):,.2f}")
                st.write(f"- Área: {calc_constr_det.get('area_construida_m2', 0)} m²")
                st.write(f"- Valor médio: R$ {calc_constr_det.get('valor_construcao_medio', 0):,.2f}")
            st.write(f"**Método:** {preco.get('metodo_estatistico', '?')}")

            # Comparação com preço anunciado
            if imovel_alvo_export.get("price") and imovel_alvo_export["price"] > 0:
                st.markdown("---")
                preco_anunc = imovel_alvo_export["price"]
                if valor_med > 0:
                    diferenca_pct = ((preco_anunc - valor_med) / valor_med) * 100
                    if diferenca_pct > 5:
                        st.warning(f"O preço anunciado (R$ {preco_anunc:,.0f}) está {diferenca_pct:.1f}% acima do valor médio da região (R$ {valor_med:,.0f})")
                    elif diferenca_pct < -5:
                        st.success(f"O preço anunciado (R$ {preco_anunc:,.0f}) está {abs(diferenca_pct):.1f}% abaixo do valor médio da região (R$ {valor_med:,.0f}) — boa oportunidade")
                    else:
                        st.info(f"O preço anunciado (R$ {preco_anunc:,.0f}) está alinhado com o valor médio da região (R$ {valor_med:,.0f}) — diferença de {abs(diferenca_pct):.1f}%")

        st.divider()

        # ── BOTÃO EXPORTAR PDF ─────────────────────────────────────
        laudo_texto = f"""LAUDO DE AVALIAÇÃO IMOBILIÁRIA
{'='*50}

Imóvel: {rua}, {numero} - {bairro}, {cidade}/{estado}
Tipo: {tipo} | Área: {area}m² | Terreno: {area_terreno}m²
Quartos: {quartos} | Banheiros: {banheiros} | Vagas: {vagas}

RESULTADO DA AVALIAÇÃO
{'-'*50}
Valor Médio Estimado: R$ {avaliacao.get('valor_medio_imovel', 0):,.2f}
Valor de Liquidez (-10%): R$ {avaliacao.get('valor_liquidez', 0):,.2f}
Tempo Estimado de Venda: {liquidez_info.get('tempo_estimado', '?')}

MÉTODO
{'-'*50}
{preco.get('metodo_estatistico', '?')}
{preco.get('justificativa', '')}

Gerado automaticamente pelo Sistema Multiagente de Precificação Imobiliária.
"""
        st.download_button(
            label="📄 Exportar Laudo (TXT)",
            data=laudo_texto,
            file_name=f"laudo_{cidade}_{bairro}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    else:
        st.error("Não foi possível calcular o preço. Verifique os dados e tente novamente.")
        if isinstance(resultado, dict):
            st.json(resultado)
