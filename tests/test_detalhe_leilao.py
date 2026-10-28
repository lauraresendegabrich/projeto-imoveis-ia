"""
"Ver avaliacao completa" (pagina "Leiloes ativos"): o resultado gravado em
execucoes.resultado_completo (services/detalhe_leilao.py) remonta a mesma tela de
quando a avaliacao acaba de rodar. Banco simulado: nenhum teste le ou grava no Neon.

    .venv/Scripts/python.exe -m tests.test_detalhe_leilao
"""
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

import streamlit as st
from streamlit.testing.v1 import AppTest

import services.banco
from services import detalhe_leilao, leiloes_ativos
from services.leilao import agora_brasilia
from tests.test_leiloes_ativos import PAGINA, linha
from tests.test_tela_resultado import resultado_sem_valor

AG5_OK = {"status_avaliacao": "ok", "avaliacao_confiavel": True,
          "avaliacao_planilha": {"valor_medio_imovel": 500000, "valor_liquidez": 450000},
          "liquidez_experimental": {"tempo_estimado": "90 a 150 dias"},
          "comparaveis_usados": {"construcao": [], "terreno": []}}
TELA = {"rua": "Avenida Jose Leite", "numero": "911", "bairro": "Caji", "cidade": "Lauro de Freitas",
        "estado": "BA", "tipo": "Apartamento", "quartos": 2, "banheiros": 1, "vagas": 1}


def imovel(**extra):
    """Linha de imoveis_leilao (Leilao SFI; 1o leilao ja passou, 2o daqui a 3 dias)."""
    agora = agora_brasilia()
    base = {"id": 1, "banco": "CAIXA", "codigo": "8555522716531", "numero_imovel": "855552271653-1",
            "modalidade": "Leilão SFI", "data_1_leilao": agora - timedelta(days=1), "valor_minimo_1": 224000.0,
            "data_2_leilao": agora + timedelta(days=3), "valor_minimo_2": 296523.5, "valor_minimo": None,
            "data_encerramento": None, "valor_avaliacao": 224000.0, "situacao": "ativo", "gravame": False,
            "edital": "0052/0226 - CPA/RE", "numero_item": "25", "leiloeiro": None, "matricula": None,
            "averbacao_leiloes_negativos": None, "gravame_texto": None, "formas_pagamento": None}
    base.update(extra)
    return base


def resultado_ok():
    r = resultado_sem_valor()
    r["preco_estimado"] = AG5_OK
    r["leilao"] = {"decisao": "Oportunidade", "aviso_zona": "Aviso da zona gravado.", "alvo_sem_localizacao": False,
                   "encerramento": datetime(2026, 11, 30, 10)}
    r["imovel_alvo"] = {"area": 54.68, "tipo": "apartment", "price": None}
    return r


def execucao(**extra):
    """Linha de execucoes como o banco devolve (Decimal ja em float; data_hora com fuso)."""
    base = {"id_execucao": "abc", "data_hora": datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc),
            "endereco": "Avenida Jose Leite, 911", "bairro": "Caji", "cidade": "Lauro de Freitas", "uf": "BA",
            "status_agente5": "ok", "valor_mercado": 500000.0, "liquidez": 450000.0, "tempo_venda": "90 a 150 dias",
            "lance_maximo": 300000.0, "decisao": "Oportunidade", "etapa_avaliada": 1, "alertas": [],
            "verificacoes": None, "resultado_completo": None}
    base.update(extra)
    return base


def gravado(resultado=None, tela=TELA):
    """resultado_completo depois de ida e volta pelo JSONB (como o banco devolve)."""
    completo = detalhe_leilao.resultado_para_gravar(resultado or resultado_ok(), tela)
    return json.loads(json.dumps(completo))


COMPARAVEIS = [{"id": 1, "id_execucao": "abc", "tipo": "construcao", "preco": 510000.0, "area": 101.0,
                "valor_m2": 5049.5, "endereco": "Rua 1", "bairro": "Centro", "portal": "VivaReal",
                "link": "https://x/1", "status_zona": "confirmado", "entrou_no_calculo": True}]


