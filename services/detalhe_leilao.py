"""
Avaliacao completa de um imovel de leilao ("Ver avaliacao completa" na pagina
"Leiloes ativos").

Na gravacao (migracao 006), execucoes.resultado_completo guarda o resultado dos 5
agentes como a tela de resultado o usa, sem as fotos e descricoes dos anuncios (a
maior parte do tamanho; a tela nao as mostra). Na leitura, a tela e remontada com
ele; o cartao do leilao e refeito com a etapa atual do imovel (mesma conta de
services/leilao.py), como na lista. Sem resultado_completo (avaliacao anterior a
006), o cartao sai do que as colunas da execucao guardam.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import PurePath

from services.leilao import avaliar_imovel_leilao
from services.leiloes_ativos import _conectar, _simples
from services.banco import TIMEOUT_COMANDO_MS

logger = logging.getLogger(__name__)

VERSAO_RESULTADO = 1
# Acima disso (JSON em bytes) a coluna fica vazia: o resto da avaliacao e gravado.
TAMANHO_MAX_RESULTADO = 5_000_000
# Campos dos anuncios que a tela nao mostra e que fazem a maior parte do tamanho.
CAMPOS_FORA_DO_RESULTADO = frozenset({"fotos_urls", "images", "fotos", "imagens", "descricao", "description"})
# Do resultado da sessao: "registro" e o proprio registro do banco (sai das colunas).
CHAVES_FORA_DO_RESULTADO = frozenset({"registro"})

SQL_EXECUCAO = "SELECT * FROM execucoes WHERE id_execucao = %s"
SQL_IMOVEL = "SELECT * FROM imoveis_leilao WHERE id = %s"
SQL_COMPARAVEIS = "SELECT * FROM comparaveis WHERE id_execucao = %s ORDER BY id"


def para_json(valor):
    """
    Copia que o JSONB aceita: datas em ISO, Decimal e numeros do numpy em float, NaN e
    infinito em None, tuplas em listas, chaves em texto e sem o caractere nulo (o
    Postgres recusa os dois ultimos). Tira os campos de CAMPOS_FORA_DO_RESULTADO.
    """
    if valor is None or isinstance(valor, bool):
        return valor
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, str):
        return valor.replace("\x00", "")
    if isinstance(valor, dict):
        return {str(k): para_json(v) for k, v in valor.items() if k not in CAMPOS_FORA_DO_RESULTADO}
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [para_json(v) for v in valor]
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return para_json(float(valor))
    if isinstance(valor, PurePath):
        return str(valor)
    if hasattr(valor, "item"):          # numpy.int64, numpy.float64...
        try:
            return para_json(valor.item())
        except (TypeError, ValueError):
            pass
    return str(valor)


def resultado_para_gravar(resultado: dict, tela: dict) -> dict | None:
    """
    Valor de execucoes.resultado_completo: {versao, resultado, tela}. `tela` sao os
    campos do formulario que a tela de resultado mostra (rua, numero, bairro, cidade,
    estado, tipo, quartos, banheiros, vagas). None se passar de TAMANHO_MAX_RESULTADO
    ou der erro: o resto da avaliacao e gravado do mesmo jeito.
    """
    try:
        completo = {
            "versao": VERSAO_RESULTADO,
            "resultado": para_json({k: v for k, v in resultado.items() if k not in CHAVES_FORA_DO_RESULTADO}),
            "tela": para_json(tela),
        }
        tamanho = len(json.dumps(completo, ensure_ascii=False).encode("utf-8"))
    except Exception as exc:
        logger.warning(f"[Banco] resultado completo nao montado: {type(exc).__name__}: {exc}")
        return None
    if tamanho > TAMANHO_MAX_RESULTADO:
        logger.warning(f"[Banco] resultado completo com {tamanho // 1024} KB: nao gravado (limite "
                       f"{TAMANHO_MAX_RESULTADO // 1024} KB)")
        return None
    return completo


def _linha(cursor) -> dict | None:
    registro = cursor.fetchone()
    if registro is None:
        return None
    return {c.name: _simples(v) for c, v in zip(cursor.description, registro)}


def carregar_detalhe(database_url: str, id_execucao: str, id_imovel: int | None) -> dict:
    """{execucao, imovel, comparaveis} lidos do banco (Decimal -> float). Erro de banco sobe."""
    with _conectar(database_url) as conexao, conexao.cursor() as cursor:
        cursor.execute(f"SET statement_timeout = {int(TIMEOUT_COMANDO_MS)}")
        cursor.execute(SQL_EXECUCAO, (id_execucao,))
        execucao = _linha(cursor)
        imovel = None
        if id_imovel is not None:
            cursor.execute(SQL_IMOVEL, (int(id_imovel),))
            imovel = _linha(cursor)
        cursor.execute(SQL_COMPARAVEIS, (id_execucao,))
        colunas = [c.name for c in cursor.description]
        comparaveis = [{c: _simples(v) for c, v in zip(colunas, r)} for r in cursor.fetchall()]
    return {"execucao": execucao, "imovel": imovel, "comparaveis": comparaveis}


def agente5_do_registro(execucao: dict) -> dict:
    """
    O que avaliar_leilao le do Agente 5, a partir das colunas da execucao (avaliacao
    sem resultado_completo). So "ok" com lance maximo gravado conta como confiavel,
    como na lista (services/leiloes_ativos.py).
    """
    confiavel = execucao.get("status_agente5") == "ok" and execucao.get("lance_maximo") is not None
    return {
        "status_avaliacao": execucao.get("status_agente5"),
        "avaliacao_confiavel": confiavel,
        "avaliacao_planilha": {"valor_liquidez": execucao.get("liquidez"),
                               "valor_medio_imovel": execucao.get("valor_mercado")},
    }


def montar_detalhe(dados: dict, agora: datetime | None = None) -> dict | None:
    """
    O que a tela de detalhe mostra, a partir de carregar_detalhe:
      resultado : o da tela de resultado (None sem resultado_completo), com o cartao do
                  leilao refeito na etapa atual e o registro do banco (alertas e Excel)
      tela      : campos do formulario mostrados (None sem resultado_completo)
      leilao    : cartao do leilao na etapa atual (None sem valor minimo)
      execucao  : linha da execucao, com _imovel_leilao (para o Excel)
      comparaveis : linhas de comparaveis
    None se a execucao nao esta no banco.
    """
    execucao = dados.get("execucao")
    if not execucao:
        return None
    execucao = dict(execucao)
    imovel = dados.get("imovel")
    comparaveis = dados.get("comparaveis") or []
    execucao["_imovel_leilao"] = imovel
    completo = execucao.get("resultado_completo") or {}
    resultado = completo.get("resultado")

    agente5 = (resultado or {}).get("preco_estimado") or agente5_do_registro(execucao)
    leilao = avaliar_imovel_leilao(agente5, imovel, agora) if imovel else None
    if resultado is not None:
        resultado = dict(resultado)
        gravado = resultado.get("leilao") or {}
        if leilao is not None:
            for chave in ("aviso_zona", "alvo_sem_localizacao"):
                leilao[chave] = gravado.get(chave)
        resultado["leilao"] = leilao
        resultado["registro"] = {"execucao": execucao, "comparaveis": comparaveis}
    return {
        "resultado": resultado,
        "tela": completo.get("tela") if resultado is not None else None,
        "leilao": leilao,
        "execucao": execucao,
        "comparaveis": comparaveis,
    }
