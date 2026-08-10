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
    page_title="Precificação Imobiliária",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 Sistema Multiagente de Precificação Imobiliária")
st.markdown("Insira os dados do imóvel alvo e clique em **Avaliar** para estimar o valor de mercado.")

# ============================================================
# FORMULÁRIO
# ============================================================

with st.form("imovel_form"):
    st.subheader("📍 Localização")
    col1, col2 = st.columns(2)
    with col1:
        rua = st.text_input("Rua", value="Rua Frederico Soares")
        numero = st.text_input("Número", value="499")
        bairro = st.text_input("Bairro", value="Santa Fe")
    with col2:
        cidade = st.text_input("Cidade", value="Campo Grande")
        estado = st.text_input("Estado (sigla)", value="MS")

    st.subheader("🏗️ Características")
    col3, col4, col5 = st.columns(3)
    with col3:
        tipo = st.selectbox("Tipo", ["Casa", "Apartamento", "Terreno"])
        area = st.number_input("Área construída (m²)", min_value=0, value=230)
        area_terreno = st.number_input("Área do terreno (m²)", min_value=0, value=360)
    with col4:
        quartos = st.number_input("Quartos", min_value=0, value=3)
        banheiros = st.number_input("Banheiros", min_value=0, value=2)
        vagas = st.number_input("Vagas", min_value=0, value=1)
    with col5:
        preco_anunciado = st.number_input("Preço anunciado (R$, opcional)", min_value=0, value=0)
        descricao = st.text_area("Descrição (opcional)", value="")

    st.subheader("📸 Fotos do imóvel (opcional)")
    st.caption("Cole as URLs das fotos do imóvel (uma por linha). Melhora a análise de qualidade.")
    fotos_texto = st.text_area("URLs das fotos", value="", height=100, placeholder="https://exemplo.com/foto1.jpg\nhttps://exemplo.com/foto2.jpg")

    submitted = st.form_submit_button("🚀 Avaliar Imóvel", use_container_width=True)


# ============================================================
# EXECUÇÃO DO PIPELINE
# ============================================================

