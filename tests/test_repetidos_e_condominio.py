"""
Arapiraca, 31/10/2026 (casa de rua popular de leilao avaliada pelo dobro da CAIXA):
  - repetidos que escapavam: descricao com <br> num portal e nao no outro; similaridade
    que dependia da ordem dos anuncios; rua "Queiroz" x "Queiros" com o mesmo numero.
  - casa em condominio fechado nao e comparavel de casa de rua (pre-classificacao).
Sem rede.

    .venv/Scripts/python.exe -m tests.test_repetidos_e_condominio
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from agents import identidade as idt
from agents.comparables import _alvo_em_condominio, _casa_em_condominio, _pre_classificar

TEXTO = ("Uma residência pensada para quem valoriza conforto, privacidade e ambientes bem integrados, em um dos "
         "condomínios mais desejados de Arapiraca. Com uma proposta contemporânea e excelente aproveitamento dos "
         "espaços, o imóvel conta com 3 dormitórios, sendo 1 suíte, sala ampla, cozinha integrada e área gourmet.")


def casa(**extra):
    base = {"tipo": "casa", "propertyType": "Casas", "price": 450_000, "area": 120, "bedrooms": 2,
            "neighborhood": "Santa Esmeralda", "url": "https://x/1"}
    return {**base, **extra}


def test_descricao_com_html_e_o_mesmo_texto():
    a = TEXTO.replace(". ", ".<br><br>")
    assert idt.similaridade_descricao(a, TEXTO) == idt.similaridade_descricao(TEXTO, TEXTO)
    assert idt.sem_html("a<br>b&nbsp;c") == "a b c"


def test_similaridade_nao_depende_da_ordem():
    a, b = TEXTO, TEXTO.replace("Uma residência", "Residência").replace("ampla", "grande") + " Agende sua visita."
    assert idt.similaridade_descricao(a, b) == idt.similaridade_descricao(b, a)
    assert idt.ratio_simetrico("abcd" * 80, "abce" * 80) == idt.ratio_simetrico("abce" * 80, "abcd" * 80)


def test_rua_com_grafia_proxima_e_o_mesmo_numero_junta():
    a = casa(street="Rua José Cícero de Queiroz, 1127", url="https://x/a", description="Casa ampla.")
    b = casa(street="Rua José Cícero De Queirós, 1127", url="https://x/b", description="Outro texto.")
    assert idt.mesmo_imovel(a, b)[0] and idt.mesmo_imovel(b, a)[0]
    # Outro numero ou outro preco: continua separado.
    assert not idt.mesmo_imovel(a, dict(b, street="Rua José Cícero De Queirós, 1129"))[0]
    assert not idt.mesmo_imovel(a, dict(b, price=440_000))[0]


def test_casa_em_condominio():
    assert _casa_em_condominio({"property_sub_type": "CONDOMINIUM"})
    assert _casa_em_condominio({"url": "https://www.vivareal.com.br/imovel/casa-de-condominio-3-quartos-x"})
    assert _casa_em_condominio({"title": "Imóvel em condomínio fechado no bairro Arnon de Melo"})
    assert _casa_em_condominio({"description": TEXTO})
    # Representante sem sinal, repetido juntado com o subtipo do portal.
    assert _casa_em_condominio({"duplicatas": [{"dados_identidade": {"property_sub_type": "CONDOMINIUM"}}]})
    # Nao e condominio.
    assert not _casa_em_condominio({"description": "Casa de rua, sem condomínio, 3 quartos"})
    assert not _casa_em_condominio({"description": "Condomínio: Sob responsabilidade do comprador."})
    assert not _casa_em_condominio({"title": "Casa com 3 quartos à venda na Rua São João, 1243"})


def test_alvo_de_rua_recusa_comparavel_em_condominio():
    alvo = {"tipo": "house", "propertyType": "Casas", "area": 121.86, "rua": "RUA MARIA DE LOURDES DE OLIVEIRA",
            "description": "3 Quartos, 1 Vaga na Garagem, 2 Wc, 2 Salas, Cozinha"}
    cond = casa(area=110, property_sub_type="CONDOMINIUM")
    r = _pre_classificar(alvo, cond)
    assert not r["elegivel_llm"] and r["condominio_x_rua"], r["motivos_incompatibilidade"]
    assert "casa em condominio fechado (o imovel e casa de rua)" in r["motivos_incompatibilidade"]
    assert _pre_classificar(alvo, casa(area=110))["elegivel_llm"]
    # Alvo em condominio: a regra nao se aplica.
    alvo_cond = dict(alvo, rua="RUA A COND RES JARDIM ALTO")
    assert _alvo_em_condominio(alvo_cond) and _pre_classificar(alvo_cond, cond)["elegivel_llm"]


def test_prompt_diz_que_a_area_ja_passou_no_filtro():
    from agents.comparables import _montar_prompt_clustering
    alvo = {"propertyType": "Casas", "area": 121.86, "bedrooms": 3, "bathrooms": 2}
    prompt = _montar_prompt_clustering(alvo, [casa(area=154, bedrooms=3)], limite_area_pct=0.30)
    assert "todos os candidatos ja estao a ate 30% da area construida do alvo" in prompt
    assert "Diferenca de area dentro desse limite NAO e motivo para B sozinha" in prompt
    assert "ja estao a ate" not in _montar_prompt_clustering(alvo, [casa()])


def test_anuncio_sem_area_nao_completa_o_minimo_da_zona():
    from agents.comparables import _ampliar_raio

    def a(dist, **extra):
        return {"url": f"https://x/{dist}", "distancia_metros": dist, "geocodificacao_nivel": "coordenadas_athena",
                "price": 300_000, "area": 100, **extra}
    # Arapiraca: 5 na zona de 900 m, 1 sem area (duplex do Grandvista): o raio continua.
    confirmados = [a(345), a(631), a(763), a(784), a(405, area=None)]
    conf, _, raio = _ampliar_raio(confirmados, [a(966), a(1291), a(1336)], 900)
    assert raio == 1350 and len(conf) == 8, (raio, len(conf))


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
