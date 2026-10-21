"""
Verificacoes automaticas (services/verificacoes.py): para cada uma, um caso que
passa e um que falha. O resultado de base usa o Agente 5 de verdade. Sem rede.

    .venv/Scripts/python.exe -m tests.test_verificacoes
"""
import copy
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from agents.price_liquidity import executar_agente5
from services.verificacoes import ordenar_para_tela, refazer_conta_agente5, verificar_execucao

ID = "exec-1"


def casa(i, **extra):
    return {"url": f"https://x/{i}", "propertyType": "Casas", "price": 500_000 + i * 37_000, "area": 100 + i * 4,
            "street": f"Rua {i}", "neighborhood": "Centro", "city": "Curitiba", "state": "PR", "cluster": "A",
            "status_julgamento": "JULGADO_LLM", "provider_llm": "gemini", "modelo_llm": "gemini-2.5-flash",
            "checagem_alvo": {"resultado": "nao", "score": 0.0, "sinais": []},
            "classificacao_zona": "na_zona", "distancia_metros": 100 + i * 50,
            "id_execucao": ID, "coletado_em": "2026-10-21T09:00:00", **extra}


def terreno(i, **extra):
    return {"url": f"https://t/{i}", "propertyType": "Terrenos", "price": 200_000 + i * 15_000, "area": 300 + i * 10,
            "city": "Curitiba", "state": "PR", "cluster": "terreno", "status_julgamento": "SEPARADO_TIPO",
            "checagem_alvo": {"resultado": "nao", "score": 0.0, "sinais": []},
            "classificacao_zona": "na_zona", "distancia_metros": 200 + i * 30,
            "id_execucao": ID, "coletado_em": "2026-10-21T09:00:00", **extra}


def montar(area_terreno=None, n_casas=6, n_terrenos=2):
    casas = [casa(i) for i in range(n_casas)]
    reprovada = casa(90, cluster="B", status_julgamento="REPROVADO_PRE_CLASSIFICACAO",
                     classificacao_zona=None, distancia_metros=None)
    terrenos = [terreno(i) for i in range(n_terrenos)]
    alvo5 = {"propertyType": "casa", "area": 120, "area_terreno": area_terreno}
    ag5 = executar_agente5(alvo5, copy.deepcopy(terrenos), copy.deepcopy(casas), {}, {})
    ag5["id_execucao"] = ID
    ag5["zona_calculada_nesta_avaliacao"] = True
    return {
        "id_execucao": ID,
        "imovel_alvo": {"cidade": "Curitiba", "estado": "PR", "tipo": "house", "area": 120,
                        "geocodificacao_nivel": "rua"},
        "localizacao_alvo": "rua",
        "resumo_coleta": {"fontes": {"athena": {"consultada": True, "respondeu": True, "anuncios": 9, "falhas": []},
                                     "apify": {"consultada": False, "motivo": "não consultado"}},
                          "contagem": {"antes_dos_repetidos": n_casas + n_terrenos + 2, "unicos": n_casas + n_terrenos + 1,
                                       "repetidos_juntados": 1, "cortados_pelo_limite": 0, "repetidos_dos_cortados": 0,
                                       "mantidos": n_casas + n_terrenos + 1, "repetidos": 1}},
        "falhas": [],
        "comparaveis": casas + [reprovada],
        "terrenos": terrenos,
        "resumo": {"cluster_a": n_casas, "llm_nao_julgados": 0},
        "duplicatas_descartadas": [{"Mantido": "VivaReal", "Preço": 500000, "Área": 100, "Descartado": "ImovelWeb",
                                    "Anúncio descartado": "https://iw/1", "Motivo": "mesmo_codigo"}],
        "zona_homogenea": {"id_execucao": ID, "coordenadas_alvo": {"lat": -25.4, "lon": -49.2},
                           "raio_final_m": 500, "comparaveis_confirmados": casas + terrenos, "terrenos": terrenos},
        "analise_qualitativa": {"id_execucao": ID,
                                "imovel_alvo": {"analise_qualitativa": {"status": "ok", "scores": {"score_qualitativo": 0.5}}},
                                "comparaveis": [dict(c, analise_qualitativa={"status": "ok", "scores": {"score_qualitativo": 0.6}})
                                                for c in casas]},
        "infraestrutura": {"id_execucao": ID, "scores": {"score_final": 0.72}},
        "preco_estimado": ag5,
    }


def _v(resultado, inicio):
    """A verificacao cujo texto comeca com `inicio`."""
    achadas = [v for v in verificar_execucao(resultado) if v["verificacao"].startswith(inicio)]
    assert len(achadas) == 1, (inicio, [v["verificacao"] for v in verificar_execucao(resultado)])
    return achadas[0]


def _passa(resultado, inicio):
    v = _v(resultado, inicio)
    assert v["ok"] is True, v


def _falha(resultado, inicio):
    v = _v(resultado, inicio)
    assert v["ok"] is False, v
    return v


