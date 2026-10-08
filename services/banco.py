"""
Gravacao de cada avaliacao no PostgreSQL (Neon)
===============================================

Tabelas criadas manualmente a partir de db/schema.sql (o app nunca cria tabelas).

Regras:
  - Conexao por DATABASE_URL: st.secrets no Streamlit Cloud, .env localmente.
  - O Neon gratuito suspende o banco parado e "acorda" no primeiro acesso, com
    alguns segundos de atraso: timeout de conexao de TIMEOUT_CONEXAO_S.
  - A gravacao NUNCA quebra o app nem faz a tela esperar: roda em segundo plano e
    qualquer erro so vira um aviso no log.
  - As duas tabelas sao gravadas numa unica transacao (entra tudo ou nada).
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

TIMEOUT_CONEXAO_S = 15          # Neon "acordando" leva alguns segundos
TIMEOUT_COMANDO_MS = 20000      # nenhuma gravacao deve passar disso

COLUNAS_EXECUCOES = (
    "id_execucao", "versao_codigo", "parametros", "fontes", "modelos_ia", "tempo_s", "falhas",
    "origem", "codigo_caixa", "link", "modalidade", "tipo", "endereco", "bairro", "cidade", "uf",
    "area_privativa", "area_terreno", "quartos", "banheiros", "campos_presumidos",
    "valor_minimo", "valor_avaliacao",
    "anuncios_encontrados", "repetidos", "parecidos", "confirmados_na_zona",
    "usados_por_fallback", "terrenos_usados", "raio_zona_m",
    "valor_m2_construcao", "valor_m2_terreno", "valor_mercado", "liquidez",
    "status_agente5", "qtd_comparaveis_construcao", "qtd_terrenos",
    "lance_maximo", "sobra", "decisao", "tempo_venda", "alertas",
)
COLUNAS_JSON = {"parametros", "fontes", "modelos_ia", "falhas", "campos_presumidos", "alertas"}
COLUNAS_COMPARAVEIS = (
    "id_execucao", "tipo", "preco", "area", "valor_m2", "endereco", "bairro",
    "portal", "link", "status_zona", "entrou_no_calculo",
)


def obter_database_url() -> str:
    """DATABASE_URL de st.secrets (Streamlit Cloud) ou, localmente, do ambiente/.env."""
    try:
        import streamlit as st
        valor = st.secrets.get("DATABASE_URL")
        if valor:
            return str(valor)
    except Exception:
        pass
    return os.getenv("DATABASE_URL", "")


def gravar_execucao(execucao: dict, comparaveis: list[dict], database_url: str | None = None) -> bool:
    """
    Grava uma execucao e seus comparaveis numa transacao. Retorna True se gravou.
    Nunca levanta excecao: falha vira aviso no log.
    """
    url = database_url if database_url is not None else obter_database_url()
    if not url:
        logger.info("[Banco] DATABASE_URL nao configurada: avaliacao nao gravada")
        return False
    try:
        import psycopg
        from psycopg.types.json import Jsonb

        linha = [
            Jsonb(execucao.get(c)) if c in COLUNAS_JSON and execucao.get(c) is not None else execucao.get(c)
            for c in COLUNAS_EXECUCOES
        ]
        sql_execucao = (
            f"INSERT INTO execucoes ({', '.join(COLUNAS_EXECUCOES)}) "
            f"VALUES ({', '.join(['%s'] * len(COLUNAS_EXECUCOES))})"
        )
        sql_comparavel = (
            f"INSERT INTO comparaveis ({', '.join(COLUNAS_COMPARAVEIS)}) "
            f"VALUES ({', '.join(['%s'] * len(COLUNAS_COMPARAVEIS))})"
        )
        # prepare_threshold=None: o endereco "-pooler" do Neon passa por um pool de
        # conexoes que nao lida bem com comandos preparados reaproveitados.
        with psycopg.connect(url, connect_timeout=TIMEOUT_CONEXAO_S, prepare_threshold=None) as conexao:
            with conexao.transaction(), conexao.cursor() as cursor:
                cursor.execute(f"SET LOCAL statement_timeout = {int(TIMEOUT_COMANDO_MS)}")
                cursor.execute(sql_execucao, linha)
                if comparaveis:
                    cursor.executemany(
                        sql_comparavel,
                        [[c.get(col) for col in COLUNAS_COMPARAVEIS] for c in comparaveis],
                    )
        logger.info(
            f"[Banco] avaliacao {execucao.get('id_execucao')} gravada "
            f"({len(comparaveis)} comparaveis)"
        )
        return True
    except Exception as exc:
        logger.warning(
            f"[Banco] nao foi possivel gravar a avaliacao {execucao.get('id_execucao')}: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def gravar_em_segundo_plano(execucao: dict, comparaveis: list[dict]) -> threading.Thread:
    """Dispara gravar_execucao numa thread: a tela nao espera o banco."""
    database_url = obter_database_url()   # le os secrets ainda na thread do Streamlit
    thread = threading.Thread(
        target=gravar_execucao,
        args=(execucao, comparaveis, database_url),
        name=f"gravar-{execucao.get('id_execucao')}",
        daemon=True,
    )
    thread.start()
    return thread
