"""
Tela de resultado de uma avaliacao: o cartao do leilao, os valores, os 5 agentes, o
laudo (TXT) e o Excel. Usada logo depois de avaliar (app/paginas/avaliacao.py) e no
"Ver avaliacao completa" da pagina "Leiloes ativos" (app/paginas/leiloes_ativos.py),
com o resultado gravado no banco (services/detalhe_leilao.py).
"""
import streamlit as st

from app.blocos_leilao import mostrar_estimativa_2o_leilao
from app.cronometro import mostrar_cronometro
from app.funil import funil_ligado, montar_funil, mostrar_funil
from services.leilao import (
    ALIQUOTA_IR, CORES_DECISAO, CORRETAGEM, CUSTOS_ANTES_DA_VENDA, faixas_de_lance, html_decisao,
    lance_em_destaque, texto_aviso_lancamento, texto_cabecalho, texto_comissao, texto_conta_linha,
    texto_gravame, texto_lance_descarte, texto_lance_maximo, texto_percentual, texto_roi_outra_etapa,
)
from services.leilao import linhas_laudo as linhas_laudo_leilao
from services.textos_tela import (
    anuncios_do_alvo_na_zona, anuncios_do_proprio_imovel, contagem, imobiliaria_proxima,
    linhas_laudo_imobiliaria, linhas_referencia, motivo_sem_valor, motivo_terreno_fora,
    nota_anuncio_do_alvo, suspeitos_do_proprio_imovel, texto_sem_imobiliaria,
)
from services.verificacoes import resumo_conferencia

def fmt_brl(valor, decimais=0):
    """Formata valor monetário no padrão brasileiro: R$ 1.234.567,89"""
    try:
        valor = float(valor)
    except (ValueError, TypeError):
        return "R\\$ 0"
    if decimais > 0:
        texto = f"{valor:,.{decimais}f}"
    else:
        texto = f"{valor:,.0f}"
    # Converte formato americano (1,234,567.89) pra brasileiro (1.234.567,89)
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R\\$ {texto}"


# Alertas (os mesmos gravados no banco) mostrados na tela com explicacao e anuncios.
ALERTAS_NA_TELA = (
    "amostra_concentrada", "terreno_fora_do_padrao", "possivel_repetido_no_calculo",
    "area_diferente_entre_portais",
)


def alertas_na_tela(resultado, codigos=ALERTAS_NA_TELA):
    """Alertas desta avaliacao que a tela mostra, na ordem em que foram gerados."""
    alertas = ((resultado.get("registro") or {}).get("execucao") or {}).get("alertas") or []
    return [a for a in alertas if a.get("codigo") in codigos]


def alertas_amostra_concentrada(resultado):
    return alertas_na_tela(resultado, ("amostra_concentrada",))


def _anuncios_do_alerta(alerta):
    """Anuncios do detalhe do alerta, em lista unica (grupos de repetidos viram motivo)."""
    detalhe = alerta.get("detalhe")
    if isinstance(detalhe, dict):
        itens = detalhe.get("anuncios") or []
    else:
        itens = detalhe or []
    anuncios = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        if "anuncios" in item:      # grupo de possivel repetido
            grupo = f"Grupo: nº {item.get('numero')}, {item.get('area')} m², {fmt_brl(item.get('preco') or 0)}"
            anuncios += [{**a, "motivo": grupo} for a in item.get("anuncios") or []]
        else:
            anuncios.append(item)
    return anuncios


def _linha_anuncio(a):
    return {
        "Endereço": ", ".join(x for x in (a.get("endereco"), a.get("bairro")) if x) or "-",
        "Preço": fmt_brl(a["preco"]) if a.get("preco") else "-",
        "Área": f"{float(a['area']):g} m²" if a.get("area") else "-",
        "Portal": a.get("portal") or "-",
        "Anúncio": f"[ver]({a['link']})" if a.get("link") else "-",
    }


def _mostrar_grupos_de_repetidos(alerta):
    """
    Logo abaixo do aviso "Possivel repetido no calculo": um titulo por grupo ("Grupo 1:
    nº 888, R$ 830.000, 203 m²") e os anuncios do grupo embaixo.
    """
    import pandas as pd
    detalhe = alerta.get("detalhe")
    itens = (detalhe.get("anuncios") if isinstance(detalhe, dict) else detalhe) or []
    grupos = [g for g in itens if isinstance(g, dict) and g.get("anuncios")]
    n = sum(len(g["anuncios"]) for g in grupos)
    with st.expander(f"Ver os {n} anúncios que podem ser repetidos"):
        for i, g in enumerate(grupos, start=1):
            area = f", {float(g['area']):g} m²" if g.get("area") else ""
            st.markdown(f"**Grupo {i}: nº {g.get('numero') or '-'}, {fmt_brl(g.get('preco') or 0)}{area}**")
            st.markdown(pd.DataFrame([_linha_anuncio(a) for a in g["anuncios"]]).to_markdown(index=False),
                        unsafe_allow_html=True)


def mostrar_alertas_na_tela(resultado):
    """Aviso de cada alerta (texto explicativo) e os anuncios envolvidos num expander."""
    import pandas as pd
    for alerta in alertas_na_tela(resultado):
        texto = str(alerta.get("mensagem") or "").replace("R$", "R\\$")   # $ nao vira formula
        st.warning(f"⚠️ {texto}")
        if alerta.get("codigo") == "possivel_repetido_no_calculo":
            _mostrar_grupos_de_repetidos(alerta)
            continue
        anuncios = _anuncios_do_alerta(alerta)
        rotulo = (f"Ver os {len(anuncios)} anúncios iguais" if alerta.get("codigo") == "amostra_concentrada"
                  else "Ver os anúncios")
        with st.expander(rotulo):
            com_motivo = any(a.get("motivo") for a in anuncios)
            linhas = []
            for a in anuncios:
                linha = {
                    "Endereço": ", ".join(x for x in (a.get("endereco"), a.get("bairro")) if x) or "-",
                    "Preço": fmt_brl(a["preco"]) if a.get("preco") else "-",
                    "Área": f"{float(a['area']):g} m²" if a.get("area") else "-",
                    "Portal": a.get("portal") or "-",
                    "Anúncio": f"[ver]({a['link']})" if a.get("link") else "-",
                }
                if com_motivo:
                    linha["Motivo"] = str(a.get("motivo") or "-").replace("R$", "R\\$")
                linhas.append(linha)
            if linhas:
                st.markdown(pd.DataFrame(linhas).to_markdown(index=False), unsafe_allow_html=True)