# ---------------------------------------------------------------- gravacao
def test_para_json_aceita_o_que_o_jsonb_nao_aceita():
    import numpy as np
    valor = {("a", 1): 1, "data": datetime(2026, 10, 28, 9, 30), "preco": Decimal("1.5"), "nan": float("nan"),
             "inf": float("inf"), "tupla": (1, 2), "texto": "a\x00b", "np": np.int64(7), "npf": np.float64(2.5),
             "fotos_urls": ["x"], "images": ["y"], "descricao": "longa", "lista": [{"description": "z", "url": "u"}]}
    saida = detalhe_leilao.para_json(valor)
    json.dumps(saida, allow_nan=False)   # sem NaN/infinito
    assert saida["('a', 1)"] == 1 and saida["data"] == "2026-10-28T09:30:00" and saida["preco"] == 1.5
    assert saida["nan"] is None and saida["inf"] is None and saida["tupla"] == [1, 2] and saida["texto"] == "ab"
    assert saida["np"] == 7 and saida["npf"] == 2.5
    assert not {"fotos_urls", "images", "descricao"} & set(saida) and saida["lista"] == [{"url": "u"}]


def test_resultado_para_gravar_tira_o_registro_e_guarda_a_tela():
    r = resultado_ok()
    r["registro"] = {"execucao": {"muito": "grande"}, "comparaveis": []}
    completo = detalhe_leilao.resultado_para_gravar(r, TELA)
    assert completo["versao"] == detalhe_leilao.VERSAO_RESULTADO and completo["tela"] == TELA
    assert "registro" not in completo["resultado"] and completo["resultado"]["preco_estimado"] == AG5_OK
    assert "registro" in r   # o resultado da sessao nao muda


def test_resultado_grande_demais_ou_com_erro_nao_e_gravado():
    original = detalhe_leilao.TAMANHO_MAX_RESULTADO
    detalhe_leilao.TAMANHO_MAX_RESULTADO = 100
    try:
        assert detalhe_leilao.resultado_para_gravar(resultado_ok(), TELA) is None
    finally:
        detalhe_leilao.TAMANHO_MAX_RESULTADO = original
    ciclo = {}
    ciclo["eu"] = ciclo
    assert detalhe_leilao.resultado_para_gravar({"x": ciclo}, TELA) is None   # RecursionError: nao quebra


def test_registro_tem_a_coluna_e_o_banco_grava_como_json():
    from services.banco import COLUNAS_EXECUCOES, COLUNAS_JSON
    assert "resultado_completo" in COLUNAS_EXECUCOES and "resultado_completo" in COLUNAS_JSON


# ---------------------------------------------------------------- leitura
def test_detalhe_refaz_o_cartao_na_etapa_atual():
    # Avaliado no 1o leilao; o 1o ja passou: o cartao vale para o 2o (R$ 296.523,50).
    dados = {"execucao": execucao(resultado_completo=gravado()), "imovel": imovel(), "comparaveis": COMPARAVEIS}
    d = detalhe_leilao.montar_detalhe(dados)
    assert d["leilao"]["etapa"] == 2 and d["leilao"]["valor_minimo"] == 296523.5
    assert d["resultado"]["leilao"] is d["leilao"] and d["leilao"]["aviso_zona"] == "Aviso da zona gravado."
    assert d["resultado"]["registro"]["comparaveis"] == COMPARAVEIS and d["tela"] == TELA
    assert d["execucao"]["_imovel_leilao"]["codigo"] == "8555522716531"   # para o Excel


def test_detalhe_antigo_usa_as_colunas_da_execucao():
    d = detalhe_leilao.montar_detalhe({"execucao": execucao(), "imovel": imovel(), "comparaveis": []})
    assert d["resultado"] is None and d["tela"] is None
    assert d["leilao"]["etapa"] == 2 and d["leilao"]["liquidez"] == 450000.0 and d["leilao"]["roi"] is not None
    # "Sem estimativa" gravado (sem lance maximo): continua sem estimativa.
    d = detalhe_leilao.montar_detalhe({"execucao": execucao(lance_maximo=None, status_agente5="amostra_insuficiente"),
                                       "imovel": imovel(), "comparaveis": []})
    assert d["leilao"]["decisao"] == "Sem estimativa" and d["leilao"]["lance_maximo"] is None
    assert detalhe_leilao.montar_detalhe({"execucao": None, "imovel": None, "comparaveis": []}) is None


