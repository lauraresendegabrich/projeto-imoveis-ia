"""
Pasta temporaria para os testes que rodam a zona do Agente 2: sem isso, o Agente 2
grava zona_homogenea_ag2.json e a imagem de satelite (falsa, nos testes) em data/,
por cima dos arquivos da ultima avaliacao feita no computador.
"""
import contextlib
import tempfile

import agents.comparables as ag2


@contextlib.contextmanager
def data_dir_temporario():
    """Durante o bloco, o Agente 2 grava numa pasta temporaria (apagada no fim)."""
    original = ag2.DATA_DIR
    with tempfile.TemporaryDirectory() as pasta:
        ag2.DATA_DIR = pasta
        try:
            yield pasta
        finally:
            ag2.DATA_DIR = original