def mostrar_avaliacao_leilao(leilao):
    """
    Cartao do leilao, no topo do resultado (services/leilao.py): banco, modalidade e
    etapa, cronometro ate a proxima data, aviso de gravame, a resposta (4 cores), ROI,
    lances e a conta. So aparece quando ha valor minimo da etapa. Sem estimativa
    confiavel do Agente 5, mostra a resposta sem lance maximo.
    """
    import pandas as pd
    if not leilao:
        return
    st.markdown("#### 🔨 Avaliação de leilão")
    if leilao.get("modalidade"):
        st.markdown(f"**{texto_cabecalho(leilao)}**")
        mostrar_cronometro(leilao)
    if texto_gravame(leilao):
        st.error(f"⚠️ {texto_gravame(leilao)}")
    st.markdown(html_decisao(leilao["decisao"]), unsafe_allow_html=True)
    if leilao.get("alvo_sem_localizacao"):
        st.warning(
            "⚠️ Endereço não localizado no mapa com precisão de rua ou bairro: a distância "
            "dos comparáveis até o imóvel não foi verificada. Confira antes de decidir."
        )
    rotulo_minimo = f"Valor mínimo ({leilao['etapa']}º leilão)" if leilao.get("etapa") else "Valor mínimo"
    if leilao.get("lance_maximo") is not None:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("ROI pagando o valor mínimo", texto_percentual(leilao["roi"]))
        with col2:
            st.metric(rotulo_minimo, fmt_brl(leilao["valor_minimo"]))
        with col3:
            # Oportunidade: lance de 30%; Margem apertada: de 15% (o de 30% fica abaixo do
            # minimo); Descartar: nenhum lance da 15%.
            rotulo_lance, lance = lance_em_destaque(leilao)
            st.metric(rotulo_lance, fmt_brl(lance) if lance is not None else "—",
                      help="Maior lance que ainda dá o ROI indicado. Quanto maior o lance, menor o ROI. "
                           "Veja as faixas em \"Quanto dar de lance\".")
        # A conta numa linha, logo abaixo do ROI ($ escapado: no markdown vira formula).
        st.caption(texto_conta_linha(leilao["conta"]).replace("R$", "R\\$"))
        st.markdown(f"**{texto_lance_maximo(leilao, fmt_brl)}**")
        st.caption(texto_lance_descarte(leilao, fmt_brl))
        # Tabela das faixas de lance: o ROI cai conforme o lance sobe.
        st.markdown("**Quanto dar de lance**")
        st.markdown(pd.DataFrame([
            {"Lance": f["lance"], "ROI": f["roi"],
             "Resposta": f"{CORES_DECISAO[f['decisao']][2]} {f['decisao']}",
             "": ("← o valor mínimo está aqui" if f["minimo_aqui"]
                  else "abaixo do mínimo: não dá" if f["abaixo_do_minimo"] else "")}
            for f in faixas_de_lance(leilao, fmt_brl)
        ]).to_markdown(index=False))
        if leilao.get("estimativa_2o_leilao"):
            mostrar_estimativa_2o_leilao(leilao["estimativa_2o_leilao"], fmt_brl)
        elif texto_roi_outra_etapa(leilao, fmt_brl):
            st.caption(texto_roi_outra_etapa(leilao, fmt_brl))
        conta = leilao["conta"]
        with st.expander("Conta do investimento (pagando o valor mínimo)"):
            st.markdown(pd.DataFrame([
                ("Arrematação (valor mínimo)", fmt_brl(conta["arrematacao"])),
                (f"Custos antes da venda (arrematação + {texto_percentual(CUSTOS_ANTES_DA_VENDA, 0)})",
                 fmt_brl(conta["custos_antes_da_venda"])),
                ("Receita da venda (valor de liquidez)", fmt_brl(conta["venda"])),
                (f"Corretagem ({texto_percentual(CORRETAGEM, 0)} da venda)", fmt_brl(conta["corretagem"])),
                (f"IR ({texto_percentual(ALIQUOTA_IR, 0)} de venda − custos antes da venda)", fmt_brl(conta["ir"])),
                ("Todos os custos", fmt_brl(conta["custos_totais"])),
                ("Resultado", fmt_brl(conta["resultado"])),
                ("ROI (resultado ÷ custos antes da venda)", texto_percentual(conta["roi"])),
            ], columns=["", "Valor"]).to_markdown(index=False))
    else:
        st.caption(f"{rotulo_minimo}: {fmt_brl(leilao['valor_minimo'])}")
    if leilao.get("valor_avaliacao"):
        st.caption(f"Valor de avaliação (informativo): {fmt_brl(leilao['valor_avaliacao'])}")
    if texto_comissao(leilao):
        st.caption(texto_comissao(leilao))
    if leilao.get("aviso_direito_preferencia"):
        st.caption(f"ℹ️ {leilao['aviso_direito_preferencia']}")
    dados = [f"{rotulo}: {leilao[campo]}" for rotulo, campo in (
        ("Nº do imóvel", "numero_imovel"), ("Edital", "edital"), ("Item", "numero_item"),
        ("Leiloeiro(a)", "leiloeiro"), ("Matrícula", "matricula"),
        ("Averbação dos leilões negativos", "averbacao_leiloes_negativos"),
    ) if leilao.get(campo)]
    if dados:
        st.caption(" · ".join(dados))
    if leilao.get("aviso_zona"):
        st.warning(f"⚠️ {leilao['aviso_zona']}")

