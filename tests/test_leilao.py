"""
Testes da avaliacao de leilao CAIXA (services/leilao.py), com os exemplos reais do
CLAUDE.md. Sem rede.

    .venv/Scripts/python.exe -m tests.test_leilao
"""
import sys

sys.path.insert(0, ".")

from services.leilao import FATOR_LUCRO_LEILAO, avaliar_leilao, ler_valor_reais, linhas_laudo


def ag5(status="ok", liquidez=None, usados=None):
    """Resultado do Agente 5 so com os campos que a regra usa."""
    return {
        "status_avaliacao": status,
        "avaliacao_confiavel": status == "ok",
        "avaliacao_planilha": {"valor_liquidez": liquidez},
        "comparaveis_usados": usados or {"construcao": [{"status_zona": "confirmado"}] * 3, "terreno": []},
    }


def test_casa_curitiba_nao_descartar():
    r = avaliar_leilao(ag5(liquidez=644432), 323158)
    assert r["decisao"] == "Não descartar", r
    assert round(r["lance_maximo"]) == 415763, r["lance_maximo"]
    assert round(r["sobra"]) == 92605, r["sobra"]


def test_apto_sao_paulo_descartar():
    r = avaliar_leilao(ag5(liquidez=314986), 217368)
    assert r["decisao"] == "Descartar", r
    assert round(r["lance_maximo"]) == 203217, r["lance_maximo"]
    assert round(r["sobra"]) == -14151, r["sobra"]


def test_casa_rio_verde_sem_estimativa():
    r = avaliar_leilao(ag5(status="amostra_insuficiente", liquidez=500000), 391948)
    assert r["decisao"] == "Sem estimativa", r
    assert r["lance_maximo"] is None and r["sobra"] is None
    assert r["status_agente5"] == "amostra_insuficiente"


def test_todos_os_status_nao_ok_dao_sem_estimativa():
    for status in ("sem_amostra", "valor_nao_estimado", "amostra_insuficiente"):
        r = avaliar_leilao(ag5(status=status, liquidez=500000), 100000)
        assert r["decisao"] == "Sem estimativa", (status, r)


def test_agente5_sem_resultado_da_sem_estimativa():
    for vazio in (None, {}):
        r = avaliar_leilao(vazio, 100000)
        assert r["decisao"] == "Sem estimativa" and r["status_agente5"] == "sem_resultado", r


def test_sem_valor_minimo_nao_ha_bloco():
    for vm in (None, 0, "", "abc"):
        assert avaliar_leilao(ag5(liquidez=644432), vm) is None, vm


def test_sobra_zero_nao_descarta():
    r = avaliar_leilao(ag5(liquidez=155000), 100000)
    assert abs(r["sobra"]) < 1e-6 and r["decisao"] == "Não descartar", r


def test_valor_avaliacao_e_so_informativo():
    sem = avaliar_leilao(ag5(liquidez=644432), 323158)
    com = avaliar_leilao(ag5(liquidez=644432), 323158, valor_avaliacao=900000)
    assert com["valor_avaliacao"] == 900000
    assert (com["lance_maximo"], com["sobra"], com["decisao"]) == (sem["lance_maximo"], sem["sobra"], sem["decisao"])


def test_conta_comparaveis_fora_da_regiao():
    usados = {
        "construcao": [{"status_zona": "confirmado"}, {"status_zona": "fallback"}, {"status_zona": "sem_validacao"}],
        "terreno": [{"status_zona": "fallback"}],
    }
    r = avaliar_leilao(ag5(liquidez=644432, usados=usados), 323158)
    assert r["comparaveis_fora_da_regiao"] == 3, r
    assert r["decisao"] == "Não descartar"   # o aviso nao muda a decisao


def _brl(v):
    return f"R$ {v:,.0f}".replace(",", ".")


def test_laudo_curitiba():
    linhas = linhas_laudo(avaliar_leilao(ag5(liquidez=644432), 323158, 410000), _brl)
    assert linhas[0] == "Decisão: Não descartar", linhas
    assert "Lance máximo: R$ 415.763" in linhas
    assert "Valor mínimo CAIXA: R$ 323.158" in linhas
    assert "Sobra: R$ 92.605" in linhas
    assert "Valor de avaliação CAIXA (informativo): R$ 410.000" in linhas


def test_laudo_sao_paulo_mostra_falta():
    linhas = linhas_laudo(avaliar_leilao(ag5(liquidez=314986), 217368), _brl)
    assert "Falta: R$ 14.151" in linhas, linhas


def test_laudo_sem_estimativa_nao_tem_lance():
    linhas = linhas_laudo(avaliar_leilao(ag5(status="amostra_insuficiente"), 391948), _brl)
    assert linhas == ["Decisão: Sem estimativa", "Valor mínimo CAIXA: R$ 391.948"], linhas
    assert linhas_laudo(None, _brl) == []


def test_ler_valor_reais_formatos_aceitos():
    casos = {
        "323158": 323158.0, "323.158": 323158.0, "323.158,50": 323158.5, "323158,50": 323158.5,
        "R$ 323.158,50": 323158.5, "r$323.158": 323158.0, "323158.50": 323158.5,
        "1.250.000": 1250000.0, "1.250.000,00": 1250000.0, " 480000 ": 480000.0, "480000,5": 480000.5,
    }
    for texto, esperado in casos.items():
        assert ler_valor_reais(texto) == esperado, (texto, ler_valor_reais(texto))


def test_ler_valor_reais_vazio_e_zero():
    for texto in ("", "   ", None, "0", "0,00"):
        assert ler_valor_reais(texto) is None, texto


def test_ler_valor_reais_invalidos():
    for texto in ("abc", "32.15.8", "323,158,50", "12,345", "-5000"):
        try:
            ler_valor_reais(texto)
        except ValueError:
            continue
        raise AssertionError(f"deveria recusar {texto!r}")


def test_fator_unico():
    assert FATOR_LUCRO_LEILAO == 1.55


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
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
