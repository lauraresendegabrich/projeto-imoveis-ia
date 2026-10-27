"""
Pagina "Leiloes ativos" (app/pages/1_Leilões_ativos.py) e services/leiloes_ativos.py.
Banco simulado: nenhum teste le ou grava no Neon.

    .venv/Scripts/python.exe -m tests.test_leiloes_ativos
"""
import logging
import sys
from datetime import datetime, timedelta
from decimal import Decimal

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

import streamlit as st
from streamlit.testing.v1 import AppTest

import services.banco
from services import leiloes_ativos
from services.leilao import agora_brasilia, conta_investimento

PAGINA = "app/pages/1_Leilões_ativos.py"


def linha(**extra):
    """Linha de vw_leiloes como o banco devolve (ja com os Decimal convertidos)."""
    base = {
        "id": 1, "banco": "CAIXA", "codigo": "8555522716531", "numero_imovel": "855552271653-1",
        "link": "https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel=8555522716531",
        "modalidade": "Leilão SFI", "tipo": "apartamento", "endereco": "Avenida Jose Leite, 911", "bairro": "Caji",
        "cidade": "Lauro de Freitas", "uf": "BA", "etapa_atual": 1,
        "encerramento": agora_brasilia() + timedelta(days=3), "valor_minimo_atual": 224000.0,
        "valor_avaliacao": 224000.0, "encerrado": False, "ativo": True, "situacao": "ativo",
        "gravame": False, "gravame_texto": None, "averbacao_leiloes_negativos": "Não se aplica",
        "ultima_execucao": "abc", "avaliado_em": datetime(2026, 10, 26, 15, 0), "decisao": "Oportunidade",
        "roi": 0.7, "lance_maximo": 300000.0, "lance_limite_descarte": 340000.0, "liquidez": 450000.0,
        "etapa_avaliada": 1, "etapa_mudou": False,
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------- regras
def test_etapa_mudou_refaz_a_resposta_com_o_valor_atual():
    # Avaliado no 1o leilao (R$ 224.000); agora vale o 2o, mais caro (R$ 296.523,50).
    l = leiloes_ativos.preparar_linha(linha(etapa_atual=2, valor_minimo_atual=296523.50, etapa_mudou=True))
    esperado = conta_investimento(296523.50, 450000.0)["roi"]
    assert l["recalculado"] and abs(l["roi"] - esperado) < 1e-12 and l["etapa"] == 2
    assert l["decisao"] == "Descartar"   # 1,6% de ROI no 2o leilao


def test_mesma_etapa_da_o_mesmo_resultado_da_avaliacao():
    l = leiloes_ativos.preparar_linha(linha())
    assert not l["recalculado"] and l["decisao"] == "Oportunidade"
    assert abs(l["roi"] - conta_investimento(224000.0, 450000.0)["roi"]) < 1e-12


def test_sem_liquidez_fica_sem_estimativa_e_sem_avaliacao_fica_vazio():
    l = leiloes_ativos.preparar_linha(linha(liquidez=None, decisao="Sem estimativa"))
    assert l["decisao"] == "Sem estimativa" and l["roi"] is None and l["lance_maximo"] is None
    l = leiloes_ativos.preparar_linha(linha(ultima_execucao=None, liquidez=None, decisao=None, roi=None))
    assert l["decisao"] is None


def test_filtros():
    linhas = [leiloes_ativos.preparar_linha(l) for l in (
        linha(id=1), linha(id=2, modalidade="Venda Online", uf="SP", valor_minimo_atual=400000.0),
        linha(id=3, ultima_execucao=None, liquidez=None, decisao=None))]
    assert [l["id"] for l in leiloes_ativos.filtrar(linhas)] == [1, 2, 3]
    assert [l["id"] for l in leiloes_ativos.filtrar(linhas, decisoes=["Oportunidade"])] == [1]
    assert [l["id"] for l in leiloes_ativos.filtrar(linhas, decisoes=["Sem avaliação"])] == [3]
    assert [l["id"] for l in leiloes_ativos.filtrar(linhas, modalidades=["Venda Online"], ufs=["SP"])] == [2]


class _Coluna:
    def __init__(self, nome):
        self.name = nome


class _Banco:
    """psycopg.connect falso: guarda os comandos e devolve as linhas dadas."""

    def __init__(self, linhas=(), rowcount=1):
        self.linhas, self.rowcount, self.comandos = list(linhas), rowcount, []
        self.description = [_Coluna(c) for c in (self.linhas[0].keys() if self.linhas else ())]

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def transaction(self):
        return self

    def cursor(self):
        return self

    def execute(self, sql, parametros=None):
        self.comandos.append((sql, parametros))

    def fetchall(self):
        return [tuple(l.values()) for l in self.linhas]


def _com_banco_falso(banco, funcao):
    import psycopg
    original = psycopg.connect
    psycopg.connect = banco
    try:
        return funcao()
    finally:
        psycopg.connect = original


def test_listar_converte_decimal_e_escolhe_a_view():
    banco = _Banco([{"id": 1, "valor_minimo_atual": Decimal("224000.00"), "roi": Decimal("0.7068")}])
    linhas = _com_banco_falso(banco, lambda: leiloes_ativos.listar_leiloes("postgresql://falso"))
    assert linhas == [{"id": 1, "valor_minimo_atual": 224000.0, "roi": 0.7068}]
    assert any(sql == "SELECT * FROM vw_leiloes_ativos" for sql, _ in banco.comandos)
    banco = _Banco([{"id": 1}])
    _com_banco_falso(banco, lambda: leiloes_ativos.listar_leiloes("postgresql://falso", incluir_inativos=True))
    assert any(sql.startswith("SELECT * FROM vw_leiloes ORDER BY") for sql, _ in banco.comandos)


def test_marcar_situacao():
    banco = _Banco()
    assert _com_banco_falso(banco, lambda: leiloes_ativos.marcar_situacao("postgresql://falso", 7, "vendido"))
    assert banco.comandos == [(leiloes_ativos.SQL_SITUACAO, ("vendido", 7))]
    assert not _com_banco_falso(_Banco(rowcount=0), lambda: leiloes_ativos.marcar_situacao("x", 7, "retirado"))
    try:
        leiloes_ativos.marcar_situacao("x", 7, "arrematado")
    except ValueError:
        return
    raise AssertionError("aceitou situacao invalida")


# ---------------------------------------------------------------- pagina
def _pagina(linhas, url="postgresql://falso", erro=None):
    st.cache_data.clear()
    chamadas = []
    original_url, original_listar = services.banco.obter_database_url, leiloes_ativos.listar_leiloes
    original_marcar = leiloes_ativos.marcar_situacao

    def listar(database_url, incluir_inativos=False):
        if erro:
            raise erro
        return [l for l in linhas if incluir_inativos or l.get("ativo")]

    services.banco.obter_database_url = lambda: url
    leiloes_ativos.listar_leiloes = listar
    leiloes_ativos.marcar_situacao = lambda u, i, s: chamadas.append((i, s)) or True
    at = AppTest.from_file(PAGINA, default_timeout=60)
    at.chamadas = chamadas
    at._restaurar = lambda: (setattr(services.banco, "obter_database_url", original_url),
                             setattr(leiloes_ativos, "listar_leiloes", original_listar),
                             setattr(leiloes_ativos, "marcar_situacao", original_marcar))
    return at


def _rodar(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_pagina_lista_os_ativos_com_cronometro_e_resposta():
    at = _pagina([linha(), linha(id=2, ativo=False, situacao="vendido")])
    try:
        _rodar(at)
        assert "**CAIXA · Leilão SFI · 1º leilão** · nº 855552271653-1" in " ".join(m.value for m in at.markdown)
        assert at.get("iframe"), "cronometro"
        assert any("Oportunidade" in m.value for m in at.markdown)
        assert any(m.label == "Imóveis" and m.value == "1" for m in at.metric)
        assert any(m.label == "Encerram em até 7 dias" and m.value == "1" for m in at.metric)
        assert len(at.selectbox) == 1                       # o vendido nao aparece
        at.toggle[0].set_value(True).run()
        assert len(at.selectbox) == 2 and any("Situação: vendido" in c.value for c in at.caption)
    finally:
        at._restaurar()


def test_pagina_mostra_quando_a_resposta_foi_refeita():
    at = _pagina([linha(etapa_atual=2, valor_minimo_atual=296523.50, etapa_mudou=True)])
    try:
        _rodar(at)
        assert any("Avaliado no 1º leilão: a resposta foi refeita com o valor do 2º leilão" in c.value
                   for c in at.caption)
        assert any("Descartar" in m.value for m in at.markdown)
    finally:
        at._restaurar()


def test_salvar_situacao_grava_e_avisa():
    at = _pagina([linha(id=9)])
    try:
        _rodar(at)
        at.selectbox(key="situacao_9").select("retirado")
        at.button(key="salvar_9").click()
        _rodar(at)
        assert at.chamadas == [(9, "retirado")]
        assert any('Situação alterada para "retirado"' in s.value for s in at.success)
    finally:
        at._restaurar()


def test_compra_direta_sem_cronometro_e_gravame():
    at = _pagina([linha(modalidade="Compra Direta", etapa_atual=None, encerramento=None, gravame=True,
                        gravame_texto="Imóvel com penhora averbada.")])
    try:
        _rodar(at)
        assert not at.get("iframe")
        assert any("sem data de encerramento" in c.value for c in at.caption)
        assert any("Imóvel com penhora averbada." in e.value for e in at.error)
    finally:
        at._restaurar()


def test_sem_banco_ou_banco_fora_do_ar():
    at = _pagina([], url="")
    try:
        _rodar(at)
        assert any("Banco não configurado" in w.value for w in at.warning)
    finally:
        at._restaurar()
    at = _pagina([], erro=TimeoutError("neon dormindo"))
    try:
        _rodar(at)
        assert any("Não foi possível ler os leilões" in e.value for e in at.error)
    finally:
        at._restaurar()


def test_lista_vazia_explica_como_aparecer():
    at = _pagina([])
    try:
        _rodar(at)
        assert any("depois de avaliados com a modalidade" in i.value for i in at.info)
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
