"""
Testes do registro no banco (services/registro_execucao.py e services/banco.py).
Sem banco real: confere a montagem das linhas, a coerencia com db/schema.sql e que
uma falha do banco nunca quebra nem trava.

    .venv/Scripts/python.exe -m tests.test_banco
"""
import re
import sys
import time

sys.path.insert(0, ".")

from services.banco import COLUNAS_COMPARAVEIS, COLUNAS_EXECUCOES, gravar_execucao
from services.leilao import avaliar_leilao
from services.registro_execucao import montar_registro, versao_codigo


def _ag5():
    return {
        "status_avaliacao": "ok",
        "avaliacao_confiavel": True,
        "zona_calculada_nesta_avaliacao": True,
        "avaliacao_planilha": {"valor_medio_imovel": 716036.0, "valor_liquidez": 644432.4},
        "valor_m2_zona_homogenea": {
            "terreno": {"valor_m2_referencia": 900.0},
            "construcao": {"combinados": {"valor_m2_referencia": 3500.0}},
        },
        "liquidez_experimental": {"tempo_estimado": "60 a 90 dias"},
        "comparaveis_usados": {
            "construcao": [
                {"url": "https://a/1", "rua": "Rua A, 10", "bairro": "Centro", "preco": 500000, "area": 100,
                 "status_zona": "confirmado", "portal": "VivaReal"},
                {"url": "https://a/2", "rua": "Rua B", "bairro": "Centro", "preco": 400000, "area": 80,
                 "status_zona": "fallback", "portal": "ImovelWeb"},
            ],
            "terreno": [{"url": "https://t/1", "preco": 200000, "area": 250, "status_zona": "confirmado"}],
        },
        "comparaveis_descartados": {
            "construcao": [{"url": "https://a/3", "preco": 9000000, "area": 100, "status_zona": "confirmado"}],
            "terreno": [],
        },
        "avisos": [],
    }


def _registro(**extra):
    ag5 = _ag5()
    entrada = {"origem": "CAIXA", "valor_minimo": 323158, "valor_avaliacao": 410000,
               "modalidade": "Venda Online", "codigo_caixa": "1444400000000", "link": "https://caixa/1"}
    alvo = {"tipo": "house", "rua": "Rua X", "numero": "100", "bairro": "Centro", "cidade": "Curitiba",
            "estado": "PR", "area": 150, "area_terreno": 300, "bedrooms": 3, "bathrooms": 2}
    coletados = [{"fonte_dados": "Athena/S3", "duplicatas": [{}, {}]}, {"fonte_dados": "Athena/S3"}, {}]
    args = dict(
        id_execucao="abc123", imovel_alvo=alvo, leilao_entrada=entrada,
        leilao=avaliar_leilao(ag5, 323158, 410000), imoveis_coletados=coletados,
        resultado_ag2={"resumo": {"cluster_a": 12}, "comparaveis": [
            {"status_julgamento": "JULGADO_LLM", "provider_llm": "groq", "modelo_llm": "gpt-oss-120b"}]},
        zona_resultado={"resumo_zona": {"raio_usado_metros": 450, "confirmados": 9},
                        "zona_homogenea": {"provider_visao": "gemini"}},
        resultado_ag3={}, resultado_ag4={"scores": {"provider_llm": "Gemini"}},
        resultado_ag5=ag5, tempos={"total": 300.5}, falhas=["agente3: Timeout"],
    )
    args.update(extra)
    return montar_registro(**args)


def test_execucao_tem_os_campos_principais():
    e, _ = _registro()
    assert e["origem"] == "CAIXA" and e["tipo"] == "casa" and e["uf"] == "PR"
    assert e["endereco"] == "Rua X, 100"
    assert e["valor_minimo"] == 323158 and e["valor_avaliacao"] == 410000
    assert e["decisao"] == "Não descartar" and round(e["lance_maximo"]) == 415763 and round(e["sobra"]) == 92605
    assert e["status_agente5"] == "ok" and e["liquidez"] == 644432.4 and e["valor_mercado"] == 716036.0
    assert e["anuncios_encontrados"] == 3 and e["repetidos"] == 2 and e["parecidos"] == 12
    assert e["confirmados_na_zona"] == 9 and e["raio_zona_m"] == 450
    assert e["usados_por_fallback"] == 1 and e["terrenos_usados"] == 1
    assert e["qtd_comparaveis_construcao"] == 2 and e["qtd_terrenos"] == 1
    assert e["tempo_venda"] == "60 a 90 dias" and e["tempo_s"] == 300.5
    assert e["parametros"]["fator_lucro_leilao"] == 1.55 and e["parametros"]["min_amostras_confiavel"] == 3
    assert e["modelos_ia"]["agente4"] == "Gemini" and e["fontes"]["anuncios_apify"] == 1
    assert e["falhas"]["falhas"] == ["agente3: Timeout"]


def test_sem_leilao_decisao_fica_vazia():
    e, _ = _registro(leilao=None, leilao_entrada=None)
    assert e["decisao"] is None and e["lance_maximo"] is None and e["origem"] == "CAIXA"


