"""
Tela e terminal usam o MESMO fluxo (services/pipeline.py). Agentes trocados por
versoes falsas: sem rede, sem banco.

    .venv/Scripts/python.exe -m tests.test_pipeline_unico
"""
import os
import re
import sys

sys.path.insert(0, ".")
os.environ["DATABASE_URL"] = ""

from agents import collector, comparables, infra_evaluator, price_liquidity, text_analyzer
from services import pipeline

CHAMADAS = []


def _instalar_agentes_falsos(anuncios=True, comparaveis=True):
    """Troca as funcoes dos agentes por versoes que so registram como foram chamadas."""
    CHAMADAS.clear()

    def geocodificar(**kw):
        CHAMADAS.append(("geocodificar", kw))
        return -23.4, -51.4, "rua_numero", "Rua X, 1"

    def coletar(**kw):
        CHAMADAS.append(("coletar", kw))
        if not anuncios:
            return []
        return [{"id": 1, "price": 300000, "area": 70, "source": "VivaReal", "street": "Rua X",
                 "escopo_busca": "rua+bairro+proximidade", "duplicatas": [{"source": "Chaves na Mão", "url": "u2"}]}]

    def identificar(**kw):
        CHAMADAS.append(("identificar", kw))
        lista = [{"id": 1, "cluster": "A"}] if comparaveis else []
        return {"comparaveis": lista, "terrenos": [{"id": 9, "propertyType": "Terrenos"}],
                "resumo": {"cluster_a": len(lista)}}

    def zona(**kw):
        CHAMADAS.append(("zona", kw))
        return {"comparaveis_confirmados": [], "fora_zona": [], "zona_homogenea": {"raio_metros": 500}}

    def ag3(imovel_alvo, id_execucao=None):
        CHAMADAS.append(("ag3", {"imovel_alvo": imovel_alvo, "id_execucao": id_execucao}))
        return {"resumo": {"total_analisados": 1}}

    def ag4(id_execucao=None):
        CHAMADAS.append(("ag4", {"id_execucao": id_execucao}))
        return {"scores": {"score_final": 0.5}}

    def ag5(imovel_alvo_extra=None, id_execucao=None):
        CHAMADAS.append(("ag5", {"imovel_alvo_extra": imovel_alvo_extra, "id_execucao": id_execucao}))
        return {"status_avaliacao": "ok", "avaliacao_confiavel": True,
                "avaliacao_planilha": {"valor_medio_imovel": 300000, "valor_liquidez": 270000},
                "comparaveis_usados": {"construcao": [], "terreno": []}}

    comparables._geocodificar_com_fallback = geocodificar
    comparables.reiniciar_contagem_tomtom = lambda: None
    comparables.identificar_comparaveis = identificar
    comparables.analisar_zona_homogenea = zona
    collector.coletar_imoveis = coletar
    collector.resumo_da_coleta = lambda id_execucao: {"brutos": 0}
    text_analyzer.analisar_comparaveis = ag3
    infra_evaluator.avaliar_infraestrutura = ag4
    price_liquidity.estimar_preco = ag5
    os.environ["GOOGLE_MAPS_KEY"] = "teste"


def _alvo():
    return pipeline.montar_imovel_alvo(
        rua="Rua X", numero="1", bairro="Centro", cidade="Arapongas", estado="PR", tipo="Casa",
        area=70, area_terreno=128, quartos=2, banheiros=1, vagas=1,
        fotos=["https://a/1.jpg", "ftp://b", "", "https://a/2.jpg"],
    )


def test_tela_e_terminal_chamam_o_fluxo_unico():
    tela = open("app/paginas/avaliacao.py", encoding="utf-8").read()
    graph = open("app/graph.py", encoding="utf-8").read()
    main = open("app/main.py", encoding="utf-8").read()
    for nome, codigo in (("tela", tela), ("graph", graph), ("main", main)):
        assert "executar_avaliacao" in codigo, nome
        # Nenhum deles chama os agentes direto (so o services/pipeline.py).
        for funcao in ("coletar_imoveis(", "identificar_comparaveis(", "analisar_zona_homogenea(",
                       "analisar_comparaveis(", "avaliar_infraestrutura("):
            assert not re.search(rf"(?<![\w.]){re.escape(funcao)}", codigo), f"{nome} chama {funcao} direto"


