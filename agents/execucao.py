"""
Identificador de cada avaliacao (id_execucao)
==============================================

Os agentes trocam dados por arquivos JSON em data/ (zona_homogenea_ag2.json,
imoveis_comparaveis_ag2.json, imoveis_analisados_ag3.json, infra_avaliada_ag4.json).
Os Agentes 3, 4 e 5 leem arquivos escritos por etapas anteriores. Se uma etapa nao
roda nesta avaliacao (ex.: zona homogenea sem GOOGLE_MAPS_KEY ou com erro), o arquivo
que fica em disco e o da avaliacao ANTERIOR, de outro imovel, e era lido como se fosse
desta. No Streamlit Cloud a pasta data/ tambem e compartilhada entre pessoas avaliando
ao mesmo tempo.

Cada avaliacao gera um id_execucao, cada agente o grava no JSON que escreve, e quem le
so aceita o arquivo com o mesmo id. Chamadas sem id_execucao (testes e scripts antigos)
mantem o comportamento anterior.
"""
from __future__ import annotations

import json
import logging
import os
import uuid

logger = logging.getLogger(__name__)


def novo_id_execucao() -> str:
    return uuid.uuid4().hex


def ler_json_da_execucao(caminho: str, id_execucao: str | None) -> dict | None:
    """
    Conteudo do JSON em `caminho`, ou None se ele nao existe, esta corrompido ou,
    quando `id_execucao` e informado, foi escrito por outra avaliacao.
    """
    if not os.path.exists(caminho):
        return None
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[Execucao] {os.path.basename(caminho)} ilegivel: {exc}")
        return None
    if not isinstance(dados, dict):
        return None
    if id_execucao and dados.get("id_execucao") != id_execucao:
        logger.warning(
            f"[Execucao] {os.path.basename(caminho)} e de outra avaliacao "
            f"(id={dados.get('id_execucao')}, esperado={id_execucao}); ignorado"
        )
        return None
    return dados