def mostrar_resultado(resultado, imovel_alvo_export, tela):
    """
    Resultado completo de uma avaliacao. `imovel_alvo_export` e o imovel alvo mandado
    aos agentes; `tela` traz os campos do formulario mostrados no texto e no laudo
    (rua, numero, bairro, cidade, estado, tipo, quartos, banheiros, vagas).
    """
    rua, numero, bairro, cidade, estado = (tela.get(c) for c in ("rua", "numero", "bairro", "cidade", "estado"))
    tipo, quartos, banheiros, vagas = (tela.get(c) for c in ("tipo", "quartos", "banheiros", "vagas"))
    st.divider()
    st.subheader("📊 Resultado da Avaliação")

    # Preço estimado
    preco = resultado.get("preco_estimado", {})
    if preco and isinstance(preco, dict):
        # Cartao do leilao no topo: banco, modalidade, etapa, cronometro e a resposta.
        mostrar_avaliacao_leilao(resultado.get("leilao"))

        avaliacao = preco.get("avaliacao_planilha") or preco.get("avaliacao", {})
        liquidez_info = preco.get("liquidez_experimental") or preco.get("liquidez", {})

        # O Ag5 sinaliza quando nao teve amostra suficiente ou o valor deu <= 0.
        # Nesses casos NAO mostramos "R$ 0" como se fosse um resultado valido.
        avaliacao_confiavel = preco.get("avaliacao_confiavel", True)
        status_avaliacao = preco.get("status_avaliacao", "ok")
        # False quando a zona homogenea nao rodou nesta avaliacao (o Ag5 nao usa a
        # zona de uma avaliacao anterior): o motivo nao e falta de anuncios.
        zona_calculada = preco.get("zona_calculada_nesta_avaliacao", True)

        # Sem valor: o motivo exato (ex.: "Faltou 1 casa para o mínimo de 5.") e o
        # que da para fazer. Os avisos tecnicos do Agente 5 ficam no bloco dele.
        sem_valor = motivo_sem_valor(resultado, imovel_alvo_export) if not avaliacao_confiavel else None
        if sem_valor:
            st.warning(f"⚠️ **Não foi possível estimar um valor confiável para este imóvel.** {sem_valor['motivo']}")
            for _fazer in sem_valor["fazer"]:
                st.caption(f"• {_fazer}")

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            valor_medio = avaliacao.get("valor_medio_imovel", 0)
            valor_medio_txt = fmt_brl(valor_medio) if avaliacao_confiavel else "—"
            st.metric("💰 Valor Médio Estimado", valor_medio_txt)
        with col_b:
            valor_liq = avaliacao.get("valor_liquidez", 0)
            valor_liq_txt = fmt_brl(valor_liq) if avaliacao_confiavel else "—"
            st.metric("⚡ Valor de Liquidez (-10%)", valor_liq_txt)
        with col_c:
            tempo = liquidez_info.get("tempo_estimado", "?")
            st.metric("⏱️ Tempo Estimado de Venda", tempo if avaliacao_confiavel else "—")
            if avaliacao_confiavel and (preco or {}).get("aviso_infraestrutura"):
                st.caption(f"⚠️ {preco['aviso_infraestrutura']}")

        # Anuncio do proprio imovel logo abaixo do valor: mexe no preco (continua
        # aparecendo tambem nas tabelas de baixo).
        excluidos_alvo, _ = anuncios_do_proprio_imovel(resultado)
        suspeitos_alvo = suspeitos_do_proprio_imovel(resultado, imovel_alvo_export)
        # Provavel anuncio do proprio imovel (perfil quase todo igual): em destaque.
        for s_alvo in [s for s in suspeitos_alvo if s["provavel"]]:
            st.error(
                f"⚠️ **Provável anúncio do próprio imóvel (continua no cálculo):** "
                f"{s_alvo['motivo']}.".replace("$", "\\$")
                + (f" [Ver o anúncio]({s_alvo['url']})" if s_alvo["url"] else "")
            )
        if excluidos_alvo:
            st.info(
                "🎯 Encontramos o anúncio do próprio imóvel e ele saiu do cálculo."
                + "".join(f" [Ver o anúncio]({u})" for u in excluidos_alvo if u)
            )
        for s_alvo in [s for s in suspeitos_alvo if not s["provavel"]]:
            st.warning(
                f"⚠️ Possível anúncio do próprio imóvel (continua no cálculo): {s_alvo['motivo']}.".replace("$", "\\$")
                + (f" [Confira o anúncio]({s_alvo['url']})" if s_alvo["url"] else "")
            )

        # Sem valor confiavel: os comparaveis validos como referencia (nao e estimativa).
        referencia = linhas_referencia(resultado) if not avaliacao_confiavel else []
        if referencia:
            import pandas as pd
            st.markdown(f"**Anúncios válidos encontrados ({len(referencia)}), só como referência**")
            st.caption(
                "⚠️ Não é uma estimativa: são poucos anúncios para um valor confiável. "
                "Use só para ter uma ideia dos preços perto do imóvel."
            )
            st.markdown(pd.DataFrame([{
                "Preço": fmt_brl(l["preco"]),
                "Área": f"{l['area']:.0f} m²",
                "R$/m²": fmt_brl(l["m2"]),
                "Rua": l["rua"] or "-",
                "Bairro": l["bairro"] or "-",
                "Anúncio": f"[ver]({l['url']})" if l["url"] else "-",
            } for l in referencia]).rename(columns={"R$/m²": "R\\$/m²"}).to_markdown(index=False),
                unsafe_allow_html=True)

        # Comparaveis com a distancia nao verificada (contam para o minimo de 5) e
        # busca na cidade toda: aviso com numeros, com ou sem valor minimo CAIXA.
        if resultado.get("aviso_raio"):
            st.info(f"📏 {resultado['aviso_raio']}")
        if (preco or {}).get("aviso_terreno"):
            st.info(f"🏞️ {preco['aviso_terreno']}")
        if texto_aviso_lancamento(preco):
            st.info(f"🏗️ {texto_aviso_lancamento(preco)}")
        mostrar_alertas_na_tela(resultado)
        if resultado.get("aviso_zona"):
            st.warning(f"⚠️ {resultado['aviso_zona']}")

        # ==============================================================
        # COMO CHEGAMOS NESTE VALOR
        # ==============================================================
        st.divider()
        st.subheader("📖 Como chegamos neste valor")

        zona = resultado.get("zona_homogenea", {})
        zh = zona.get("zona_homogenea", {}) if zona else {}
        raio = (zona or {}).get("raio_final_m") or zh.get("raio_metros") or zh.get("raio_sugerido_metros") or 500
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
        portais = resultado.get("resumo", {}).get("portais", {})
        na_rua_n = resultado.get("resumo", {}).get("na_rua", 0)
        tempo_coleta = resultado.get("resumo", {}).get("tempo_coleta_s", 0)
        _resumo_ag2 = resultado.get("resumo", {})
        terrenos_sep = _resumo_ag2.get("terrenos_separados", _resumo_ag2.get("terrenos_excluidos", 0))
        with st.expander("🔍 Agente Coletor de Dados"):
            # "Na regiao": a busca vai alem do bairro (rua, bairro e ate 1,5 km).
            st.write(f"Encontramos **{contagem(total_encontrados, 'imóvel', 'imóveis')}** à venda na região do imóvel "
                     f"({bairro}, {cidade}/{estado}).")
            col_c1, col_c2, col_c3 = st.columns(3)
            with col_c1:
                st.metric("Total", total_encontrados, f"{len(portais)} fontes")
            with col_c2:
                st.metric("Na rua", na_rua_n, f"de {total_encontrados}")
            with col_c3:
                st.metric("Terrenos", terrenos_sep, "separados")

        # Ag.2
        cluster_a = resultado.get("resumo", {}).get("cluster_a", len(confirmados))
        cluster_b = resultado.get("resumo", {}).get("cluster_b", 0)
        terrenos_sep = _resumo_ag2.get("terrenos_separados", _resumo_ag2.get("terrenos_excluidos", 0))
        with st.expander("📊 Agente Identificador de Comparáveis"):
            # Monta texto compacto em um único bloco markdown
            linhas = [f"Dos {contagem(total_encontrados, 'imóvel encontrado', 'imóveis encontrados')}:"]
            if terrenos_sep > 0:
                linhas.append(f"- {contagem(terrenos_sep, 'é terreno', 'são terrenos')} (não entram na comparação direta)")
            # Quantos sairam ja na comparacao de area/caracteristicas (Python, sem IA) e
            # quantos a IA julgou. Resultado antigo sem esses numeros: texto de antes.
            n_sem_ia = (_resumo_ag2.get("pre_classificacao") or {}).get("incompativeis_pre_classificacao")
            n_ia = _resumo_ag2.get("llm_tentados")
            if n_sem_ia is not None and n_ia is not None:
                if n_sem_ia:
                    linhas.append(f"- {contagem(n_sem_ia, 'saiu', 'saíram')} já na comparação de área e características "
                                  f"(muito diferentes das do seu), sem chegar à IA")
                if n_ia:
                    linhas.append(f"- {contagem(n_ia, 'foi analisado', 'foram analisados')} pela IA para identificar "
                                  f"os mais parecidos com o seu")
            elif terrenos_sep > 0:
                analisados = total_encontrados - terrenos_sep
                linhas.append(f"- {contagem(analisados, 'foi analisado', 'foram analisados')} pela IA para identificar os mais parecidos com o seu")
            else:
                linhas.append(f"- Todos foram analisados pela IA para identificar os mais parecidos com o seu")
            linhas.append(
                f"- **{cluster_a}** {'classificado como comparável' if cluster_a == 1 else 'classificados como comparáveis'} "
                f"(perfil similar ao seu)"
            )
            if cluster_b > 0:
                linhas.append(f"- {contagem(cluster_b, 'descartado', 'descartados')} (perfil muito diferente: área, quartos ou padrão incompatível)")
            st.markdown("\n".join(linhas))

            # Zona: mostra comparaveis e terrenos na zona
            terrenos_zona_list = [c for c in confirmados if (c.get("propertyType", "") or "").lower() in ("terrenos", "terreno", "lote", "residential_allotment_land", "allotment_land")]
            comparaveis_zona_list = [c for c in confirmados if c not in terrenos_zona_list]
            zona_linhas = []
            n_zona = len(comparaveis_zona_list)
            nota_alvo = nota_anuncio_do_alvo(anuncios_do_alvo_na_zona(resultado, comparaveis_zona_list))
            if cluster_a == 0:
                zona_linhas.append("- Nenhum comparável para conferir na zona homogênea")
            elif n_zona == cluster_a == 1:
                zona_linhas.append(f"- O único comparável está na zona homogênea (raio de {raio} m){nota_alvo}")
            elif n_zona == cluster_a:
                zona_linhas.append(f"- Todos os **{cluster_a}** comparáveis estão na zona homogênea (raio de {raio} m){nota_alvo}")
            else:
                zona_linhas.append(
                    f"- Dos {contagem(cluster_a, 'comparável', 'comparáveis')}, **{n_zona}** "
                    f"{'está' if n_zona == 1 else 'estão'} na zona homogênea (raio de {raio} m){nota_alvo}"
                )
            if terrenos_sep > 0:
                n_ter_zona = len(terrenos_zona_list)
                if n_ter_zona == terrenos_sep == 1:
                    zona_linhas.append("- O único terreno está na zona homogênea (pode entrar no cálculo do m² do terreno)")
                elif n_ter_zona == terrenos_sep:
                    zona_linhas.append(f"- Todos os **{terrenos_sep}** terrenos estão na zona homogênea (podem entrar no cálculo do m² do terreno)")
                elif n_ter_zona > 0:
                    zona_linhas.append(
                        f"- Dos {contagem(terrenos_sep, 'terreno', 'terrenos')}, **{n_ter_zona}** "
                        f"{'está' if n_ter_zona == 1 else 'estão'} na zona homogênea (podem entrar no cálculo do m² do terreno)"
                    )
                else:
                    zona_linhas.append(f"- Nenhum terreno na zona — cálculo do m² do terreno não será aplicado")
            st.markdown("\n".join(zona_linhas))

            # Detalhes da zona homogênea
            st.markdown("---")
            st.markdown("**Zona homogênea**")
            st.write("A zona homogênea é a área ao redor do seu imóvel onde as construções têm características parecidas (mesmo tipo, tamanho e padrão). Só imóveis dentro dessa zona são usados no cálculo do valor, porque representam melhor o mercado local.")
            if zh:
                raio_ia_zona = (zona or {}).get("raio_ia_m")
                if raio_ia_zona and raio_ia_zona != raio:
                    st.write(f"- Raio escolhido pela IA: **{raio_ia_zona} metros**; ampliado para **{raio} metros** para completar a amostra")
                else:
                    st.write(f"- Raio utilizado: **{raio} metros**")
                st.write(f"- Padrão construtivo: {zh.get('padrao_construtivo', 'não disponível')}")
                st.write(f"- Homogeneidade visual: {zh.get('homogeneidade_visual', 'não disponível')}")
                st.write(f"- Densidade urbana: {zh.get('densidade_urbana', 'não disponível')}")
                justificativa_zh = zh.get("justificativa_raio") or zh.get("descricao_zona_homogenea", "")
                if "<think>" in str(justificativa_zh):
                    justificativa_zh = ""
                if justificativa_zh:
                    st.write(f"- Justificativa: {justificativa_zh}")

            # Imagem de satélite: usa o caminho que o Ag2 gravou no resultado da zona
            # (suporta run_id); cai no caminho legado so se o campo nao existir.
            import os
            img_path = (zona.get("imagem_satelite") if zona else None) or "data/satelite_zona_homogenea_ag2.png"
            if img_path and os.path.exists(img_path):
                st.image(img_path, caption="Imagem de satélite com marcador no imóvel alvo", use_container_width=True)

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
                st.markdown("**🏠 Seu imóvel**")
                col_est, col_pad, col_score = st.columns(3)
                with col_est:
                    st.metric("Estado", estado_alvo.capitalize())
                with col_pad:
                    st.metric("Padrão", padrao_alvo.capitalize())
                with col_score:
                    st.metric("Score", f"{score_alvo}", classif_alvo)

                # Pontos positivos
                positivos = alvo_analise.get("pontos_positivos", [])
                if positivos:
                    bullets_pos = "\n".join([f"- {p}" for p in positivos])
                    st.markdown(f"✅ **Pontos positivos:**\n{bullets_pos}")

                # Pontos negativos
                negativos = alvo_analise.get("pontos_negativos", [])
                if negativos:
                    bullets_neg = "\n".join([f"- {n}" for n in negativos])
                    st.markdown(f"⚠️ **Pontos de atenção:**\n{bullets_neg}")

                # Características da unidade
                carac_unidade = alvo_analise.get("caracteristicas_unidade", [])
                if carac_unidade:
                    st.markdown(f"🏢 **Unidade:** {', '.join(carac_unidade)}")

                # Características do condomínio
                carac_condo = alvo_analise.get("caracteristicas_condominio", [])
                if carac_condo:
                    st.markdown(f"🏘️ **Condomínio:** {', '.join(carac_condo)}")

                # Observações
                observacoes = alvo_analise.get("observacoes", [])
                if observacoes:
                    obs_text = " | ".join(observacoes)
                    st.markdown(f"ℹ️ _{obs_text}_")

            # Resumo da vizinhança
            if total_analisados > 0:
                st.markdown("---")
                n_label = "imóvel" if total_analisados == 1 else "imóveis"
                st.markdown(f"**🏘️ Vizinhança** ({total_analisados} {n_label} analisado{'s' if total_analisados > 1 else ''})")
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    st.metric("Score médio da região", f"{score_medio:.2f}")
                with col_v2:
                    st.metric("Imóveis analisados", total_analisados)

                # Comparação alvo vs vizinhança
                score_alvo_val = alvo_analise.get("scores", {}).get("score_qualitativo", 0) if alvo_analise else 0
                try:
                    score_alvo_num = float(score_alvo_val)
                except (ValueError, TypeError):
                    score_alvo_num = 0
                alvo_sem_evidencia = bool(
                    (alvo_analise or {}).get("detalhes_calculo", {}).get("regra_neutra_aplicada")
                )
                if alvo_sem_evidencia:
                    # Nota neutra por falta de fotos/descricao: comparar com a vizinhanca
                    # diria "abaixo da media" sem base nenhuma.
                    st.info(
                        "Sem fotos e sem descrição do seu imóvel, não dá para comparar a conservação "
                        "e o acabamento com a vizinhança. Usamos nota neutra (0,50). Para uma comparação "
                        "real, informe a descrição e os links das fotos."
                    )
                elif score_alvo_num > 0 and score_medio > 0:
                    if score_alvo_num > score_medio + 0.1:
                        st.success(f"Seu imóvel (score {score_alvo_num:.2f}) está **acima da média** da vizinhança ({score_medio:.2f}) — melhor conservado e acabado que os vizinhos.")
                    elif score_alvo_num < score_medio - 0.1:
                        st.warning(f"Seu imóvel (score {score_alvo_num:.2f}) está **abaixo da média** da vizinhança ({score_medio:.2f}) — os imóveis vizinhos têm melhor conservação.")
                    else:
                        st.info(f"Seu imóvel (score {score_alvo_num:.2f}) está **na média** da vizinhança ({score_medio:.2f}).")

                # Tabela de comparáveis na zona
                ag3_comps = resultado.get("analise_qualitativa", {})
                comparaveis_tabela = ag3_comps.get("comparaveis", []) if ag3_comps else []
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
                        preco_val = comp.get("price") or comp.get("preco") or 0
                        try:
                            preco_val = float(preco_val)
                        except (ValueError, TypeError):
                            preco_val = 0
                        eh_alvo = comp.get("eh_anuncio_do_alvo", False)
                        possivel_alvo = comp.get("possivel_anuncio_do_alvo", False)
                        if eh_alvo:
                            obs_alvo = "🎯 seu anúncio"
                        elif possivel_alvo:
                            obs_alvo = "⚠️ possível (não confirmado)"
                        else:
                            obs_alvo = ""
                        dados_tabela.append({
                            "Preço": f"{fmt_brl(preco_val)}" if preco_val else "-",
                            "Área": f"{comp.get('area') or comp.get('area_construida', 0)}m²",
                            "Rua": comp.get("street") or comp.get("rua") or "-",
                            "Bairro": comp.get("neighborhood") or comp.get("bairro", "?"),
                            "Portais": " + ".join(comp.get("fontes_origem") or [comp.get("source") or "-"]),
                            "Estado": estado_cons,
                            "Padrão": padrao_tab,
                            "Score": score_q,
                            "Obs": obs_alvo,
                            "Anúncio": link,
                        })
                    df = pd.DataFrame(dados_tabela)
                    st.markdown(df.to_markdown(index=False), unsafe_allow_html=True)

                    # Legenda quando o proprio anuncio do alvo foi identificado
                    n_alvo = sum(1 for c in comparaveis_tabela if c.get("eh_anuncio_do_alvo"))
                    if n_alvo:
                        plural = "anúncios identificados" if n_alvo > 1 else "anúncio identificado"
                        st.caption(
                            f"🎯 {n_alvo} {plural} como o do **seu próprio imóvel**. "
                            f"Ele aparece aqui para comparação, mas **não entrou no cálculo do preço** "
                            f"(evita que o valor pedido no anúncio influencie a estimativa)."
                        )
                    # Legenda para SUSPEITOS (perfil compativel, identidade nao confirmada)
                    n_susp = sum(1 for c in comparaveis_tabela if c.get("possivel_anuncio_do_alvo"))
                    if n_susp:
                        plural_s = "anúncios têm" if n_susp > 1 else "anúncio tem"
                        st.caption(
                            f"⚠️ {n_susp} {plural_s} perfil muito parecido com o do seu imóvel "
                            f"(mesmo bairro e área, com preço ou cômodos parecidos, ou no mesmo prédio), mas "
                            f"**sem prova de que seja o mesmo anúncio** (sem a unidade, ou com algum dado "
                            f"divergente, como vagas). Por segurança, **continuam no cálculo** — "
                            f"marcamos apenas para transparência."
                        )

                    # Anuncios repetidos que o Ag1 descartou (mesmo imovel em outro
                    # portal ou por outra imobiliaria), para conferencia.
                    dups = resultado.get("duplicatas_descartadas") or []
                    if dups:
                        # Uma linha por imovel: o anuncio que entrou no calculo e todos os
                        # repetidos dele que foram descartados.
                        grupos_dup = {}
                        for d in dups:
                            chave = d.get("Anúncio mantido") or (d.get("Mantido"), d.get("Preço"), d.get("Área"))
                            grupos_dup.setdefault(chave, []).append(d)
                        with st.expander(
                            f"🔁 Anúncios repetidos descartados ({contagem(len(dups), 'anúncio', 'anúncios')} de "
                            f"{contagem(len(grupos_dup), 'imóvel', 'imóveis')})"
                        ):
                            st.caption(
                                "O mesmo imóvel apareceu em mais de um anúncio. Ficou só um anúncio de "
                                "cada imóvel (coluna \"Anúncio que ficou\"); os da coluna \"Descartados\" "
                                "saíram já na busca. Ficar aqui não quer dizer que o imóvel entrou no "
                                "cálculo do preço: ele ainda passa pelo filtro de parecidos e pela zona. "
                                "Os que entraram no preço estão em \"Imóveis usados neste cálculo\"."
                            )
                            linhas_dup = []
                            for grupo in grupos_dup.values():
                                d = grupo[0]
                                try:
                                    preco_d = fmt_brl(float(d.get("Preço"))) if d.get("Preço") else "-"
                                except (TypeError, ValueError):
                                    preco_d = "-"
                                links_desc = [
                                    f"[{g['Descartado']}]({g['Anúncio descartado']})" if g.get("Anúncio descartado") else str(g.get("Descartado"))
                                    for g in grupo
                                ]
                                motivos = list(dict.fromkeys(g.get("Motivo") or "-" for g in grupo))
                                linhas_dup.append({
                                    "Preço": preco_d,
                                    "Área": f"{float(d['Área']):.0f}m²" if d.get("Área") else "-",
                                    "Anúncio que ficou": f"[{d['Mantido']}]({d['Anúncio mantido']})" if d.get("Anúncio mantido") else d.get("Mantido"),
                                    "Descartados": f"{contagem(len(grupo), 'anúncio', 'anúncios')}: " + ", ".join(links_desc),
                                    "Motivo": ", ".join(motivos),
                                })
                            st.markdown(pd.DataFrame(linhas_dup).to_markdown(index=False), unsafe_allow_html=True)

        # Ag.4
        score_final_infra = scores_infra.get("score_final", 0) or 0
        classif_infra = resumo_infra.get("classificacao_infraestrutura", "?")
        with st.expander("🏥 Agente Avaliador de Infraestrutura"):
            if (infra_data or {}).get("status") == "endereco_nao_localizado":
                # Agente 4 sem localizacao precisa: nao avalia a partir do centro da cidade.
                st.warning(f"⚠️ {infra_data.get('mensagem')}. O tempo estimado de venda usou a infraestrutura como média.")
            else:
                st.write(f"O entorno do seu imóvel tem infraestrutura **{classif_infra}** (score {score_final_infra:.2f}).")

                # Mensagem alinhada a classificacao real do Ag4 (5 niveis:
                # excelente >=0.85, boa >=0.70, moderada >=0.50, basica >=0.30, insuficiente <0.30)
                if classif_infra == "excelente":
                    st.success("Região com infraestrutura excelente — escolas, hospitais, comércio e transporte fartos no entorno.")
                elif classif_infra == "boa":
                    st.success("Região com boa infraestrutura — tem o essencial por perto e boa cobertura na maioria das categorias.")
                elif classif_infra == "moderada":
                    st.info("Região com infraestrutura moderada — tem o básico por perto, mas pode faltar algo em alguma categoria.")
                elif classif_infra == "basica":
                    st.warning("Região com infraestrutura básica — poucas opções de serviços no entorno.")
                else:
                    st.error("Região com infraestrutura insuficiente — pouco comércio, transporte ou serviços próximos.")

                # Nivel 2: perfil da regiao classificado pela LLM + ajuste aplicado ao score
                perfil_regiao = scores_infra.get("perfil_regiao")
                ajuste_llm = scores_infra.get("ajuste_llm")
                score_det = scores_infra.get("score_deterministico")
                justif_ajuste = scores_infra.get("justificativa_ajuste")
                if perfil_regiao and perfil_regiao != "desconhecido":
                    perfil_label = perfil_regiao.replace("_", " ")
                    if ajuste_llm and abs(float(ajuste_llm)) >= 0.001 and score_det is not None:
                        sinal = "aumentou" if float(ajuste_llm) > 0 else "reduziu"
                        st.caption(
                            f"🧭 A IA classificou a região como **{perfil_label}** e {sinal} o score "
                            f"em {abs(float(ajuste_llm)):.2f} (de {float(score_det):.2f} para {score_final_infra:.2f})."
                        )
                        if justif_ajuste:
                            st.caption(f"_{justif_ajuste}_")
                    else:
                        st.caption(f"🧭 A IA classificou a região como **{perfil_label}** (sem ajuste no score).")

                # Gráfico radar
                infra_full = resultado.get("infraestrutura", {})
                if infra_full:
                    scores_cat = infra_full.get("scores", {}).get("scores_categoria", {})
                    if not scores_cat:
                        # Fallback: tenta pegar do nivel raiz dos scores
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

                    # POIs por faixa — mostra destaques úteis
                    pois = infra_full.get("pois_por_faixa", {})
                    if pois:
                        st.markdown("---")
                        st.markdown("**📍 O que tem perto do seu imóvel**")

                        # Junta todas as faixas e mostra os mais relevantes por categoria
                        nomes_emojis = {
                            "comercio": "🛒", "educacao": "🏫", "saude_basica": "💊",
                            "hospital": "🏥", "lazer": "🌳", "transporte": "🚌",
                            "equipamentos_regionais": "🎓", "servicos_e_alimentacao": "🍽️",
                        }
                        linhas_destaque = []
                        for cat in ["comercio", "educacao", "saude_basica", "hospital", "lazer", "equipamentos_regionais", "transporte", "servicos_e_alimentacao"]:
                            # Pega os 3 mais próximos de todas as faixas
                            todos_cat = []
                            if cat == "transporte":
                                # Transporte vem de campo separado
                                trans_data = infra_full.get("transporte", {})
                                todos_cat = trans_data.get("paradas", []) + trans_data.get("estacoes", [])
                                todos_cat.sort(key=lambda x: x.get("distancia_metros", 9999))
                            else:
                                for faixa_nome in ["0_400", "401_800", "801_1500"]:
                                    items = pois.get(faixa_nome, {}).get(cat, [])
                                    if isinstance(items, list):
                                        todos_cat.extend(items)
                                todos_cat.sort(key=lambda x: x.get("distancia_metros", 9999))
                            if todos_cat:
                                emoji = nomes_emojis.get(cat, "📌")
                                # Filtra POIs sem nome real
                                com_nome = [p for p in todos_cat if p.get("nome") and p.get("nome") != "?" and p.get("nome") != "parada"]
                                if not com_nome:
                                    com_nome = todos_cat  # usa todos se nenhum tem nome
                                destaques = [f"{p.get('nome', '?')} ({p.get('distancia_metros', '?')}m)" for p in com_nome[:3]]
                                qtd_total = len(todos_cat)
                                extra_qtd = f" — {qtd_total} encontrados" if qtd_total > 3 else ""
                                linhas_destaque.append(f"{emoji} **{cat.replace('_', ' ').title()}** ({qtd_total}): {' · '.join(destaques)}")
                        if linhas_destaque:
                            st.markdown("\n\n".join(linhas_destaque))

                        # Resumo total — MESMA base das categorias exibidas acima:
                        # POIs por faixa + transporte (que vem de campo separado e tambem
                        # aparece na lista). Antes o total ignorava transporte, gerando
                        # divergencia (soma das categorias != total).
                        total_pois_faixa = sum(
                            len(v) for fd in pois.values() for v in fd.values() if isinstance(v, list)
                        )
                        _trans = infra_full.get("transporte", {})
                        total_transporte = len(_trans.get("paradas", []) or []) + len(_trans.get("estacoes", []) or [])
                        total_all = total_pois_faixa + total_transporte
                        st.caption(f"Total: {total_all} pontos de interesse mapeados até 1500m")

                    # Imobiliária mais próxima (só até DISTANCIA_MAX_IMOBILIARIA_M do imóvel)
                    st.markdown("---")
                    st.markdown("**📞 Imobiliária mais próxima**")
                    imob = imobiliaria_proxima(infra_full)
                    if imob:
                        st.markdown(f"**{imob.get('nome') or '?'}**")
                        infos_imob = []
                        if imob.get("telefone"):
                            infos_imob.append(f"📱 {imob['telefone']}")
                        if imob.get("email"):
                            infos_imob.append(f"✉️ {imob['email']}")
                        if imob.get("website"):
                            infos_imob.append(f"🌐 [{imob['website']}]({imob['website']})")
                        if infos_imob:
                            st.markdown(" | ".join(infos_imob))
                        st.caption(
                            f"📍 {imob.get('endereco') or 'endereço não informado'} "
                            f"({int(float(imob['distancia_metros']))} m)"
                        )
                        if imob.get("opening_hours"):
                            st.caption(f"🕐 {imob['opening_hours']}")
                    else:
                        st.caption(f"{texto_sem_imobiliaria()}.")


        # Ag.5
        m2_ref = calc_constr.get("valor_m2_referencia", 0) or 0
        # Padrao: busca do Ag5 (imovel_alvo) ou do Ag3
        padrao_usado = preco.get("imovel_alvo", {}).get("padrao_construtivo", "") if preco else ""
        if not padrao_usado or padrao_usado == "?":
            padrao_usado = alvo_analise.get("padrao_acabamento", "") if alvo_analise else ""
        if not padrao_usado or padrao_usado in ("?", "desconhecido"):
            padrao_usado = "todos os comparáveis"
        area_calc = calc_constr.get("area_construida_m2", 0) or 0
        valor_med = avaliacao.get("valor_medio_imovel", 0)
        valor_liq = avaliacao.get("valor_liquidez", 0)
        with st.expander("💰 Agente Estimador de Preço"):
          if not avaliacao_confiavel:
            # Sem amostra suficiente: nao mostra passo a passo com R$ 0 (seria enganoso).
            st.warning(f"Não foi possível estimar um valor confiável para este imóvel. {sem_valor['motivo']}")
            for _av in (preco.get("avisos", []) or []):
                st.caption(f"• {_av}")
          else:
            st.write(f"Com base nos imóveis da vizinhança, o valor médio do m² da construção é **{fmt_brl(m2_ref, 2)}**.")
            st.write(f"Para o seu imóvel de {area_calc:.0f}m²:")
            st.write(f"- Valor médio estimado: **{fmt_brl(valor_med)}**")
            st.write(f"- Valor de liquidez: **{fmt_brl(valor_liq)}** (valor sugerido para venda rápida — desconto de 10%)")
            st.write(f"- Tempo estimado de venda: **{tempo}**")

            # ── PASSO A PASSO DO CÁLCULO ──────────────────────────────
            st.markdown("---")
            st.markdown("**🧮 Como chegamos neste valor (passo a passo)**")

            calc_terreno = preco.get("calculo_terreno", {})
            calc_constr_det = preco.get("calculo_construcao", {})
            terreno_aplicado = calc_terreno.get("aplicado", False)
            vmz = preco.get("valor_m2_zona_homogenea", {})
            vmz_terreno = vmz.get("terreno", {})
            vmz_constr = vmz.get("construcao", {}).get("combinados", {})

            # Conta IMOVEIS distintos (bate com a tabela "Imoveis usados"), nao os
            # valores de m2 das duas series combinadas (que dobram a contagem).
            _usados_ag5 = preco.get("comparaveis_usados", {}) or {}
            n_constr = len(_usados_ag5.get("construcao", []) or [])
            n_terreno = len(_usados_ag5.get("terreno", []) or [])

            # Passo 1 — imoveis usados
            st.markdown(
                f"**1. Imóveis usados como referência**  \n"
                f"O valor vem dos anúncios comparáveis na sua zona homogênea. "
                f"Construção: **{contagem(n_constr, 'imóvel', 'imóveis')}**. "
                + (f"Terreno: **{contagem(n_terreno, 'terreno', 'terrenos')}**." if terreno_aplicado else
                   f"Terreno não entrou: {motivo_terreno_fora(preco)}.")
            )

            # Passo 2 — m2 de construcao
            m2c_menor = vmz_constr.get("menor_valor_m2", 0) or 0
            m2c_ref = vmz_constr.get("valor_m2_referencia", 0) or 0
            st.markdown(
                f"**2. Valor do m² da construção**  \n"
                f"Faixa dos comparáveis: de {fmt_brl(m2c_menor, 2)} (mínimo) até a referência "
                f"**{fmt_brl(m2c_ref, 2)}** (média que remove os 25% mais baratos e 25% mais caros)."
            )

            # Passo 3 — terreno (se aplicável)
            if terreno_aplicado:
                m2t_ref = calc_terreno.get("valor_m2_referencia", 0) or 0
                area_ter = calc_terreno.get("area_terreno_m2", 0) or 0
                val_ter = calc_terreno.get("valor_terreno_medio", 0) or 0
                st.markdown(
                    f"**3. Valor do terreno**  \n"
                    f"m² de terreno da zona: **{fmt_brl(m2t_ref, 2)}** × {area_ter:.0f}m² do seu lote "
                    f"= **{fmt_brl(val_ter)}**."
                )
                val_constr = calc_constr_det.get("valor_construcao_medio", 0) or 0
                st.markdown(
                    f"**4. Valor da construção**  \n"
                    f"{fmt_brl(m2c_ref, 2)} × {area_calc:.0f}m² construídos = **{fmt_brl(val_constr)}**."
                )
                st.markdown(
                    f"**5. Valor final** = terreno + construção = "
                    f"{fmt_brl(val_ter)} + {fmt_brl(val_constr)} = **{fmt_brl(valor_med)}**."
                )
            else:
                st.markdown(
                    f"**3. Valor final**  \n"
                    f"{fmt_brl(m2c_ref, 2)} × {area_calc:.0f}m² = **{fmt_brl(valor_med)}**."
                )

            st.caption(f"Método estatístico: {preco.get('metodo_estatistico', '?')}")

            # Como o tempo de venda foi estimado
            liq = preco.get("liquidez_experimental", {})
            sc3 = liq.get("score_agente3_usado")
            sc4 = liq.get("score_agente4_usado")
            partes_liq = []
            if sc3 is not None:
                partes_liq.append(f"qualidade {sc3:.2f}")
            if sc4 is not None:
                partes_liq.append(f"infraestrutura {sc4:.2f}")
            if partes_liq:
                st.caption(
                    f"⏱️ Tempo de venda ({tempo}) estimado a partir de: "
                    + " + ".join(partes_liq)
                    + " (peso: qualidade 35%, infraestrutura 40%, preço 25%). Estimativa experimental."
                )

            # Se o proprio anuncio do alvo foi identificado, avisa que ele nao entrou no calculo.
            n_alvo_calc = resultado.get("resumo", {}).get("anuncios_do_alvo_marcados", 0)
            if n_alvo_calc:
                st.caption(
                    (f"🎯 1 anúncio identificado como o do seu próprio imóvel foi **excluído deste cálculo**"
                     if n_alvo_calc == 1 else
                     f"🎯 {n_alvo_calc} anúncios identificados como o do seu próprio imóvel foram "
                     f"**excluídos deste cálculo**")
                    + " para não ancorar o valor no preço pedido."
                )

            # ── COMPARÁVEIS USADOS NO CÁLCULO (com link) ──────────────
            usados = preco.get("comparaveis_usados", {}) or {}
            usados_constr = usados.get("construcao", []) or []
            usados_terr = usados.get("terreno", []) or []
            if usados_constr or usados_terr:
                st.markdown("---")
                st.markdown("**🏘️ Imóveis usados neste cálculo**")

                import pandas as _pd

                def _linhas_usados(lista, rotulo):
                    linhas = []
                    for u in lista:
                        preco_u = u.get("preco") or 0
                        try:
                            preco_u = float(preco_u)
                        except (ValueError, TypeError):
                            preco_u = 0
                        area_u = u.get("area") or u.get("area_terreno") or 0
                        url_u = u.get("url") or ""
                        # Sinais de auditoria: nao deveriam estar no calculo.
                        alertas = []
                        if u.get("eh_anuncio_do_alvo"):
                            alertas.append("🎯 seu anúncio")
                        elif u.get("possivel_anuncio_do_alvo"):
                            alertas.append("⚠️ possível alvo (perfil)")
                        if u.get("suspeita_leilao"):
                            alertas.append("⚠️ leilão?")
                        localizacao_u = (
                            "✅ Confirmado na zona" if (u.get("status_zona") or "confirmado") == "confirmado"
                            else "📍 Distância não verificada"
                        )
                        linhas.append({
                            "Tipo": rotulo,
                            "Localização": localizacao_u,
                            "Preço": fmt_brl(preco_u) if preco_u else "-",
                            "Área": f"{float(area_u):.0f}m²" if area_u else "-",
                            "Rua": u.get("rua") or "-",
                            "Bairro": u.get("bairro") or "-",
                            "Alerta": " ".join(alertas) if alertas else "",
                            "Anúncio": f"[ver]({url_u})" if url_u else "-",
                        })
                    return linhas

                linhas_all = _linhas_usados(usados_constr, "Construção") + _linhas_usados(usados_terr, "Terreno")
                if linhas_all:
                    df_usados = _pd.DataFrame(linhas_all)
                    st.markdown(df_usados.to_markdown(index=False), unsafe_allow_html=True)
                    st.caption(
                        f"{contagem(len(usados_constr), 'imóvel usado', 'imóveis usados')} no m² da construção e "
                        f"{contagem(len(usados_terr), 'terreno', 'terrenos')} no m² do terreno. "
                        f"São exatamente os anúncios que entraram na média."
                    )
                    usados_todos = usados_constr + usados_terr
                    n_alvo_usado = sum(1 for u in usados_todos if u.get("eh_anuncio_do_alvo"))
                    n_possivel = sum(
                        1 for u in usados_todos
                        if u.get("possivel_anuncio_do_alvo") and not u.get("eh_anuncio_do_alvo")
                    )
                    n_leilao = sum(1 for u in usados_todos if u.get("suspeita_leilao"))
                    if n_alvo_usado or n_leilao:
                        st.warning(
                            "⚠️ No cálculo: " + " e ".join(
                                p for p in (
                                    contagem(n_alvo_usado, "anúncio do seu próprio imóvel (🎯)",
                                             "anúncios do seu próprio imóvel (🎯)") if n_alvo_usado else "",
                                    contagem(n_leilao, "possível leilão (⚠️ leilão?)",
                                             "possíveis leilões (⚠️ leilão?)") if n_leilao else "",
                                ) if p
                            ) + ". Confira pelo link — imóveis assim distorcem o valor e idealmente "
                            "não deveriam entrar na média."
                        )
                    if n_possivel:
                        st.caption(
                            f"⚠️ {contagem(n_possivel, 'imóvel', 'imóveis')} com perfil muito parecido com o seu "
                            f"(\"possível alvo\": mesma área e bairro, preço ou cômodos parecidos, ou o "
                            f"mesmo prédio). Sem prova de que sejam o seu anúncio, continuam no cálculo."
                        )

            # Avisos do Ag5 (amostra insuficiente, terrenos descartados por sanidade, etc.)
            avisos_ag5 = preco.get("avisos", []) or []
            if avisos_ag5:
                st.markdown("---")
                st.markdown("**⚠️ Observações sobre a confiabilidade**")
                for _av in avisos_ag5:
                    st.caption(f"• {_av}")

            # Comparação com preço anunciado
            if imovel_alvo_export.get("price") and imovel_alvo_export["price"] > 0:
                st.markdown("---")
                preco_anunc = imovel_alvo_export["price"]
                if valor_med > 0:
                    diferenca_pct = ((preco_anunc - valor_med) / valor_med) * 100
                    if diferenca_pct > 5:
                        st.warning(f"O preço anunciado ({fmt_brl(preco_anunc)}) está {diferenca_pct:.1f}% acima do valor médio da região ({fmt_brl(valor_med)})")
                    elif diferenca_pct < -5:
                        st.success(f"O preço anunciado ({fmt_brl(preco_anunc)}) está {abs(diferenca_pct):.1f}% abaixo do valor médio da região ({fmt_brl(valor_med)}) — boa oportunidade")
                    else:
                        st.info(f"O preço anunciado ({fmt_brl(preco_anunc)}) está alinhado com o valor médio da região ({fmt_brl(valor_med)}) — diferença de {abs(diferenca_pct):.1f}%")

        st.divider()

        # ── CONFERENCIA (modo conferencia; MOSTRAR_FUNIL=0 desliga) ─────────
        # Verificacoes automaticas em frases simples, uma por agente, fechada por
        # padrao. O detalhe tecnico fica no Excel (aba Verificacoes) e no banco.
        if funil_ligado():
            conferencia = resumo_conferencia(resultado, resultado.get("verificacoes"))
            with st.expander(conferencia["titulo"], expanded=False):
                st.markdown("\n".join(f"- {frase}" for frase in conferencia["frases"]).replace("$", "\\$"))

        # ── FUNIL DOS ANUNCIOS (conferencia; MOSTRAR_FUNIL=0 desliga) ─────
        # Onde cada anuncio saiu (agente) e por que, ou se entrou no calculo.
        if funil_ligado():
            mostrar_funil(st, resultado)

        # ── BOTÃO EXPORTAR LAUDO (TXT) ─────────────────────────────
        # No TXT usamos "R$" limpo (sem o escape \$ de markdown do fmt_brl).
        def _brl_txt(v):
            return fmt_brl(v).replace("R\\$", "R$")

        if avaliacao_confiavel:
            bloco_resultado = (
                f"Valor Médio Estimado: {_brl_txt(avaliacao.get('valor_medio_imovel', 0))}\n"
                f"Valor de Liquidez (-10%): {_brl_txt(avaliacao.get('valor_liquidez', 0))}\n"
                f"Tempo Estimado de Venda: {liquidez_info.get('tempo_estimado', '?')}"
            )
            if preco.get("aviso_infraestrutura"):
                bloco_resultado += f"\n({preco['aviso_infraestrutura']})"
        else:
            bloco_resultado = "\n".join(
                [f"Não foi possível estimar um valor confiável para este imóvel. {sem_valor['motivo']}"]
                + [f"- {_fazer}" for _fazer in sem_valor["fazer"]]
            )

        for _url in excluidos_alvo:
            bloco_resultado += f"\nAtenção: encontramos o anúncio do próprio imóvel e ele saiu do cálculo ({_url or 'sem link'})."
        for s_alvo in suspeitos_alvo:
            bloco_resultado += (
                f"\nAtenção: {'provável' if s_alvo['provavel'] else 'possível'} anúncio do próprio imóvel, "
                f"continua no cálculo ({s_alvo['motivo']}; {s_alvo['url'] or 'sem link'})."
            )
        if resultado.get("aviso_raio"):
            bloco_resultado += f"\nAtenção: {resultado['aviso_raio']}"
        if (preco or {}).get("aviso_terreno"):
            bloco_resultado += f"\nAtenção: {preco['aviso_terreno']}"
        if texto_aviso_lancamento(preco):
            bloco_resultado += f"\nAtenção: {texto_aviso_lancamento(preco)}"
        for alerta_tela in alertas_na_tela(resultado):
            # No laudo nao ha a lista de anuncios: aponta para a tela e o Excel.
            texto_alerta = (
                str(alerta_tela.get("mensagem") or "")
                .replace("Confira os anúncios abaixo.", "Confira os anúncios na tela ou no Excel.")
                .replace("Confira os anúncios.", "Confira os anúncios na tela ou no Excel.")
                .replace("confira esses anúncios.", "confira esses anúncios na tela ou no Excel.")
            )
            bloco_resultado += f"\nAtenção: {texto_alerta}"

        linhas_leilao = linhas_laudo_leilao(resultado.get("leilao"), _brl_txt)
        bloco_leilao = "\n".join(
            ["", "AVALIAÇÃO DE LEILÃO (CAIXA)", "-" * 50] + linhas_leilao + [""]
        ) if linhas_leilao else ""

        # Imobiliaria mais proxima: so quando o Agente 4 avaliou o entorno.
        infra_laudo = resultado.get("infraestrutura") or {}
        bloco_imobiliaria = "\n".join(
            ["", "IMOBILIÁRIA MAIS PRÓXIMA", "-" * 50] + linhas_laudo_imobiliaria(infra_laudo) + [""]
        ) if infra_laudo and infra_laudo.get("status") != "endereco_nao_localizado" else ""

        laudo_texto = f"""LAUDO DE AVALIAÇÃO IMOBILIÁRIA
{'='*50}

Imóvel: {rua}, {numero} - {bairro}, {cidade}/{estado}
Tipo: {tipo} | Área: {imovel_alvo_export.get('area') or 0}m² | Terreno: {imovel_alvo_export.get('area_terreno') or 0}m²
Quartos: {quartos} | Banheiros: {banheiros} | Vagas: {vagas if vagas is not None else 'não informado'}

RESULTADO DA AVALIAÇÃO
{'-'*50}
{bloco_resultado}
{bloco_leilao}{bloco_imobiliaria}
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

        # Resultado desta avaliacao em Excel (mesmo conteudo gravado no banco):
        # aba Resumo (Campo | Valor) e aba Comparaveis (um anuncio por linha).
        registro_excel = resultado.get("registro") or {}
        if registro_excel.get("execucao"):
            from services.registro_execucao import excel_resultado
            st.download_button(
                label="📥 Baixar resultado (Excel)",
                data=excel_resultado(
                    registro_excel["execucao"], registro_excel.get("comparaveis") or [],
                    funil=montar_funil(resultado) if funil_ligado() else None,
                ),
                file_name=f"resultado_{cidade}_{bairro}.xlsx".replace(" ", "_"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    else:
        st.error("Não foi possível calcular o preço. Verifique os dados e tente novamente.")
        mostrar_avaliacao_leilao(resultado.get("leilao"))
        if isinstance(resultado, dict):
            st.json(resultado)
