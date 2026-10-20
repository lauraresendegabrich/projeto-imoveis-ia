"""
Semelhanca de descricoes na checagem do proprio anuncio: um texto que e PARTE do
outro nao pode dar nota baixa (continencia), sem casar textos genericos. Sem rede.

    .venv/Scripts/python.exe -m tests.test_descricao_continencia
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

import agents.comparables as ag2

COMPLETA = ("CÓDIGO DO IMÓVEL : CA0406<br><br>LOCALIZAÇÃO: Localizado na Praia do sonho <br><br>AMBIENTES: "
            "Casa com 8 quartos sendo 6 suítes, com varanda, espaço gourmet, ótima localização a 570m da praia. "
            "<br><br>DIFERENCIAIS: Casa com piscina, área externa, casa em ótimo estado para potencial turístico."
            "<br><br>Agende sua visita!<br>Atendemos sábado, domingo e feriado.(Plantão de vendas)<br>Pagani Imóveis<br>")
TRECHO = ("CÓDIGO DO IMÓVEL : CA0406\n\nLOCALIZAÇÃO: Localizado na Praia do sonho \n\nAMBIENTES: Casa com 8 "
          "quartos sendo 6 suítes, com varanda, espaço gourmet, ótima localização a 570m da praia.")
RODAPE = "Agende sua visita! Atendemos sábado, domingo e feriado.(Plantão de vendas) Pagani Imóveis"

ALVO = {"rua": "", "numero": "", "bairro": "Praia do Sonho", "neighborhood": "Praia do Sonho", "cidade": "Palhoça",
        "estado": "SC", "tipo": "house", "propertyType": "Casas", "area": 360.0, "bedrooms": 8, "bathrooms": 6,
        "parkingSpaces": 2, "price": 1200000.0, "descricao_gerada": False}


def anuncio(desc):
    return {"url": "https://vr/2903862416", "propertyType": "Casas", "tipo": "casa", "price": 1200000.0,
            "area": 360.0, "bedrooms": 8, "bathrooms": 6, "parkingSpaces": 2, "neighborhood": "Praia do Sonho",
            "description": desc}


def test_a_palhoca_trecho_inicial_confirma():
    assert ag2._similaridade_descricao(TRECHO, COMPLETA) >= 0.75
    eh, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, description=TRECHO), anuncio(COMPLETA))
    assert eh and any(s.startswith("casa_preco_area_descricao") for s in sinais), sinais


def test_b_anuncios_diferentes_com_o_mesmo_rodape_nao_confirmam():
    casa_1 = ("Casa térrea com 3 quartos, sala ampla, cozinha planejada, quintal com churrasqueira e garagem "
              "para dois carros, no bairro Ponte do Imaruim, perto de escola e mercado. " + RODAPE)
    casa_2 = ("Sobrado com 4 suítes, piscina aquecida, espaço gourmet integrado e vista para o mar na Pinheira, "
              "acabamento de alto padrão e energia solar instalada. " + RODAPE)
    assert ag2._similaridade_descricao(casa_1, casa_2) < 0.75, ag2._similaridade_descricao(casa_1, casa_2)
    eh, _, _, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, description=casa_1), anuncio(casa_2))
    assert not eh
    # So o rodape colado (curto e generico) tambem nao confirma.
    assert ag2._similaridade_descricao(RODAPE, casa_2) < 0.75


def test_c_texto_curto_contido_nao_usa_continencia():
    curto = "Casa com piscina, área externa, casa em ótimo estado para potencial turístico."
    assert 60 <= len(ag2._normalizar_texto(curto)) < ag2.CONTINENCIA_MIN_CARACTERES
    assert ag2._similaridade_descricao(curto, COMPLETA) < 0.75, ag2._similaridade_descricao(curto, COMPLETA)


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