# ---------------------------------------------------------------- base
def test_base_tudo_passa():
    vs = verificar_execucao(montar())
    assert all(v["ok"] is True for v in vs), [v for v in vs if v["ok"] is not True]
    assert all(set(v) == {"agente", "verificacao", "esperado", "encontrado", "ok"} for v in vs)


def test_falhas_primeiro_na_tela():
    r = montar()
    r["preco_estimado"]["id_execucao"] = "outra"
    r.pop("resumo_coleta")                     # coleta antiga: fontes e contagens nao verificaveis
    ordem = [v["ok"] for v in ordenar_para_tela(verificar_execucao(r))]
    assert ordem == sorted(ordem, key=lambda ok: {False: 0, None: 1, True: 2}[ok]) and ordem[0] is False
    assert None in ordem and ordem[-1] is True


def test_resultado_vazio_nao_quebra():
    assert isinstance(verificar_execucao({}), list)


# ---------------------------------------------------------------- geral
def test_geral_funil_uma_etapa_por_anuncio():
    _passa(montar(), "Cada anúncio aparece em exatamente uma etapa")
    r = montar()
    r["comparaveis"].append(dict(r["comparaveis"][0]))     # mesmo anuncio duas vezes
    v = _falha(r, "Cada anúncio aparece em exatamente uma etapa")
    assert "1 em mais de uma etapa" in v["encontrado"], v


def test_geral_resultados_desta_execucao():
    _passa(montar(), "Os resultados dos Agentes 2 a 5 são desta execução")
    r = montar()
    r["infraestrutura"]["id_execucao"] = "rodada-anterior"
    assert "Agente 4: rodada-anterior" in _falha(r, "Os resultados dos Agentes 2 a 5")["encontrado"]


# ---------------------------------------------------------------- agente 1
def test_ag1_cidade_uf():
    _passa(montar(), "Todos os anúncios são da cidade/UF pedidas")
    r = montar()
    r["comparaveis"][0]["city"] = "Colombo"
    assert "1 de outra cidade (Colombo/PR)" in _falha(r, "Todos os anúncios são da cidade")["encontrado"]


# ---------------------------------------------------------------- agente 2
def test_ag2_decisao_de_cada_imovel():
    v = _v(montar(), "Todo imóvel construído tem decisão")
    assert v["ok"] and "1 pela pré-classificação, 6 pela IA (gemini/gemini-2.5-flash: 6)" in v["encontrado"], v
    r = montar()
    r["comparaveis"][1].update(status_julgamento="NAO_JULGADO", cluster=None)
    assert "1 sem julgamento" in _falha(r, "Todo imóvel construído tem decisão")["encontrado"]


def test_ag2_distancia_dos_confirmados():
    _passa(montar(), "Todo comparável confirmado na zona tem distância")
    r = montar()
    r["zona_homogenea"]["comparaveis_confirmados"][2]["distancia_metros"] = 900
    assert "1 fora do raio" in _falha(r, "Todo comparável confirmado na zona")["encontrado"]


def test_ag2_checagem_do_proprio_anuncio():
    _passa(montar(), "A checagem do próprio anúncio rodou")
    r = montar()
    del r["terrenos"][0]["checagem_alvo"]
    assert "1 sem" in _falha(r, "A checagem do próprio anúncio rodou")["encontrado"]


# ---------------------------------------------------------------- agente 3
def test_ag3_avaliados_e_notas():
    _passa(montar(), "Todo comparável que chegou foi avaliado")
    r = montar()
    r["analise_qualitativa"]["comparaveis"][0]["analise_qualitativa"]["scores"]["score_qualitativo"] = 1.4
    _falha(r, "Todo comparável que chegou foi avaliado")
    r = montar()
    r["analise_qualitativa"]["comparaveis"].pop()          # um nao avaliado, sem falha registrada
    _falha(r, "Todo comparável que chegou foi avaliado")
    r["analise_qualitativa"] = {}
    r["falhas"] = ["agente3: TimeoutError"]                 # falha registrada: ok
    _passa(r, "Todo comparável que chegou foi avaliado")


# ---------------------------------------------------------------- agente 4
def test_ag4_localizacao_e_nota():
    _passa(montar(), "Rodou com localização precisa")
    r = montar()
    r["infraestrutura"]["scores"]["score_final"] = 1.3
    _falha(r, "Rodou com localização precisa")
    r = montar()
    r["infraestrutura"] = {"id_execucao": ID, "status": "endereco_nao_localizado"}
    r["preco_estimado"]["aviso_infraestrutura"] = None
    _falha(r, "Rodou com localização precisa")              # sem o aviso de nota neutra
    r["preco_estimado"]["aviso_infraestrutura"] = "Tempo estimado sem a infraestrutura..."
    _passa(r, "Rodou com localização precisa")


