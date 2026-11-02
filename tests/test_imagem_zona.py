"""
Imagem de satelite da zona gravada junto do resultado (Cambe, 02/11/2026: o banco so
guardava o caminho de um arquivo local, sobrescrito a cada avaliacao). Sem rede.

    .venv/Scripts/python.exe -m tests.test_imagem_zona
"""
import base64
import io
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from PIL import Image
from streamlit.testing.v1 import AppTest

from agents.comparables import LARGURA_IMAGEM_GRAVADA, _imagem_para_gravar


def _png(largura=1280, altura=1280):
    saida = io.BytesIO()
    Image.new("RGB", (largura, altura), (40, 120, 60)).save(saida, format="PNG")
    return saida.getvalue()


def test_imagem_reduzida_em_jpeg():
    b64 = _imagem_para_gravar(_png())
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert img.format == "JPEG" and img.width == LARGURA_IMAGEM_GRAVADA and img.height == LARGURA_IMAGEM_GRAVADA
    assert _imagem_para_gravar(None) is None and _imagem_para_gravar(b"nao e imagem") is None


def _tela(zona_extra):
    resultado = {
        "status": "completo", "resumo": {"cluster_a": 0},
        "preco_estimado": {"status_avaliacao": "amostra_insuficiente", "avaliacao_confiavel": False,
                           "comparaveis_usados": {"construcao": [], "terreno": []}},
        "comparaveis": [], "terrenos": [],
        "zona_homogenea": {"comparaveis_confirmados": [], "raio_final_m": 400,
                           "zona_homogenea": {"raio_metros": 400}, **zona_extra},
        "registro": {"execucao": {"alertas": []}, "comparaveis": []},
    }
    at = AppTest.from_file("app/interface.py", default_timeout=60)
    at.session_state["resultado"] = resultado
    at.session_state["imovel_alvo_dados"] = {"area": 100, "tipo": "house"}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_tela_mostra_a_imagem_gravada():
    at = _tela({"imagem_satelite_jpeg": _imagem_para_gravar(_png(400, 400))})
    assert len(at.get("imgs")) == 1


def test_sem_imagem_gravada_nao_mostra_arquivo_de_outra_avaliacao():
    # Avaliacao antiga: so o caminho do arquivo (que hoje e de outro imovel).
    at = _tela({"imagem_satelite": "data/satelite_zona_homogenea_ag2.png"})
    assert len(at.get("imgs")) == 0


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
