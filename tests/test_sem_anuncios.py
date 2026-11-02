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


def test_texto_da_coleta_vazia():
    from services.textos_tela import texto_coleta_vazia
    assert texto_coleta_vazia(None) == "O banco de anúncios não tem casas nem terrenos à venda nesta região."
    c = {"contagem": {"brutos": 5, "removidos_leilao": 1, "sem_preco_ou_local": 2, "fora_da_regiao": 2}}
    assert texto_coleta_vazia(c) == (
        "O banco de anúncios trouxe 5 anúncios, mas nenhum serve para comparar: 1 era de leilão ou da própria "
        "CAIXA (inclusive anúncios do próprio imóvel); 2 não tinham preço ou localização; 2 eram de fora da "
        "região do imóvel.")


def test_texto():
    assert texto_sem_anuncios("Casa", "FEIJO", "ac") == (
        "Não há casas nem terrenos à venda em Feijo/AC na base de anúncios que sirvam para comparar; "
        "não é possível estimar o valor de mercado.")
    assert texto_sem_anuncios("Apartamento", "", "").startswith("Não há apartamentos nem terrenos à venda em nesta cidade")


def test_anuncio_copiado_da_pagina_da_caixa_e_leilao():
    from agents.collector import _eh_leilao
    # Atalaia/PR: o proprio imovel da CAIXA revendido por corretores, sem a palavra "leilao".
    vdp = {"title": "Imóvel selecionado Caixa — Casa no Centro, Atalaia - PR, Nº 125, 300m² | Venda Online",
           "description": ". Cadastro do Imóvel nº 707 (prefeitura Municipal). Baixar matrícula do imóvelrua curitiba, N. 125"}
    terreno = {"title": "R$ 88.518,56 - Terreno - PR - ATALAIA - GLEBA ATALAIA",
               "description": "[! ] oportunidade caixa: Imóvel com 39% de Desconto! Terreno, 0. 00 de área total"}
    apto = {"title": "Imóvel com potencial de valorização — Apartamento no Cavalhada, Porto Alegre",
            "description": "2 Quartos, Wc, Sala, Cozinha. .Baixar matrícula do imóvelRUA DOUTOR JULIO TEIXEIRA"}
    assert _eh_leilao(vdp) and _eh_leilao(terreno) and _eh_leilao(apto)
    # Anuncio comum com "VENDA ONLINE" (corretor de BH) continua.
    comum = {"title": "Maravilhosa Casa com 5 Quartos e 5 banheiros à Venda Mangabeiras",
             "description": "VENDA ONLINE - Agendamento de visita pelo Site ou Whatsapp - Aprovação de cadastro online"}
    assert not _eh_leilao(comum)


def test_tela_sem_anuncios_mostra_o_motivo_e_o_leilao():
    import agents.collector as ag1
    import agents.comparables as ag2
    import services.banco as banco
    import services.cep as cep
    originais = (ag1.coletar_imoveis, ag2._geocodificar_com_fallback, cep.buscar_cep, banco.gravar_em_segundo_plano)
    # Como em Atalaia: o banco trouxe 20, todos da CAIXA (resumo guardado pela coleta).
    ag1.coletar_imoveis = lambda **kw: (ag1._guardar_resumo_coleta(
        kw["id_execucao"], {"contagem": {"brutos": 20, "removidos_leilao": 20, "antes_dos_repetidos": 0, "unicos": 0,
                                          "repetidos_juntados": 0, "mantidos": 0, "repetidos": 0,
                                          "cortados_pelo_limite": 0, "repetidos_dos_cortados": 0},
                             "descartados": [
            {"url": "https://x/1", "tipo": "Casas", "preco": 387737.0, "area": 179.0, "rua": "Rua Curitiba, 125",
             "anunciante": "SSI IMÓVEIS", "motivo": "leilão ou imóvel da CAIXA"}]}), [])[1]
    ag2._geocodificar_com_fallback = lambda **_: (-8.1766, -70.354, "rua", "Rua 21 de Dezembro")
    cep.buscar_cep = lambda _cep: (None, "nao_encontrado")
    gravados = []
    banco.gravar_em_segundo_plano = lambda execucao, comparaveis: gravados.append((execucao, comparaveis))
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
        # Gravada no banco como "Sem estimativa", com o leilao e sem comparaveis.
        assert len(gravados) == 1, gravados
        execucao, comparaveis = gravados[0]
        assert execucao["status_agente5"] == "sem_amostra" and comparaveis == []
        assert execucao["decisao"] == "Sem estimativa" and execucao["valor_minimo"] == 148492.0, execucao["decisao"]
        assert execucao["anuncios_encontrados"] == 0 and execucao["resultado_completo"]
        # O "Ver avaliacao completa" (leiloes ativos) abre esse resultado sem erro.
        tela = AppTest.from_file("app/interface.py", default_timeout=120)
        gravado = execucao["resultado_completo"]["resultado"]          # como os leiloes ativos abrem
        tela.session_state["resultado"] = {**gravado, "registro": {"execucao": execucao}}
        tela.session_state["imovel_alvo_dados"] = gravado.get("imovel_alvo") or {}
        tela.run()
        assert not tela.exception, [e.value for e in tela.exception]
        textos = " ".join(m.value for m in tela.markdown)
        assert ("O banco de anúncios trouxe 20 anúncios, mas nenhum serve para comparar: 20 eram de leilão "
                "ou da própria CAIXA (inclusive anúncios do próprio imóvel).") in textos, textos[:500]
        assert "Nenhum anúncio chegou a esta etapa: não há o que comparar." in textos
        assert "Todos foram analisados pela IA" not in textos and "Encontramos **0" not in textos
        assert "**Anúncios que vieram do banco (1) e por que saíram**" in textos
        assert "Rua Curitiba, 125" in textos and "leilão ou imóvel da CAIXA" in textos
        # Conferencia: sem problema falso no Agente 4 e com o motivo certo.
        from services.verificacoes import resumo_conferencia
        conf = resumo_conferencia(gravado)
        assert "problema" not in conf["titulo"], conf
        assert conf["frases"][0].startswith("Agente 1: O banco de anúncios trouxe 20 anúncios"), conf["frases"]
        assert all(f.endswith("não rodou: nenhum anúncio para comparar.") for f in conf["frases"][1:]), conf["frases"]
    finally:
        ag1.coletar_imoveis, ag2._geocodificar_com_fallback, cep.buscar_cep, banco.gravar_em_segundo_plano = originais


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
