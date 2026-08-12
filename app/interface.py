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
        tipo = st.selectbox("Tipo", ["Casa", "Apartamento", "Terreno"], index=["Casa", "Apartamento", "Terreno"].index(preset.get("tipo", "Casa")))
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
    if area <= 0 and tipo != "Terreno":
        erros_validacao.append("Área construída deve ser maior que zero")
    if area_terreno <= 0 and tipo == "Terreno":
        erros_validacao.append("Área do terreno deve ser maior que zero para terrenos")
    if quartos <= 0 and tipo != "Terreno":
        erros_validacao.append("Número de quartos deve ser maior que zero")

    if erros_validacao:
        st.error("❌ **Preencha todos os campos obrigatórios para iniciar a avaliação:**")
        for erro in erros_validacao:
            st.warning(f"• {erro}")
        st.stop()

    # Monta o dict do imóvel alvo
    tipo_map = {"Casa": "house", "Apartamento": "apartment", "Terreno": "house"}
    property_type_map = {"Casa": "Casas", "Apartamento": "Apartamentos", "Terreno": "Terrenos"}

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
        st.success(f"✅ **Agente Coletor** — {len(imoveis_coletados)} imóveis à venda encontrados na região")
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
        st.success(f"✅ **Agente Identificador** — {resumo.get('cluster_a', 0)} imóveis parecidos com o seu (mesma faixa de área, quartos e preço)")

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
                st.success(f"✅ **Agente Identificador** — Zona homogênea definida: **{len(confirmados)}** de {total_analisados_zona} imóveis estão na vizinhança (raio {raio_usado}m), {len(fora)} descartados por distância")
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
            classif = resultado_ag4.get("resumo_scores", {}).get("classificacao_infraestrutura", "?")
            with log_area:
                st.success(f"✅ **Agente Avaliador de Infraestrutura** — Mapeou escolas, hospitais, comércio e transporte no entorno. Classificação: **{classif}**")
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
                st.success(f"✅ **Agente Analisador** — Avaliou fotos e descrição de **{total_analisados} imóveis** (estado de conservação, padrão de acabamento)")
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
        valor = resultado_ag5.get("avaliacao", {}).get("valor_medio_imovel", 0)
        liquidez_val = resultado_ag5.get("avaliacao", {}).get("valor_liquidez_arredondado", 0)
        tempo_venda = resultado_ag5.get("liquidez", {}).get("tempo_estimado", "?")
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
        avaliacao = preco.get("avaliacao", {})
        liquidez_info = preco.get("liquidez", {})

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
        resumo_infra = infra_data.get("resumo_scores", {}) if infra_data else {}
        preco_data = resultado.get("preco_estimado", {})
        calc_constr = preco_data.get("calculo_construcao", {}) if preco_data else {}
        imovel_alvo_info = preco_data.get("imovel_alvo", {}) if preco_data else {}

        # Ag.1
        total_encontrados = resultado.get("resumo", {}).get("total_coletados", len(confirmados) + len(fora_zona))
        st.markdown(f"**🔍 Agente Coletor de Dados**")
        st.write(f"Encontramos **{total_encontrados}** imóveis à venda no bairro {bairro}, {cidade}/{estado}.")

        # Ag.2
        cluster_a = resultado.get("resumo", {}).get("cluster_a", len(confirmados))
        cluster_b = resultado.get("resumo", {}).get("cluster_b", 0)
        terrenos_sep = resultado.get("resumo", {}).get("terrenos_excluidos", 0)
        st.markdown(f"**📊 Agente Identificador de Comparáveis**")
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

        # Ag.3
        score_medio = resumo3.get("score_qualitativo_medio", 0) or 0
        total_analisados = resumo3.get("total_analisados", 0) or 0
        alvo_analise = ag3_data.get("imovel_alvo", {}).get("analise_qualitativa", {}) if ag3_data else {}
        estado_alvo = alvo_analise.get("estado_conservacao", "?")
        padrao_alvo = alvo_analise.get("padrao_acabamento", "?")
        st.markdown(f"**📝 Agente Analisador**")
        st.write(f"Analisamos fotos e descrição de **{total_analisados}** imóveis da vizinhança. Score médio de qualidade: **{score_medio:.2f}**. O seu imóvel foi classificado como: **{estado_alvo}, {padrao_alvo}**.")

        # Ag.4
        score_final_infra = scores_infra.get("score_final", 0) or 0
        classif_infra = resumo_infra.get("classificacao_infraestrutura", "?")
        st.markdown(f"**🏥 Agente Avaliador de Infraestrutura**")
        st.write(f"O entorno do seu imóvel tem infraestrutura **{classif_infra}** (score {score_final_infra:.2f}).")

        # Ag.5
        m2_ref = calc_constr.get("valor_m2_referencia", 0) or 0
        padrao_usado = calc_constr.get("padrao_usado", "?")
        area_calc = calc_constr.get("area_construida_m2", 0) or 0
        valor_med = avaliacao.get("valor_medio_imovel", 0)
        valor_liq = avaliacao.get("valor_liquidez", 0)
        st.markdown(f"**💰 Agente Estimador de Preço**")
        st.write(f"Com base nos imóveis da vizinhança de padrão **{padrao_usado}**, o valor médio do m² é **R$ {m2_ref:,.2f}**. Para o seu imóvel de {area_calc:.0f}m²:")
        st.write(f"- Valor médio estimado: **R$ {valor_med:,.0f}**")
        st.write(f"- Valor de liquidez (-10%): **R$ {valor_liq:,.0f}**")
        st.write(f"- Tempo estimado de venda: **{tempo}**")

        st.divider()

        # Zona homogênea
        with st.expander("📍 Zona Homogênea"):

            st.caption("A zona homogênea é a vizinhança ao redor do seu imóvel com padrão construtivo parecido. Só imóveis dentro dessa zona são usados para calcular o valor.")
            zona = resultado.get("zona_homogenea", {})
            if zona:
                zh = zona.get("zona_homogenea", {})
                raio = zh.get("raio_metros") or zh.get("raio_sugerido_metros") or 400
                st.write(f"- Raio utilizado: **{raio} metros**")
                st.write(f"- Padrão construtivo: {zh.get('padrao_construtivo', 'não disponível')}")
                st.write(f"- Homogeneidade visual: {zh.get('homogeneidade_visual', 'não disponível')}")
                st.write(f"- Densidade urbana: {zh.get('densidade_urbana', 'não disponível')}")
                if zh.get("justificativa_raio"):
                    st.write(f"- Justificativa: {zh.get('justificativa_raio')}")
                confirmados = zona.get("comparaveis_confirmados", [])
                fora = zona.get("fora_zona", [])
                st.write(f"- Imóveis dentro da zona: **{len(confirmados)}**")
                st.write(f"- Imóveis descartados (fora do raio): {len(fora)}")
            else:
                st.write("Zona homogênea não disponível nesta execução")

        # Detalhes
        with st.expander("📐 Detalhes do Cálculo"):
            st.caption("Mostra como o valor foi calculado: o sistema separa o preço do terreno e da construção, usando a média dos imóveis da vizinhança (removendo valores extremos).")
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
                calc_constr = preco.get("calculo_construcao", {})
                st.write(f"- Padrão: {calc_constr.get('padrao_usado', '?')}")
                st.write(f"- M² referência: R$ {calc_constr.get('valor_m2_referencia', 0):,.2f}")
                st.write(f"- Área: {calc_constr.get('area_construida_m2', 0)} m²")
                st.write(f"- Valor médio: R$ {calc_constr.get('valor_construcao_medio', 0):,.2f}")

            st.markdown("**Método:** " + preco.get("metodo_estatistico", "?"))

        with st.expander("🏥 Infraestrutura da Região"):
            st.caption("Avalia o que existe perto do imóvel: escolas, hospitais, comércio, transporte público e lazer. Quanto mais infraestrutura, mais valorizado é o imóvel.")
            infra = resultado.get("infraestrutura", {})
            if infra:
                scores = infra.get("scores", {})
                resumo = infra.get("resumo_scores", {})
                score_infra = scores.get("score_final", 0)
                st.write(f"- Score final: **{score_infra}**")
                st.write(f"- Classificação: **{resumo.get('classificacao_infraestrutura', 'não disponível')}**")
                st.write(f"- Perfil: {resumo.get('perfil_regiao') or 'não disponível'}")
                st.write(f"- Impacto no valor: {resumo.get('impacto_estimado_no_valor') or 'não disponível'}")
                tempo_reg = resumo.get('tempo_liquidez_regional')
                st.write(f"- Tempo estimado de venda na região: {tempo_reg or 'não disponível'}")

                # Explicação do score
                if score_infra >= 0.70:
                    st.success("Região com excelente infraestrutura — tem escolas, hospitais, comércio e transporte perto. Isso valoriza o imóvel.")
                elif score_infra >= 0.50:
                    st.info("Região com boa infraestrutura — tem o básico por perto, mas pode faltar algo em alguma categoria.")
                elif score_infra >= 0.30:
                    st.warning("Região com infraestrutura regular — poucas opções de serviços no entorno. Pode demorar mais pra vender.")
                else:
                    st.error("Região com infraestrutura insuficiente — pouco comércio, transporte ou serviços próximos. Comum em bairros residenciais afastados ou praias.")

                pontos = resumo.get("pontos_fortes", [])
                if pontos:
                    st.markdown("**Pontos fortes:**")
                    for p in pontos:
                        st.write(f"  ✓ {p}")

                # Gráfico radar de infraestrutura
                scores_cat = {k: v for k, v in scores.items() if k not in ("score_final", "transporte_dados_insuficientes", "transporte_status")}
                if scores_cat:
                    import plotly.graph_objects as go
                    categorias = list(scores_cat.keys())
                    valores = list(scores_cat.values())
                    fig = go.Figure(data=go.Scatterpolar(
                        r=valores + [valores[0]],
                        theta=categorias + [categorias[0]],
                        fill="toself",
                        name="Infraestrutura"
                    ))
                    fig.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                        showlegend=False, height=300, margin=dict(l=40, r=40, t=20, b=20)
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("Infraestrutura não disponível")

        with st.expander("📝 Qualidade dos Imóveis Comparáveis"):
            st.caption("Avalia o estado de conservação, padrão de acabamento e diferenciais dos imóveis da região (usando fotos e descrição dos anúncios).")
            ag3 = resultado.get("analise_qualitativa", {})
            if ag3:
                resumo3 = ag3.get("resumo", {})
                score_med = resumo3.get("score_qualitativo_medio", 0)
                total = resumo3.get("total_analisados", 0)
                st.write(f"- Imóveis analisados: **{total}**")
                st.write(f"- Score médio da região: **{score_med}**")

                # Explica o motivo do score
                score_med = score_med or 0
                if score_med >= 0.80:
                    st.success("A região tem imóveis em excelente estado — alto padrão, bem conservados, com muitos diferenciais.")
                elif score_med >= 0.60:
                    st.info("A região tem imóveis em bom estado — padrão médio a alto, conservados, com alguns diferenciais.")
                elif score_med >= 0.40:
                    st.warning("A região tem imóveis em estado neutro — sem evidências claras de qualidade superior ou inferior. Pode indicar falta de fotos nos anúncios.")
                else:
                    st.error("A região tem imóveis em estado abaixo da média — conservação regular ou acabamento simples.")
            else:
                st.write("Análise qualitativa não disponível")

        with st.expander("📋 Comparáveis Usados no Cálculo"):
            st.caption("Imóveis confirmados na zona homogênea que foram usados para calcular o valor do seu.")
            zona_data = resultado.get("zona_homogenea", {})
            comparaveis = zona_data.get("comparaveis_confirmados", []) if zona_data else resultado.get("comparaveis", [])
            if comparaveis:
                # Tabela com link incluso
                import pandas as pd
                dados_tabela = []
                for comp in comparaveis:
                    url_comp = comp.get("url", "")
                    link = f"[ver]({url_comp})" if url_comp else ""
                    analise = comp.get("analise_qualitativa", {})
                    estado_cons = analise.get("estado_conservacao", "-")
                    padrao = analise.get("padrao_acabamento", "-")
                    score_q = analise.get("scores", {}).get("score_qualitativo", "-")
                    dados_tabela.append({
                        "Preço": f"R$ {comp.get('price', 0):,.0f}",
                        "Área": f"{comp.get('area', 0)}m²",
                        "Quartos": comp.get("bedrooms", "?"),
                        "Bairro": comp.get("neighborhood", "?"),
                        "Estado": estado_cons,
                        "Padrão": padrao,
                        "Score": score_q,
                        "Anúncio": link,
                    })
                df = pd.DataFrame(dados_tabela)
                st.markdown(df.to_markdown(index=False), unsafe_allow_html=True)

                # Gráfico de preços
                precos = [c.get("price", 0) for c in comparaveis if c.get("price")]
                if precos:
                    st.markdown("**Distribuição de preços dos comparáveis:**")
                    import plotly.express as px
                    fig = px.histogram(x=precos, nbins=10, labels={"x": "Preço (R$)", "y": "Quantidade"})
                    fig.update_layout(showlegend=False, height=250, margin=dict(l=20, r=20, t=20, b=20))
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.write("Nenhum comparável encontrado")

        # Justificativa
        st.markdown(f"> {preco.get('justificativa', '')}")

        # ==============================================================
        # SEÇÕES EXTRAS
        # ==============================================================

        # 1. Análise do Imóvel Alvo
        with st.expander("🏠 Análise do Seu Imóvel"):
            ag3_data = resultado.get("analise_qualitativa", {})
            alvo_data = ag3_data.get("imovel_alvo", {}) if ag3_data else {}
            analise_alvo = alvo_data.get("analise_qualitativa", {})
            if analise_alvo:
                st.write(f"- Estado de conservação: **{analise_alvo.get('estado_conservacao', 'não avaliado')}**")
                st.write(f"- Padrão de acabamento: **{analise_alvo.get('padrao_acabamento', 'não avaliado')}**")
                st.write(f"- Score qualitativo: **{analise_alvo.get('scores', {}).get('score_qualitativo', '?')}**")
                st.write(f"- Classificação: **{analise_alvo.get('classificacao_qualitativa', '?')}**")
                positivos = analise_alvo.get("pontos_positivos", [])
                if positivos:
                    st.markdown("**Pontos positivos:**")
                    st.write(", ".join(positivos))
                negativos = analise_alvo.get("pontos_negativos", [])
                if negativos:
                    st.markdown("**Pontos negativos:**")
                    st.write(", ".join(negativos))
                obs = analise_alvo.get("observacoes", [])
                if obs:
                    st.markdown("**Observações:**")
                    for o in obs:
                        # Substitui mensagem técnica por amigável
                        if "LLM Vision indisponivel" in str(o):
                            o = "Nenhuma foto disponível para análise visual. A avaliação foi feita apenas com base no texto."
                        st.write(f"• {o}")
            else:
                st.write("Análise do imóvel alvo não disponível (insira fotos para uma análise mais completa)")

        # 2. M² da Região
        with st.expander("💵 Valor do M² na Região"):
            m2_zona = preco.get("valor_m2_zona_homogenea", {})
            terreno_m2 = m2_zona.get("terreno", {})
            constr_m2 = m2_zona.get("construcao_por_padrao", {})
            if terreno_m2.get("quantidade_amostras", 0) > 0:
                st.write(f"**M² do terreno:**")
                st.write(f"- Referência: **R$ {terreno_m2.get('valor_m2_referencia', 0):,.2f}/m²**")
                st.write(f"- Menor valor: R$ {terreno_m2.get('menor_valor_m2', 0):,.2f}/m²")
                st.write(f"- Amostras: {terreno_m2.get('quantidade_amostras', 0)} terrenos")
            else:
                st.write("M² do terreno: não disponível (sem terrenos na zona)")
            st.write("")
            st.write(f"**M² da construção (padrão {constr_m2.get('padrao_usado', '?')}):**")
            st.write(f"- Referência: **R$ {constr_m2.get('valor_m2_referencia_usado', 0):,.2f}/m²**")
            st.write(f"- Menor valor: R$ {constr_m2.get('menor_valor_m2_usado', 0):,.2f}/m²")
            st.write(f"- Método: {preco.get('metodo_estatistico', '?')}")

        # 3. Comparação com preço anunciado
        if imovel_alvo.get("price") and imovel_alvo["price"] > 0:
            with st.expander("📊 Comparação com Preço Anunciado"):
                preco_anunc = imovel_alvo["price"]
                valor_med = avaliacao.get("valor_medio_imovel", 0)
                if valor_med > 0:
                    diferenca_pct = ((preco_anunc - valor_med) / valor_med) * 100
                    if diferenca_pct > 5:
                        st.warning(f"O preço anunciado (R$ {preco_anunc:,.0f}) está {diferenca_pct:.1f}% acima do valor médio da região (R$ {valor_med:,.0f})")
                    elif diferenca_pct < -5:
                        st.success(f"O preço anunciado (R$ {preco_anunc:,.0f}) está {abs(diferenca_pct):.1f}% abaixo do valor médio da região (R$ {valor_med:,.0f}) — boa oportunidade")
                    else:
                        st.info(f"O preço anunciado (R$ {preco_anunc:,.0f}) está alinhado com o valor médio da região (R$ {valor_med:,.0f}) — diferença de {abs(diferenca_pct):.1f}%")

        # 4. Imagem de satélite
        with st.expander("🛰️ Imagem de Satélite da Região"):
            import os
            img_path = "data/satelite_zona_homogenea_ag2.png"
            if os.path.exists(img_path):
                st.image(img_path, caption="Imagem de satélite com marcador no imóvel alvo", use_container_width=True)
            else:
                st.write("Imagem de satélite não disponível nesta execução")

        # 5. POIs por faixa de distância
        with st.expander("📍 O que tem perto (escolas, hospitais, comércio)"):
            infra_data = resultado.get("infraestrutura", {})
            pois = infra_data.get("pois_por_faixa", {})
            if pois:
                for faixa_nome, faixa_label in [("microentorno_imediato", "0 a 400m"), ("entorno_caminhavel", "401 a 800m"), ("infraestrutura_ampliada", "801 a 1500m")]:
                    faixa = pois.get(faixa_nome, {})
                    total_faixa = sum(len(v) for v in faixa.values() if isinstance(v, list))
                    if total_faixa > 0:
                        st.markdown(f"**{faixa_label} ({total_faixa} pontos):**")
                        for cat, items in faixa.items():
                            if items and isinstance(items, list):
                                nomes = [f"{p.get('nome', '?')} ({p.get('distancia_metros', '?')}m)" for p in items[:5]]
                                st.write(f"  {cat}: {', '.join(nomes)}")
                        st.write("")
                # Transporte
                transporte = infra_data.get("transporte", {})
                paradas = transporte.get("paradas", [])
                if paradas:
                    st.markdown(f"**Transporte público: {len(paradas)} paradas de ônibus**")
                    for p in paradas[:5]:
                        st.write(f"  • {p.get('nome', 'parada')} — {p.get('distancia_metros', '?')}m")
                else:
                    st.write("Transporte público: nenhuma parada encontrada no raio")
            else:
                st.write("Dados de infraestrutura não disponíveis")

        # ── BOTÃO EXPORTAR PDF ─────────────────────────────────────
        st.divider()
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

INFRAESTRUTURA
{'-'*50}
Score: {resultado.get('infraestrutura', {}).get('scores', {}).get('score_final', '?')}
Classificação: {resultado.get('infraestrutura', {}).get('resumo_scores', {}).get('classificacao_infraestrutura', '?')}

ZONA HOMOGÊNEA
{'-'*50}
Raio: {resultado.get('zona_homogenea', {}).get('zona_homogenea', {}).get('raio_metros', '?')}m
Imóveis na zona: {len(resultado.get('zona_homogenea', {}).get('comparaveis_confirmados', []))}

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
