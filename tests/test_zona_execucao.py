"""
Testes da protecao contra arquivos de outra avaliacao (situacao C):
o Agente 5 so usa a zona homogenea e os demais JSONs gravados por ESTA avaliacao.
Sem rede: usa arquivos de exemplo numa pasta temporaria.

    .venv/Scripts/python.exe -m tests.test_zona_execucao
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

import agents.price_liquidity as ag5
from agents.execucao import ler_json_da_execucao

ID = "exec-atual"
OUTRO = "exec-anterior"


def _comparaveis(n=4, preco_base=500000.0):
    return [
        {
            "url": f"https://exemplo/{i}", "propertyType": "Apartamentos", "tipo": "apartamento",
            "price": preco_base + i * 10000, "area": 80.0, "cluster": "A",
            "classificacao_zona": "na_zona",
        }
        for i in range(n)
    ]


ALVO = {"propertyType": "Apartamentos", "tipo": "apartment", "area": 80.0}


def _preparar(pasta, zona=None, ag2=None):
    """Aponta o Agente 5 para `pasta` e grava os JSONs pedidos."""
    ag5.DATA_DIR = pasta
    ag5.CAMINHO_ZONA = os.path.join(pasta, "zona_homogenea_ag2.json")
    ag5.CAMINHO_AG3 = os.path.join(pasta, "imoveis_analisados_ag3.json")
    ag5.CAMINHO_AG4 = os.path.join(pasta, "infra_avaliada_ag4.json")
    ag5.CAMINHO_SAIDA = os.path.join(pasta, "preco_liquidez_ag5.json")
    if zona is not None:
        with open(ag5.CAMINHO_ZONA, "w", encoding="utf-8") as f:
            json.dump(zona, f)
    if ag2 is not None:
        with open(os.path.join(pasta, "imoveis_comparaveis_ag2.json"), "w", encoding="utf-8") as f:
            json.dump(ag2, f)


def _rodar(zona=None, ag2=None, id_execucao=ID):
    with tempfile.TemporaryDirectory() as pasta:
        _preparar(pasta, zona=zona, ag2=ag2)
        return ag5.estimar_preco(imovel_alvo_extra=dict(ALVO), id_execucao=id_execucao)


def test_zona_desta_avaliacao_calcula_normalmente():
    r = _rodar(zona={"id_execucao": ID, "comparaveis_confirmados": _comparaveis()})
    assert r["status_avaliacao"] == "ok", r["status_avaliacao"]
    assert r["avaliacao_planilha"]["valor_medio_imovel"] > 0


def test_zona_de_outra_avaliacao_vira_sem_amostra():
    # Situacao C: a zona nao rodou agora e o arquivo em disco e da avaliacao anterior.
    r = _rodar(zona={"id_execucao": OUTRO, "comparaveis_confirmados": _comparaveis()})
    assert r["status_avaliacao"] == "sem_amostra", r["status_avaliacao"]
    assert r["avaliacao_confiavel"] is False
    assert "nao foi calculada nesta avaliacao" in r["avisos"][0], r["avisos"]


def test_zona_inexistente_vira_sem_amostra():
    r = _rodar(zona=None, ag2={"id_execucao": ID, "comparaveis": _comparaveis()})
    assert r["status_avaliacao"] == "sem_amostra", r["status_avaliacao"]


def test_situacao_b_zona_vazia_desta_avaliacao_usa_cluster_a_do_ag2():
    # Alvo nao geocodificado: a zona RODOU (grava o id) mas sem confirmados.
    r = _rodar(
        zona={"id_execucao": ID, "status": "zona_nao_verificada", "comparaveis_confirmados": []},
        ag2={"id_execucao": ID, "comparaveis": _comparaveis()},
    )
    assert r["status_avaliacao"] == "ok", r["status_avaliacao"]


def test_situacao_b_com_ag2_de_outra_avaliacao_nao_usa():
    r = _rodar(
        zona={"id_execucao": ID, "comparaveis_confirmados": []},
        ag2={"id_execucao": OUTRO, "comparaveis": _comparaveis()},
    )
    assert r["status_avaliacao"] == "sem_amostra", r["status_avaliacao"]


def test_sem_id_execucao_mantem_comportamento_antigo():
    # Testes e scripts antigos chamam sem id: le o arquivo como antes.
    r = _rodar(zona={"comparaveis_confirmados": _comparaveis()}, id_execucao=None)
    assert r["status_avaliacao"] == "ok", r["status_avaliacao"]


def test_resultado_registra_o_id_execucao():
    r = _rodar(zona={"id_execucao": ID, "comparaveis_confirmados": _comparaveis()})
    assert r["id_execucao"] == ID


def test_leitor_ignora_arquivo_de_outra_avaliacao_e_corrompido():
    with tempfile.TemporaryDirectory() as pasta:
        caminho = os.path.join(pasta, "x.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"id_execucao": OUTRO, "a": 1}, f)
        assert ler_json_da_execucao(caminho, ID) is None
        assert ler_json_da_execucao(caminho, OUTRO) == {"id_execucao": OUTRO, "a": 1}
        assert ler_json_da_execucao(caminho, None) == {"id_execucao": OUTRO, "a": 1}
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("{quebrado")
        assert ler_json_da_execucao(caminho, ID) is None
        assert ler_json_da_execucao(os.path.join(pasta, "nao_existe.json"), ID) is None


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    originais = {k: getattr(ag5, k) for k in ("DATA_DIR", "CAMINHO_ZONA", "CAMINHO_AG3", "CAMINHO_AG4", "CAMINHO_SAIDA")}
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    falhas = 0
    try:
        for nome, fn in testes:
            try:
                fn()
                print(f"OK    {nome}")
            except AssertionError as e:
                falhas += 1
                print(f"FALHA {nome}: {e}")
    finally:
        for k, v in originais.items():
            setattr(ag5, k, v)
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