def test_comparaveis_usados_e_descartados():
    _, linhas = _registro()
    assert len(linhas) == 4, linhas
    assert sum(1 for l in linhas if l["entrou_no_calculo"]) == 3
    descartado = next(l for l in linhas if not l["entrou_no_calculo"])
    assert descartado["link"] == "https://a/3" and descartado["valor_m2"] == 90000.0
    fallback = next(l for l in linhas if l["link"] == "https://a/2")
    assert fallback["status_zona"] == "fallback" and fallback["portal"] == "ImovelWeb" and fallback["valor_m2"] == 5000.0
    assert {l["tipo"] for l in linhas} == {"construcao", "terreno"}
    assert all(l["id_execucao"] == "abc123" for l in linhas)


def test_linhas_tem_exatamente_as_colunas_gravadas():
    e, linhas = _registro()
    assert set(COLUNAS_EXECUCOES) <= set(e), set(COLUNAS_EXECUCOES) - set(e)
    assert all(set(COLUNAS_COMPARAVEIS) <= set(l) for l in linhas)


def test_colunas_batem_com_schema_sql():
    sql = open("db/schema.sql", encoding="utf-8").read()

    def colunas(tabela):
        corpo = re.search(rf"CREATE TABLE IF NOT EXISTS {tabela} \((.*?)\n\);", sql, re.S).group(1)
        nomes = set()
        for linha in corpo.splitlines():
            linha = linha.split("--")[0].strip()
            m = re.match(r"([a-z_0-9]+)\s+[A-Z]", linha)
            if m:
                nomes.add(m.group(1))
        return nomes

    no_schema_exec = colunas("execucoes") - {"data_hora", "faz_sentido", "observacao"}
    assert no_schema_exec == set(COLUNAS_EXECUCOES), (no_schema_exec ^ set(COLUNAS_EXECUCOES))
    no_schema_comp = colunas("comparaveis") - {"id"}
    assert no_schema_comp == set(COLUNAS_COMPARAVEIS), (no_schema_comp ^ set(COLUNAS_COMPARAVEIS))


def test_sem_database_url_nao_grava_e_nao_quebra():
    e, linhas = _registro()
    assert gravar_execucao(e, linhas, database_url="") is False


def test_banco_fora_do_ar_nao_quebra_nem_trava():
    e, linhas = _registro()
    t0 = time.time()
    ok = gravar_execucao(e, linhas, database_url="postgresql://u:p@127.0.0.1:1/db?connect_timeout=3")
    assert ok is False and time.time() - t0 < 20


def _abrir_excel():
    import io
    from openpyxl import load_workbook
    from services.registro_execucao import excel_resultado
    e, comps = _registro()
    return load_workbook(io.BytesIO(excel_resultado(e, comps))), comps


def test_excel_tem_abas_resumo_e_comparaveis():
    livro, _ = _abrir_excel()
    assert livro.sheetnames == ["Resumo", "Comparáveis"], livro.sheetnames


def test_excel_resumo_campo_valor():
    livro, _ = _abrir_excel()
    resumo = {linha[0]: linha[1] for linha in livro["Resumo"].iter_rows(values_only=True)}
    assert resumo["Decisão"] == "Não descartar"
    assert round(resumo["Lance máximo"]) == 415763 and round(resumo["Sobra (negativo = falta)"]) == 92605
    assert resumo["Valor mínimo CAIXA"] == 323158 and resumo["Valor de liquidez (−10%)"] == 644432.4
    assert resumo["Cidade"] == "Curitiba" and resumo["Estimativa confiável"] == "Sim"
    assert resumo["Identificador da avaliação"] == "abc123"
    celula_lance = next(l[1] for l in livro["Resumo"].iter_rows() if l[0].value == "Lance máximo")
    assert "R$" in celula_lance.number_format


def test_excel_comparaveis_um_por_linha_com_link():
    livro, comps = _abrir_excel()
    aba = livro["Comparáveis"]
    linhas = list(aba.iter_rows(values_only=True))
    assert linhas[0][:3] == ("Tipo", "Entrou no cálculo", "Localização")
    corpo = linhas[1:]
    assert len(corpo) == len(comps)
    assert [l[0] for l in corpo] == ["Construção", "Construção", "Construção", "Terreno"]
    assert [l[1] for l in corpo[:3]] == ["Sim", "Sim", "Não"]   # usados antes dos descartados
    assert "Fora da zona (fallback)" in [l[2] for l in corpo]
    assert aba.cell(row=2, column=10).hyperlink is not None
    assert aba.freeze_panes == "A2"


def test_versao_codigo_do_git():
    v = versao_codigo()
    assert v == "desconhecida" or re.fullmatch(r"[0-9a-f]{40}", v), v


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    falhas = 0
    for nome, fn in testes:
        try:
            fn()
            print(f"OK    {nome}")
        except AssertionError as e:
            falhas += 1
            print(f"FALHA {nome}: {e}")
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
