"""
Testes da avaliacao de leilao CAIXA (services/leilao.py), com os exemplos reais do
CLAUDE.md. Sem rede.

    .venv/Scripts/python.exe -m tests.test_leilao
"""
import sys

sys.path.insert(0, ".")

from datetime import date, datetime

from services.leilao import (
    AVISO_DIREITO_PREFERENCIA, MODALIDADES_CAIXA, avaliar_imovel_leilao, esta_ativo, etapa_atual, texto_prazo,
    ROI_OPORTUNIDADE, ROI_MARGEM_APERTADA, avaliar_leilao, classificar_roi, conta_investimento, contar_status_zona,
    lance_para_roi, ler_valor_reais, linhas_laudo, texto_aviso_zona,
)


def ag5(status="ok", liquidez=None, usados=None):
    """Resultado do Agente 5 so com os campos que a regra usa."""
    return {
        "status_avaliacao": status,
        "avaliacao_confiavel": status == "ok",
        "avaliacao_planilha": {"valor_liquidez": liquidez},
        "comparaveis_usados": usados or {"construcao": [{"status_zona": "confirmado"}] * 3, "terreno": []},
    }


def test_exemplo_do_professor():
    c = conta_investimento(425000, 1100000)
    assert round(c["custos_antes_da_venda"], 2) == 565250.00
    assert round(c["corretagem"], 2) == 55000.00
    assert round(c["ir"], 2) == 80212.50
    assert round(c["custos_totais"], 2) == 700462.50
    assert round(c["resultado"], 2) == 399537.50
    assert round(c["roi"] * 100, 2) == 70.68


def test_lance_para_roi_desfaz_a_conta():
    roi = conta_investimento(425000, 1100000)["roi"]
    assert round(lance_para_roi(1100000, roi), 2) == 425000.00
    for alvo in (ROI_MARGEM_APERTADA, ROI_OPORTUNIDADE):
        assert abs(conta_investimento(lance_para_roi(500000, alvo), 500000)["roi"] - alvo) < 1e-12


def test_faixas_do_roi_com_os_limites():
    assert classificar_roi(0.1499) == "Descartar"
    assert classificar_roi(0.15) == "Margem apertada"
    assert classificar_roi(0.2999) == "Margem apertada"
    assert classificar_roi(0.30) == "Oportunidade"
    assert classificar_roi(-0.2) == "Descartar"
    # Lance exatamente no limite (com arredondamento de ponto flutuante) fica na faixa de cima.
    assert avaliar_leilao(ag5(liquidez=500000), lance_para_roi(500000, 0.30))["decisao"] == "Oportunidade"
    assert avaliar_leilao(ag5(liquidez=500000), lance_para_roi(500000, 0.15))["decisao"] == "Margem apertada"


def test_ir_nao_fica_negativo_no_prejuizo():
    c = conta_investimento(500000, 300000)
    assert c["ir"] == 0 and c["resultado"] < 0 and c["roi"] < 0


def test_casa_curitiba_em_analise():
    r = avaliar_leilao(ag5(liquidez=644432), 323158)
    assert r["decisao"] == "Oportunidade", r
    assert round(r["roi"], 4) == 0.3495, r["roi"]
    assert round(r["lance_maximo"]) == 337068, r["lance_maximo"]
    assert round(r["lance_limite_descarte"]) == 387628, r["lance_limite_descarte"]
    assert round(r["sobra"]) == 13910, r["sobra"]


def test_pre_analise():
    r = avaliar_leilao(ag5(liquidez=644432), 360000)
    assert r["decisao"] == "Margem apertada", r
    assert 0.15 <= r["roi"] < 0.30 and r["sobra"] < 0


def test_apto_sao_paulo_descartar():
    r = avaliar_leilao(ag5(liquidez=314986), 217368)
    assert r["decisao"] == "Descartar", r
    assert round(r["roi"], 4) == 0.0216, r["roi"]
    assert round(r["lance_maximo"]) == 164752, r["lance_maximo"]
    assert round(r["sobra"]) == -52616, r["sobra"]


def test_casa_rio_verde_sem_estimativa():
    r = avaliar_leilao(ag5(status="amostra_insuficiente", liquidez=500000), 391948)
    assert r["decisao"] == "Sem estimativa", r
    assert r["lance_maximo"] is None and r["sobra"] is None and r["roi"] is None
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