# ---------------------------------------------------------------- pagina
def _pagina(dados, linhas=None):
    st.cache_data.clear()
    original = (services.banco.obter_database_url, leiloes_ativos.listar_leiloes, detalhe_leilao.carregar_detalhe)
    pedidos = []
    services.banco.obter_database_url = lambda: "postgresql://falso"
    leiloes_ativos.listar_leiloes = lambda url, incluir_inativos=False: linhas or [linha()]
    detalhe_leilao.carregar_detalhe = lambda url, id_execucao, id_imovel: pedidos.append((id_execucao, id_imovel)) or dados
    at = AppTest.from_file(PAGINA, default_timeout=60)
    at.pedidos = pedidos
    at._restaurar = lambda: (setattr(services.banco, "obter_database_url", original[0]),
                             setattr(leiloes_ativos, "listar_leiloes", original[1]),
                             setattr(detalhe_leilao, "carregar_detalhe", original[2]))
    return at


def _abrir(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.button(key="detalhe_1").click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_ver_avaliacao_completa_abre_a_tela_do_resultado_e_volta():
    at = _pagina({"execucao": execucao(resultado_completo=gravado()), "imovel": imovel(), "comparaveis": COMPARAVEIS})
    try:
        _abrir(at)
        assert at.pedidos == [("abc", 1)]
        subtitulos = [s.value for s in at.subheader]
        assert "Avenida Jose Leite, 911, Caji · Lauro de Freitas/BA" in subtitulos
        assert "📊 Resultado da Avaliação" in subtitulos and "📖 Como chegamos neste valor" in subtitulos
        assert any(c.value.startswith("Avaliado em 26/10/2026 15:00") for c in at.caption)   # Brasilia
        assert "**CAIXA · Leilão SFI · 2º leilão**" in [m.value for m in at.markdown]          # etapa atual
        rotulos = [e.label for e in at.expander]
        for agente in ("🔍 Agente Coletor de Dados", "📊 Agente Identificador de Comparáveis",
                       "💰 Agente Estimador de Preço"):
            assert agente in rotulos, rotulos
        assert any("na região do imóvel (Caji, Lauro de Freitas/BA)" in m.value for m in at.markdown)  # campos da tela
        assert not [b for b in at.button if b.label == "Salvar"]                               # a lista sumiu
        next(b for b in at.button if b.label == "← Voltar aos leilões").click().run()
        assert not at.exception and at.button(key="detalhe_1") and len(at.selectbox) == 1
    finally:
        at._restaurar()


def test_avaliacao_antiga_mostra_o_que_foi_gravado():
    at = _pagina({"execucao": execucao(), "imovel": imovel(), "comparaveis": COMPARAVEIS})
    try:
        _abrir(at)
        assert any("feita antes de o sistema guardar a tela completa" in i.value for i in at.info)
        assert "📊 Resultado da Avaliação" not in [s.value for s in at.subheader]
        assert any(m.label == "⚡ Valor de Liquidez (-10%)" and m.value == "R\\$ 450.000" for m in at.metric)
        assert any("[ver](https://x/1)" in m.value for m in at.markdown)
        assert "**CAIXA · Leilão SFI · 2º leilão**" in [m.value for m in at.markdown]
    finally:
        at._restaurar()


def test_sem_avaliacao_nao_tem_botao_e_banco_fora_do_ar_avisa():
    at = _pagina({}, linhas=[linha(ultima_execucao=None)])
    try:
        at.run()
        assert not at.exception and not [b for b in at.button if b.label == "🔎 Ver avaliação completa"]
    finally:
        at._restaurar()

    def fora_do_ar(*_):
        raise TimeoutError("neon dormindo")
    at = _pagina({})
    detalhe_leilao.carregar_detalhe = fora_do_ar
    try:
        _abrir(at)
        assert any("Não foi possível ler a avaliação" in e.value for e in at.error)
    finally:
        at._restaurar()


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