def test_montar_imovel_alvo_como_a_tela():
    a = _alvo()
    assert a["tipo"] == "house" and a["propertyType"] == "Casas" and a["localizacao"] == "Arapongas, PR"
    assert a["images"] == ["https://a/1.jpg", "https://a/2.jpg"]    # so http
    assert a["descricao_gerada"] is True and "Casa com 70m²" in a["description"]
    assert a["em_condominio"] is False and "price" not in a
    apto = pipeline.montar_imovel_alvo(rua="R", numero="", bairro="B", cidade="C", estado="SP", tipo="Apartamento",
                                       area=50, quartos=1, banheiros=1, preco=250000)
    assert apto["em_condominio"] is None and apto["area_terreno"] is None and apto["pricePerSqm"] == 5000


def test_fluxo_chama_os_agentes_como_a_tela():
    _instalar_agentes_falsos()
    eventos = []

    class Obs(pipeline.Observador):
        def etapa(self, nome, **d):
            eventos.append(nome)

    saida = pipeline.executar_avaliacao(_alvo(), obs=Obs(), gravar=False)
    assert saida["parada"] is None and saida["resultado"]["preco_estimado"]["status_avaliacao"] == "ok"
    nomes = [n for n, _ in CHAMADAS]
    assert nomes[:4] == ["geocodificar", "coletar", "identificar", "zona"], nomes
    assert set(nomes[4:]) == {"ag3", "ag4", "ag5"} and nomes[-1] == "ag5", nomes
    kw = dict(CHAMADAS)
    # O que o terminal antigo nao fazia:
    assert kw["coletar"]["lat_alvo"] == -23.4 and kw["coletar"]["nivel_geo_alvo"] == "rua_numero"
    assert {"id": 9, "propertyType": "Terrenos"} in kw["zona"]["imoveis"]        # terrenos junto, como na tela
    assert kw["ag3"]["imovel_alvo"]["rua"] == "Rua X"                            # Agente 3 recebe o imovel
    assert kw["ag5"]["imovel_alvo_extra"]["escopo_busca"] == "rua+bairro+proximidade"
    assert eventos[0] == "inicio" and eventos[-1] == "fim" and "zona_fim" in eventos
    assert saida["contexto"]["resumo"]["duplicatas_descartadas"] == 1
    assert "verificacoes" in saida["resultado"]


def test_sem_anuncios_e_sem_comparaveis_param_o_fluxo():
    _instalar_agentes_falsos(anuncios=False)
    saida = pipeline.executar_avaliacao(_alvo(), gravar=False)
    assert saida["parada"] == "sem_anuncios"
    assert saida["resultado"]["preco_estimado"]["status_avaliacao"] == "sem_amostra"
    _instalar_agentes_falsos(comparaveis=False)
    saida = pipeline.executar_avaliacao(_alvo(), gravar=False)
    assert saida["parada"] == "sem_comparaveis" and saida["resultado"] is None


def test_terminal_usa_o_fluxo_e_nao_grava_por_padrao():
    _instalar_agentes_falsos()
    gravados = []
    import services.banco as banco
    original = banco.gravar_em_segundo_plano
    banco.gravar_em_segundo_plano = lambda *a, **k: gravados.append(a)
    try:
        from app.graph import executar_pipeline
        r = executar_pipeline({"rua": "Rua X", "numero": "1", "bairro": "Centro", "cidade": "Arapongas",
                               "estado": "PR", "tipo": "house", "propertyType": "Casas", "area": 70,
                               "bedrooms": 2, "bathrooms": 1})
        assert r["status"].startswith("completo"), r["status"]
        assert r["preco_estimado"]["avaliacao_planilha"]["valor_medio_imovel"] == 300000
        assert gravados == []
        executar_pipeline({"rua": "Rua X", "bairro": "Centro", "cidade": "Arapongas", "estado": "PR",
                           "tipo": "house", "area": 70, "bedrooms": 2, "bathrooms": 1}, gravar=True)
        assert len(gravados) == 1
    finally:
        banco.gravar_em_segundo_plano = original


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