def test_sobra_zero_fica_em_analise():
    r = avaliar_leilao(ag5(liquidez=500000), lance_para_roi(500000, ROI_OPORTUNIDADE))
    assert abs(r["sobra"]) < 1e-6 and r["decisao"] == "Oportunidade", r


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
    assert r["decisao"] == "Oportunidade"   # o aviso nao muda a decisao


def _brl(v):
    return f"R$ {v:,.0f}".replace(",", ".")


def test_laudo_curitiba():
    linhas = linhas_laudo(avaliar_leilao(ag5(liquidez=644432), 323158, 410000), _brl)
    assert linhas[0] == "Decisão: Oportunidade", linhas
    assert "ROI pagando o valor mínimo: 34,95%" in linhas
    assert "Valor mínimo CAIXA: R$ 323.158" in linhas
    assert "Lance até R$ 337.068 para continuar Oportunidade" in linhas
    assert "Acima de R$ 387.628, descartar" in linhas
    assert "  Custos antes da venda (arrematação + 33%): R$ 429.800" in linhas
    assert "Valor de avaliação CAIXA (informativo): R$ 410.000" in linhas


def test_laudo_sao_paulo_descartar():
    linhas = linhas_laudo(avaliar_leilao(ag5(liquidez=314986), 217368), _brl)
    assert linhas[0] == "Decisão: Descartar" and "ROI pagando o valor mínimo: 2,16%" in linhas, linhas


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



def test_laudo_avisa_endereco_nao_localizado():
    leilao = avaliar_leilao(ag5(liquidez=644432), 323158)
    leilao["alvo_sem_localizacao"] = True
    linhas = linhas_laudo(leilao, _brl)
    assert linhas[0] == "Decisão: Oportunidade" and linhas[1].startswith("Atenção: endereço não localizado"), linhas
    leilao["alvo_sem_localizacao"] = False
    assert not any("não localizado" in l for l in linhas_laudo(leilao, _brl))

def test_ler_data_br():
    from datetime import date
    from services.leilao import ler_data_br
    assert ler_data_br("25/11/2026") == date(2026, 11, 25)
    assert ler_data_br(" 25/11/26 ") == date(2026, 11, 25)
    assert ler_data_br("") is None and ler_data_br(None) is None
    for texto in ("31/02/2026", "2026-11-25", "amanhã"):
        try:
            ler_data_br(texto)
        except ValueError:
            continue
        raise AssertionError(f"aceitou data invalida: {texto}")



# ---------------------------------------------------------------- aviso da zona
def _ag5_usados(construcao, terreno=()):
    return {"comparaveis_usados": {"construcao": [{"status_zona": s} for s in construcao],
                                   "terreno": [{"status_zona": s} for s in terreno]}}


def test_aviso_so_confirmados_nao_tem_aviso():
    c = contar_status_zona(_ag5_usados(["confirmado"] * 5, ["confirmado"] * 5))
    assert c == {"confirmado": 10, "fallback": 0, "sem_validacao": 0, "total": 10}, c
    assert texto_aviso_zona(c, "rua+bairro") is None


def test_aviso_com_fallback_tem_os_numeros():
    c = contar_status_zona(_ag5_usados(["confirmado"] * 2 + ["fallback"] * 3, ["confirmado"] * 5))
    assert c["confirmado"] == 7 and c["fallback"] == 3 and c["total"] == 10, c
    texto = texto_aviso_zona(c, "rua+bairro")
    assert texto.startswith("Só 7 dos 10 comparáveis foram confirmados perto do imóvel (dentro da zona homogênea).")
    assert "Os outros 3 não têm localização exata no anúncio" in texto
    assert "Eles contam para o mínimo de 5. Confira esses anúncios antes de decidir." in texto


def test_aviso_com_sem_validacao():
    c = contar_status_zona(_ag5_usados(["sem_validacao"] * 6))
    texto = texto_aviso_zona(c, "rua+bairro")
    assert texto == ("Nenhum comparável foi confirmado perto do imóvel. O valor usa 6 imóveis parecidos "
                     "encontrados na busca, sem verificar a distância. Confira esses anúncios antes de decidir."), texto