if submitted:
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
        "images": [url.strip() for url in fotos_texto.strip().split("\n") if url.strip()],
    }

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
        st.write(f"Pesquisando imóveis à venda perto do seu, em **{bairro}, {cidade}/{estado}**...")

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
        st.success(f"✅ **{len(imoveis_coletados)} imóveis à venda encontrados** na região")

    # ==============================================================
    # ETAPA 2 — Identificação dos comparáveis (~30s)
    # ==============================================================
    status_box.info("📊 **Etapa 2/5 — Agente Identificador de Comparáveis** | Tempo estimado: ~30 segundos")
    progress.progress(25)
    with log_area:
        st.write("Comparando os imóveis encontrados com o seu para identificar os mais parecidos...")

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
        st.success(f"✅ **{resumo.get('cluster_a', 0)} imóveis parecidos com o seu** selecionados para avaliação")

    if not comparaveis:
        status_box.error("❌ Nenhum imóvel comparável encontrado. O bairro pode ter poucos anúncios.")
        st.stop()

    # Zona homogênea (~30s)
    zona_resultado = None
    if os.getenv("GOOGLE_MAPS_KEY"):
        status_box.info("📊 **Etapa 2/5 — Agente Identificador de Comparáveis** | Validando localização...")
        progress.progress(35)
        with log_area:
            st.write("Verificando quais estão na mesma vizinhança...")
        try:
            t2z = time.time()
            endereco = f"{rua}, {numero}, {bairro}, {cidade}, {estado}"
            zona_resultado = analisar_zona_homogenea(
                endereco_alvo=endereco,
                imoveis=comparaveis + terrenos,
                cidade=cidade,
                estado=estado,
            )
            confirmados = zona_resultado.get("comparaveis_confirmados", [])
            fora = zona_resultado.get("fora_zona", [])
            tempo_zona = time.time() - t2z
            with log_area:
                st.success(f"✅ Vizinhança validada — {len(fora)} imóveis descartados por estarem longe demais")
        except Exception as e:
            with log_area:
                st.warning(f"⚠️ Validação geográfica indisponível — continuando sem ela ({type(e).__name__}: {e})")

    progress.progress(45)

    # ==============================================================
    # ETAPAS 3 e 4 — Análise de qualidade + infraestrutura (~3 min)
    # ==============================================================
    progress.progress(50)
    with log_area:
        st.write("Analisando a qualidade dos imóveis (fotos e descrição) e mapeando o que tem perto (escolas, hospitais, comércio, transporte)...")

    resultado_ag3 = {}
    resultado_ag4 = {}
    ag4_pronto = [False]
    ag3_pronto = [False]

    t34 = time.time()
    tempo_estimado_ag34 = 180  # ~3 minutos

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_ag3 = executor.submit(analisar_comparaveis)
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
                st.success(f"✅ Infraestrutura da região avaliada — Classificação: **{classif}**")
        except Exception as e:
            with log_area:
                st.warning("⚠️ Agente Avaliador de Infraestrutura indisponível")

        try:
            resultado_ag3 = future_ag3.result()
            score_qual = resultado_ag3.get("resumo", {}).get("score_qualitativo_medio", 0)
            total_analisados = resultado_ag3.get("resumo", {}).get("total_analisados", 0)
            with log_area:
                st.success(f"✅ Qualidade dos imóveis analisada — **{total_analisados} imóveis avaliados**")
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
        st.write("Calculando o valor do seu imóvel com base nos preços da vizinhança...")

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

        # Zona homogênea
        with st.expander("📍 Zona Homogênea"):
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

        with st.expander("🏥 Infraestrutura (Agente 4)"):
            infra = resultado.get("infraestrutura", {})
            if infra:
                scores = infra.get("scores", {})
                resumo = infra.get("resumo_scores", {})
                st.write(f"- Score final: **{scores.get('score_final', '?')}**")
                st.write(f"- Classificação: **{resumo.get('classificacao_infraestrutura', 'não disponível')}**")
                st.write(f"- Perfil: {resumo.get('perfil_regiao') or 'não disponível'}")
                st.write(f"- Impacto no valor: {resumo.get('impacto_estimado_no_valor') or 'não disponível'}")
                tempo_reg = resumo.get('tempo_liquidez_regional')
                st.write(f"- Tempo estimado de venda na região: {tempo_reg or 'não disponível'}")
                pontos = resumo.get("pontos_fortes", [])
                if pontos:
                    st.markdown("**Pontos fortes:**")
                    for p in pontos:
                        st.write(f"  ✓ {p}")
            else:
                st.write("Infraestrutura não disponível")

        with st.expander("📝 Análise Qualitativa (Agente 3)"):
            ag3 = resultado.get("analise_qualitativa", {})
            if ag3:
                resumo3 = ag3.get("resumo", {})
                st.write(f"- Score médio: **{resumo3.get('score_qualitativo_medio', '?')}**")
                st.write(f"- Imóveis analisados: {resumo3.get('total_analisados', '?')}")
            else:
                st.write("Análise qualitativa não disponível")

        with st.expander("📋 Comparáveis Encontrados"):
            comparaveis = resultado.get("comparaveis", [])
            if comparaveis:
                for i, comp in enumerate(comparaveis[:10], 1):
                    preco_comp = comp.get("price", 0)
                    area_comp = comp.get("area", 0)
                    rua_comp = comp.get("street") or "Rua não informada"
                    url_comp = comp.get("url", "")
                    linha = f"{i}. **R$ {preco_comp:,.0f}** | {area_comp}m² | {comp.get('neighborhood', '?')} | {rua_comp}"
                    if url_comp:
                        st.markdown(f"{linha} — [ver anúncio]({url_comp})")
                    else:
                        st.write(linha)
            else:
                st.write("Nenhum comparável encontrado")

        # Justificativa
        st.info(preco.get("justificativa", ""))

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
                        st.warning(f"⚠️ O preço anunciado (**R$ {preco_anunc:,.0f}**) está **{diferenca_pct:.1f}% acima** do valor médio da região (R$ {valor_med:,.0f})")
                    elif diferenca_pct < -5:
                        st.success(f"✅ O preço anunciado (**R$ {preco_anunc:,.0f}**) está **{abs(diferenca_pct):.1f}% abaixo** do valor médio da região (R$ {valor_med:,.0f}) — boa oportunidade")
                    else:
                        st.info(f"O preço anunciado (**R$ {preco_anunc:,.0f}**) está alinhado com o valor médio da região (R$ {valor_med:,.0f}) — diferença de {abs(diferenca_pct):.1f}%")

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

    else:
        st.error("Não foi possível calcular o preço. Verifique os dados e tente novamente.")
        if isinstance(resultado, dict):
            st.json(resultado)
