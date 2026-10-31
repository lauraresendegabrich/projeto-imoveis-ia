"""
Nenhum anuncio coletado (Feijo/AC, 31/10/2026: a base so tinha um galpao e fazendas):
a tela diz o motivo, sem "tente outro bairro", e mostra o cartao do leilao com a
resposta "Sem estimativa". Coleta e geocodificacao simuladas. Sem rede.

    .venv/Scripts/python.exe -m tests.test_sem_anuncios
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from streamlit.testing.v1 import AppTest

from services.textos_tela import texto_sem_anuncios

PAGINA_FEIJO = """SETOR 06
Valor de avaliação: R$ 148.492,00
Valor mínimo de venda 1º Leilão: R$ 148.492,00
Valor mínimo de venda 2º Leilão: R$ 89.095,20
Tipo de imóvel: Casa
Quartos: 2
Número do imóvel: 844440314644-6
Matrícula(s): 1344
Comarca: FEIJO-AC
Área total = 64,00m2
Área privativa = 64,00m2
Área do terreno = 456,00m2
Leilão SFI
Edital: 0056/0226 - CPA/RE
Número do item: 1
Leiloeiro(a): JOSECELLI KILDARE FRAGA GOMES
 Data do 1º Leilão - 14/12/2026 - 10h00
 Data do 2º Leilão - 17/12/2026 - 10h00
Endereço:
RUA 21 DE DEZEMBRO,N. SN QD 24 COD 28, NAIR ARAÚJO - CEP: 69960-000, FEIJO - ACRE
Descrição:
2 Quartos, Área de Serviço, Wc, Sala, Cozinha. .
"""


def test_texto():
    assert texto_sem_anuncios("Casa", "FEIJO", "ac") == (
        "Não há casas nem terrenos à venda em Feijo/AC na base de anúncios; "
        "não é possível estimar o valor de mercado.")
    assert texto_sem_anuncios("Apartamento", "", "").startswith("Não há apartamentos nem terrenos à venda em nesta cidade")


def test_tela_sem_anuncios_mostra_o_motivo_e_o_leilao():
    import agents.collector as ag1
    import agents.comparables as ag2
    import services.cep as cep
    originais = (ag1.coletar_imoveis, ag2._geocodificar_com_fallback, cep.buscar_cep)
    ag1.coletar_imoveis = lambda **_: []
    ag2._geocodificar_com_fallback = lambda **_: (-8.1766, -70.354, "rua", "Rua 21 de Dezembro")
    cep.buscar_cep = lambda _cep: (None, "nao_encontrado")
    try:
        at = AppTest.from_file("app/interface.py", default_timeout=120).run()
        at.sidebar.text_area(key="caixa_texto").input(PAGINA_FEIJO)
        next(b for b in at.sidebar.button if b.label == "Ler dados").click().run()
        next(b for b in at.sidebar.button if "Avaliar" in b.label).click().run()
        assert not at.exception, [e.value for e in at.exception]
        assert "❌ Sem estimativa: nenhum anúncio para comparar" in [s.value for s in at.subheader]
        erros = [e.value for e in at.error]
        assert any("Não há casas nem terrenos à venda em Feijo/AC" in e for e in erros), erros
        assert not any("Tente outro bairro" in e for e in erros)
        assert "#### 🔨 Avaliação de leilão" in [m.value for m in at.markdown]
        captions = " ".join(c.value for c in at.caption)
        assert "148.492" in captions, captions          # valor minimo do 1o leilao
    finally:
        ag1.coletar_imoveis, ag2._geocodificar_com_fallback, cep.buscar_cep = originais


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