def test_aviso_escopo_cidade():
    so_cidade = texto_aviso_zona(contar_status_zona(_ag5_usados(["confirmado"] * 5)), "cidade")
    assert so_cidade == ("Nenhum anúncio foi encontrado na rua ou no bairro do imóvel; o valor usa imóveis "
                         "parecidos de outros bairros da cidade."), so_cidade
    junto = texto_aviso_zona(contar_status_zona(_ag5_usados(["sem_validacao"] * 6)), "cidade")
    assert junto.startswith("Nenhum comparável foi confirmado") and junto.endswith("outros bairros da cidade.")


def test_laudo_usa_o_texto_novo_do_aviso():
    leilao = avaliar_leilao(ag5(liquidez=644432), 323158)
    leilao["aviso_zona"] = texto_aviso_zona(contar_status_zona(_ag5_usados(["confirmado"] * 2 + ["fallback"] * 3)))
    linhas = linhas_laudo(leilao, _brl)
    assert "Atenção: Só 2 dos 5 comparáveis foram confirmados perto do imóvel" in " | ".join(linhas), linhas
    assert not any("fora da região exata" in l for l in linhas)

def test_faixas_unicas():
    assert (ROI_MARGEM_APERTADA, ROI_OPORTUNIDADE) == (0.15, 0.30)


# ---------------------------------------------------------------- modalidades e etapa
# Exemplo real do site da CAIXA: no 2o leilao o minimo e a divida, e pode ser MAIOR.
SFI = {"modalidade": "Leilão SFI",
       "data_1_leilao": datetime(2026, 11, 10, 10, 0), "valor_minimo_1": 224000.00,
       "data_2_leilao": datetime(2026, 11, 24, 10, 0), "valor_minimo_2": 296523.50}
LIQ = 450000


def test_modalidades_com_os_nomes_do_site():
    assert MODALIDADES_CAIXA == ["Leilão SFI", "Licitação Aberta", "Venda Online", "Compra Direta"]


def test_sfi_antes_do_1o_leilao():
    r = avaliar_imovel_leilao(ag5(liquidez=LIQ), SFI, agora=datetime(2026, 11, 1, 9, 0))
    assert r["etapa"] == 1 and r["valor_minimo"] == 224000.00 and not r["encerrado"] and r["ativo"]
    assert r["encerramento"] == SFI["data_1_leilao"]
    assert r["prazo"] == "Encerra em 9 dias e 1 h (10/11/2026 10:00)"
    assert r["outra_etapa"] == 2 and r["valor_minimo_outra_etapa"] == 296523.50
    # O 2o e mais caro: o ROI da outra etapa e MENOR que o da atual.
    assert r["roi_outra_etapa"] < r["roi"]
    assert r["decisao"] == "Oportunidade" and r["aviso_direito_preferencia"] == AVISO_DIREITO_PREFERENCIA


def test_sfi_na_hora_exata_do_1o_ainda_e_1o():
    assert etapa_atual(SFI, datetime(2026, 11, 10, 10, 0))["etapa"] == 1


def test_sfi_entre_o_1o_e_o_2o_usa_o_valor_maior_do_2o():
    r = avaliar_imovel_leilao(ag5(liquidez=LIQ), SFI, agora=datetime(2026, 11, 10, 10, 1))
    assert r["etapa"] == 2 and r["valor_minimo"] == 296523.50 and not r["encerrado"] and r["ativo"]
    assert r["outra_etapa"] == 1 and r["valor_minimo_outra_etapa"] == 224000.00
    assert r["roi"] < r["roi_outra_etapa"]
    esperado = conta_investimento(296523.50, LIQ)["roi"]
    assert abs(r["roi"] - esperado) < 1e-12 and r["decisao"] == classificar_roi(esperado)
    assert r["sobra"] == r["lance_maximo"] - 296523.50


def test_sfi_depois_do_2o_esta_encerrado():
    r = avaliar_imovel_leilao(ag5(liquidez=LIQ), SFI, agora=datetime(2026, 11, 24, 10, 1))
    assert r["etapa"] == 2 and r["encerrado"] and not r["ativo"]
    assert r["valor_minimo"] == 296523.50
    assert r["prazo"] == "Encerrado em 24/11/2026 10:00"