# ---------------------------------------------------------------- agente 5
def test_ag5_refaz_a_conta():
    _passa(montar(), "Refazer a conta de forma independente")
    _passa(montar(area_terreno=250, n_terrenos=6), "Refazer a conta de forma independente")   # separa o terreno
    r = montar()
    r["preco_estimado"]["avaliacao_planilha"]["valor_medio_imovel"] += 50
    _falha(r, "Refazer a conta de forma independente")


def test_ag5_refaz_a_conta_de_apartamento():
    aptos = [{"propertyType": "apartamento", "price": p, "area": a, "url": f"https://a/{p}"}
             for p, a in ((300000, 93), (499900, 120), (630000, 110), (648000, 117), (650000, 77), (790000, 106))]
    ag5 = executar_agente5({"propertyType": "apartamento", "area": 109}, [], aptos, {}, {})
    assert abs(refazer_conta_agente5(ag5) - ag5["avaliacao_planilha"]["valor_medio_imovel"]) <= 1


def test_ag5_usados_na_zona():
    _passa(montar(), "Todos os comparáveis usados estão na zona")
    r = montar()
    r["preco_estimado"]["comparaveis_usados"]["construcao"][0]["url"] = "https://longe/1"
    _falha(r, "Todos os comparáveis usados estão na zona")


def test_ag5_anuncio_do_proprio_imovel_fora_dos_usados():
    _passa(montar(), "Nenhum anúncio do próprio imóvel entrou nos usados")
    r = montar()
    r["comparaveis"][0]["eh_anuncio_do_alvo"] = True
    _falha(r, "Nenhum anúncio do próprio imóvel entrou nos usados")


def test_ag5_terrenos_coerentes_com_a_decisao():
    _passa(montar(), "Terrenos usados coerentes")                       # nao separou, 0 usados
    _passa(montar(area_terreno=250, n_terrenos=6), "Terrenos usados coerentes")   # separou, 6 usados
    r = montar()
    r["preco_estimado"]["comparaveis_usados"]["terreno"] = [{"url": "https://t/0", "preco": 200000, "area": 300}]
    v = _falha(r, "Terrenos usados coerentes")   # o bug de antes do commit 0b47594
    assert v["encontrado"] == "não separou o terreno; 1 terrenos usados", v


def test_ag5_sem_valor_so_com_poucos_comparaveis():
    _passa(montar(), "Sem valor ⇔ menos comparáveis")
    _passa(montar(n_casas=4), "Sem valor ⇔ menos comparáveis")           # 4 < 5: sem valor, coerente
    r = montar()
    r["preco_estimado"]["avaliacao_confiavel"] = False                   # sem valor com 6 validos
    _falha(r, "Sem valor ⇔ menos comparáveis")


# ---------------------------------------------------------------- tela e Excel
def _com_uma_falha():
    r = montar()
    r["infraestrutura"]["id_execucao"] = "rodada-anterior"
    r["status"] = "completo"
    r["verificacoes"] = verificar_execucao(r)
    return r


def test_tela_mostra_a_lista_com_falhas_primeiro():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app/interface.py", default_timeout=60)
    at.session_state["resultado"] = _com_uma_falha()
    at.session_state["imovel_alvo_dados"] = {"area": 120, "tipo": "house"}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    rotulo = next(e.label for e in at.expander if e.label.startswith("🧪 Verificações automáticas"))
    assert "1 ❌ · 0 ⚪" in rotulo, rotulo
    lista = next(m.value for m in at.markdown if m.value.startswith("- ❌"))
    itens = [l for l in lista.splitlines() if l.startswith("- ")]
    assert itens[0].startswith("- ❌ **Geral** · Os resultados dos Agentes 2 a 5") and itens[1].startswith("- ✅"), itens[:2]
    assert itens[-1].startswith("- ✅")


def test_excel_tem_a_aba_verificacoes():
    import io
    from openpyxl import load_workbook
    from services.registro_execucao import excel_resultado
    r = _com_uma_falha()
    livro = load_workbook(io.BytesIO(excel_resultado({"alertas": [], "verificacoes": r["verificacoes"]}, [])))
    linhas = list(livro["Verificações"].iter_rows(values_only=True))
    assert linhas[0] == ("Resultado", "Agente", "Verificação", "Esperado", "Encontrado")
    assert linhas[1][0] == "❌ FALHOU" and linhas[-1][0] == "✅ OK" and len(linhas) == 1 + len(r["verificacoes"])
    assert "Verificações" not in load_workbook(io.BytesIO(excel_resultado({"alertas": []}, []))).sheetnames


def test_banco_grava_a_coluna():
    from services.banco import COLUNAS_EXECUCOES, COLUNAS_JSON
    assert "verificacoes" in COLUNAS_EXECUCOES and "verificacoes" in COLUNAS_JSON


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    falhas = 0
    for nome, fn in testes:
        try:
            fn()
            print(f"OK    {nome}")
        except AssertionError as e:
            falhas += 1
            print(f"FALHA {nome}: {e}")
        except Exception as e:
            falhas += 1
            print(f"ERRO  {nome}: {type(e).__name__}: {e}")
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
