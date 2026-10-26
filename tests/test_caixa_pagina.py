"""
Leitura da pagina do imovel na CAIXA (services/caixa_pagina.py), com paginas reais
salvas das 4 modalidades em tests/paginas_caixa/. Sem rede.

    .venv/Scripts/python.exe -m tests.test_caixa_pagina
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

from services.caixa_pagina import ler_pagina_caixa, texto_da_pagina

PASTA = Path(__file__).parent / "paginas_caixa"


def pagina(nome):
    return (PASTA / f"{nome}.html").read_text(encoding="utf-8")


def ler(nome):
    r = ler_pagina_caixa(pagina(nome))
    assert r["ok"], r["erro"]
    return r


def test_leilao_sfi():
    r = ler("leilao_sfi")
    c = r["campos"]
    assert c["modalidade"] == "Leilão SFI"
    # O 2o leilao e MAIS CARO que o 1o (no 2o o minimo e a divida).
    assert c["valor_minimo_1"] == 224000.00 and c["valor_minimo_2"] == 296523.50
    assert c["valor_minimo"] is None and c["valor_avaliacao"] == 224000.00
    assert c["data_1_leilao"] == datetime(2026, 11, 30, 10, 0)
    assert c["data_2_leilao"] == datetime(2026, 12, 4, 10, 0)
    assert c["edital"] == "0052/0226 - CPA/RE" and c["numero_item"] == "25"
    assert c["leiloeiro"] == "JONAS GABRIEL ANTUNES MOREIRA"
    assert c["numero_imovel"] == "855552271653-1" and c["matricula"] == "32406"
    assert c["averbacao_leiloes_negativos"] == "Não se aplica"
    assert (c["tipo"], c["quartos"], c["vagas"], c["area_privativa"]) == ("Apartamento", 2, 1, 54.68)
    assert (c["rua"], c["numero"], c["complemento"]) == ("AVENIDA JOSE LEITE", "911", "APTO. 002 BL 03 GAR 22")
    assert (c["bairro"], c["cep"], c["cidade"], c["uf"]) == ("CAJI", "42700-000", "LAURO DE FREITAS", "BA")
    assert c["formas_pagamento"] == ["Recursos próprios (à vista)", "FGTS"]
    assert c["regras_despesas"] == ("Condomínio: Sob responsabilidade do comprador.\n"
                                    "Tributos: Sob responsabilidade do comprador.")
    assert c["link"].endswith("hdnimovel=8555522716531")
    assert r["nao_encontrados"] == ["Área total", "Área do terreno"]


def test_licitacao_aberta():
    r = ler("licitacao_aberta")
    c = r["campos"]
    assert c["modalidade"] == "Licitação Aberta"
    assert c["valor_minimo"] == 155504.69 and c["valor_avaliacao"] == 244000.00
    assert c["data_encerramento"] == datetime(2026, 11, 4, 10, 0)
    assert c["data_1_leilao"] is None and c["valor_minimo_1"] is None
    assert c["edital"] == "0036/0326 - CPVE/RE" and c["numero_item"] == "15"
    assert c["leiloeiro"] == "RICARDO LUCAS GRANADO DA SILVA"
    assert c["averbacao_leiloes_negativos"] == "Em tratamento"
    assert (c["area_total"], c["area_privativa"], c["vagas"]) == (83.75, 45.30, 2)
    assert (c["rua"], c["numero"], c["bairro"]) == ("RUA WALDIR PIRES", "643", "CENTRO")
    assert r["nao_encontrados"] == ["Área do terreno"]


def test_venda_online_encerrada():
    r = ler("venda_online")
    c = r["campos"]
    assert c["modalidade"] == "Venda Online"
    assert c["valor_minimo"] == 656394.35 and c["valor_avaliacao"] == 1029938.21
    assert c["data_encerramento"] == datetime(2026, 10, 26, 18, 0)
    assert (c["tipo"], c["quartos"]) == ("Casa", 3)
    assert (c["area_total"], c["area_privativa"], c["area_terreno"]) == (435.20, 355.93, 435.20)
    assert c["rua"] == "RUA 15 DE JANEIRO (ANTIGA RUA CORONEL MESSIAS)" and c["numero"] == "890"
    assert c["formas_pagamento"] == ["Recursos próprios (à vista)", "FGTS", "Financiamento"]
    assert c["edital"] is None and c["leiloeiro"] is None
    assert r["nao_encontrados"] == ["Garagem"]


def test_venda_online_em_andamento_pega_a_data_do_cronometro():
    # Antes de encerrar, a data so esta no script do cronometro da pagina salva.
    html = pagina("venda_online").replace("Venda online encerrada em 26/10/2026 18:00:00.", "")
    assert ler_pagina_caixa(html)["campos"]["data_encerramento"] == datetime(2026, 10, 26, 18, 0)


def test_compra_direta_sem_data_e_tipo_nao_avaliado():
    r = ler("compra_direta")
    c = r["campos"]
    assert c["modalidade"] == "Compra Direta"
    assert c["valor_minimo"] == 5074300.00 and c["valor_avaliacao"] == 9226000.00
    assert c["data_encerramento"] is None and c["data_1_leilao"] is None
    assert c["tipo_caixa"] == "Gleba" and c["tipo"] is None
    assert r["avisos"] == ["Tipo de imóvel na CAIXA: Gleba. O sistema só avalia casa e apartamento."]
    # Sem "N." no endereco: numero nao e inventado.
    assert (c["rua"], c["numero"], c["bairro"], c["uf"]) == ("ESTRADA DA FLORESTA", None, "FLORESTA SUL", "AC")
    assert c["area_terreno"] == 49338.00 and c["descricao"] is None
    assert "Número" in r["nao_encontrados"] and "Quartos" in r["nao_encontrados"]
    assert "Data de encerramento" not in r["nao_encontrados"]   # Compra Direta nao tem


def test_texto_colado_le_igual_a_pagina_salva():
    for nome in ("leilao_sfi", "licitacao_aberta", "compra_direta"):
        salva = ler_pagina_caixa(pagina(nome))["campos"]
        colada = ler_pagina_caixa(texto_da_pagina(pagina(nome)))["campos"]
        salva.pop("link"), colada.pop("link")   # o link so vem na pagina salva
        assert colada == salva, nome


def test_texto_colado_da_venda_online_em_andamento_avisa_a_data():
    # Colando o texto, o script do cronometro nao vem: a data fica para preencher a mao.
    texto = texto_da_pagina(pagina("venda_online")).replace("Venda online encerrada em 26/10/2026 18:00:00.", "")
    r = ler_pagina_caixa(texto)
    assert r["campos"]["data_encerramento"] is None
    assert "Data de encerramento" in r["nao_encontrados"]


def test_gravame_vira_sim_com_o_texto():
    aviso = ("Imóvel com gravame/penhora/indisponibilidade averbada na matrícula. "
             "Regularização por conta do adquirente")
    html = pagina("licitacao_aberta").replace("<p>FORMAS DE PAGAMENTO ACEITAS:", f"<p>{aviso}</p><p>FORMAS DE PAGAMENTO ACEITAS:")
    c = ler_pagina_caixa(html)["campos"]
    assert c["gravame"] is True and c["gravame_texto"] == aviso
    assert ler("licitacao_aberta")["campos"]["gravame"] is False


def test_pagina_errada_ou_captcha():
    for conteudo in ("", "<html><head><title>Radware Bot Manager CAPTCHA</title></head><body></body></html>",
                     "um texto qualquer"):
        r = ler_pagina_caixa(conteudo)
        assert not r["ok"] and "Não parece a página de um imóvel da CAIXA" in r["erro"] and r["campos"] == {}


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