def test_sfi_sem_datas_usa_o_1o():
    sem_datas = {**SFI, "data_1_leilao": None, "data_2_leilao": None}
    e = etapa_atual(sem_datas, datetime(2026, 11, 1))
    assert e["etapa"] == 1 and e["valor_minimo"] == 224000.00 and e["encerramento"] is None and not e["encerrado"]
    so_o_2o = {**sem_datas, "valor_minimo_1": None}
    assert etapa_atual(so_o_2o, datetime(2026, 11, 1))["valor_minimo"] == 296523.50


def test_data_sem_hora_vale_ate_o_fim_do_dia():
    venda = {"modalidade": "Venda Online", "valor_minimo": 200000, "data_encerramento": date(2026, 11, 5)}
    assert not etapa_atual(venda, datetime(2026, 11, 5, 23, 0))["encerrado"]
    assert etapa_atual(venda, datetime(2026, 11, 6, 0, 0))["encerrado"]


def test_licitacao_aberta_e_venda_online():
    for modalidade in ("Licitação Aberta", "Venda Online"):
        dados = {"modalidade": modalidade, "valor_minimo": 200000, "data_encerramento": datetime(2026, 11, 5, 18, 0)}
        r = avaliar_imovel_leilao(ag5(liquidez=LIQ), dados, agora=datetime(2026, 11, 5, 6, 30))
        assert r["etapa"] is None and r["valor_minimo"] == 200000 and r["ativo"]
        assert r["prazo"] == "Encerra em 11 h (05/11/2026 18:00)"
        assert r["outra_etapa"] is None and r["roi_outra_etapa"] is None and r["aviso_direito_preferencia"] is None
    assert avaliar_imovel_leilao(ag5(liquidez=LIQ), {**dados, "modalidade": "Licitação Aberta"},
                                 agora=datetime(2026, 11, 1))["comissao_leiloeiro"] == 0.05
    assert avaliar_imovel_leilao(ag5(liquidez=LIQ), dados, agora=datetime(2026, 11, 1))["comissao_leiloeiro"] is None


def test_compra_direta_sem_data_depende_so_da_situacao():
    dados = {"modalidade": "Compra Direta", "valor_minimo": 200000}
    r = avaliar_imovel_leilao(ag5(liquidez=LIQ), dados, agora=datetime(2030, 1, 1))
    assert r["encerramento"] is None and r["prazo"] is None and not r["encerrado"] and r["ativo"]
    assert r["comissao_leiloeiro"] is None
    vendido = avaliar_imovel_leilao(ag5(liquidez=LIQ), {**dados, "situacao": "vendido"}, agora=datetime(2030, 1, 1))
    assert not vendido["ativo"] and vendido["situacao"] == "vendido"


def test_ativo_pela_situacao_e_pelo_prazo():
    assert esta_ativo(None, False) and esta_ativo("ativo", False)
    assert not esta_ativo("ativo", True) and not esta_ativo("retirado", False)


def test_texto_prazo_singular_e_menos_de_uma_hora():
    fim = datetime(2026, 11, 5, 18, 0)
    assert texto_prazo(fim, datetime(2026, 11, 4, 15, 0)) == "Encerra em 1 dia e 3 h (05/11/2026 18:00)"
    assert texto_prazo(fim, datetime(2026, 11, 5, 17, 30)) == "Encerra em menos de 1 h (05/11/2026 18:00)"
    assert texto_prazo(None, fim) is None


def test_sem_estimativa_mantem_etapa_e_prazo():
    r = avaliar_imovel_leilao(ag5(status="amostra_insuficiente", liquidez=LIQ), SFI, agora=datetime(2026, 11, 1))
    assert r["decisao"] == "Sem estimativa" and r["etapa"] == 1 and r["roi"] is None and r["roi_outra_etapa"] is None


def test_sem_valor_minimo_da_etapa_nao_avalia():
    so_1o = {**SFI, "valor_minimo_2": None}
    assert avaliar_imovel_leilao(ag5(liquidez=LIQ), so_1o, agora=datetime(2026, 11, 20)) is None


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
