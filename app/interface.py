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
                st.warning(f"⚠️ Validação geográfica indisponível — continuando sem ela")

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
                st.write(f"- Classificação: **{resumo.get('classificacao_infraestrutura', '?')}**")
                st.write(f"- Perfil: {resumo.get('perfil_regiao', '?')}")
                st.write(f"- Impacto no valor: {resumo.get('impacto_estimado_no_valor', '?')}")
                st.write(f"- Tempo liquidez regional: {resumo.get('tempo_liquidez_regional', '?')}")
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
                    st.write(f"{i}. **R$ {preco_comp:,.0f}** | {area_comp}m² | {comp.get('neighborhood', '?')} | {rua_comp}")
            else:
                st.write("Nenhum comparável encontrado")

        # Justificativa
        st.info(preco.get("justificativa", ""))

    else:
        st.error("Não foi possível calcular o preço. Verifique os dados e tente novamente.")
        if isinstance(resultado, dict):
            st.json(resultado)
