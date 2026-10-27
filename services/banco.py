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
  - As tabelas sao gravadas numa unica transacao (entra tudo ou nada).
  - Imovel de leilao (imoveis_leilao): uma linha por banco + codigo. Avaliar de novo
    atualiza a linha, sem apagar o que a nova avaliacao nao trouxe (COALESCE) e sem
    mexer na situacao manual (vendido, retirado...). Se a modalidade mudou, os campos
    dela (datas, valores minimos, edital, item, leiloeiro) vem todos da nova.
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
    "valor_minimo", "valor_avaliacao", "data_leilao", "formas_pagamento", "regras_despesas",
    "localizacao_alvo", "escopo_busca", "anuncios_por_proximidade",
    "anuncios_encontrados", "repetidos", "parecidos", "confirmados_na_zona",
    "usados_por_fallback", "terrenos_usados", "raio_zona_m",
    "valor_m2_construcao", "valor_m2_terreno", "valor_mercado", "liquidez",
    "status_agente5", "qtd_comparaveis_construcao", "qtd_terrenos",
    "lance_maximo", "sobra", "decisao", "tempo_venda", "alertas",
    "entrada_usuario", "checagem_anuncio_alvo", "verificacoes",
    "id_imovel_leilao", "etapa_avaliada", "roi", "lance_limite_descarte",
)
COLUNAS_JSON = {
    "parametros", "fontes", "modelos_ia", "falhas", "campos_presumidos", "alertas", "formas_pagamento",
    "entrada_usuario", "checagem_anuncio_alvo", "verificacoes",
}
COLUNAS_IMOVEIS_LEILAO = (
    "banco", "codigo", "numero_imovel", "link", "modalidade",
    "data_1_leilao", "valor_minimo_1", "data_2_leilao", "valor_minimo_2",
    "valor_minimo", "data_encerramento", "valor_avaliacao",
    "tipo", "endereco", "bairro", "cidade", "uf",
    "edital", "numero_item", "leiloeiro", "matricula", "averbacao_leiloes_negativos",
    "gravame", "gravame_texto", "formas_pagamento", "regras_despesas",
)
COLUNAS_JSON_IMOVEIS_LEILAO = {"formas_pagamento"}
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


# Campos que dependem da modalidade: quando ela muda (ex.: Licitacao deserta que
# volta como Compra Direta), sao trocados pelos novos MESMO vazios, senao a data da
# licitacao antiga continuaria la e o imovel apareceria como encerrado.
COLUNAS_DA_MODALIDADE = (
    "data_1_leilao", "valor_minimo_1", "data_2_leilao", "valor_minimo_2",
    "valor_minimo", "data_encerramento", "edital", "numero_item", "leiloeiro",
)


def sql_gravar_imovel_leilao() -> str:
    """
    INSERT ... ON CONFLICT (banco, codigo). Mesma modalidade: atualiza sem apagar o que
    ja havia (campo vazio na avaliacao nova fica com o valor antigo). Modalidade nova:
    os campos da modalidade (COLUNAS_DA_MODALIDADE) vem todos da avaliacao nova. No
    UPDATE, imoveis_leilao.* e a linha antiga.
    """
    def atualizar(c):
        manter = f"COALESCE(EXCLUDED.{c}, imoveis_leilao.{c})"
        if c in COLUNAS_DA_MODALIDADE:
            return (f"{c} = CASE WHEN EXCLUDED.modalidade IS DISTINCT FROM imoveis_leilao.modalidade "
                    f"THEN EXCLUDED.{c} ELSE {manter} END")
        return f"{c} = {manter}"

    colunas = [c for c in COLUNAS_IMOVEIS_LEILAO if c not in ("banco", "codigo")]
    return (
        f"INSERT INTO imoveis_leilao ({', '.join(COLUNAS_IMOVEIS_LEILAO)}) "
        f"VALUES ({', '.join(['%s'] * len(COLUNAS_IMOVEIS_LEILAO))}) "
        f"ON CONFLICT (banco, codigo) DO UPDATE SET "
        + ", ".join(atualizar(c) for c in colunas)
        + ", atualizado_em = now() RETURNING id"
    )


def gravar_execucao(execucao: dict, comparaveis: list[dict], database_url: str | None = None) -> bool:
    """
    Grava uma execucao e seus comparaveis numa transacao. Retorna True se gravou.
    Com execucao["_imovel_leilao"], grava antes o imovel e liga a execucao a ele.
    Nunca levanta excecao: falha vira aviso no log.
    """
    url = database_url if database_url is not None else obter_database_url()
    if not url:
        logger.info("[Banco] DATABASE_URL nao configurada: avaliacao nao gravada")
        return False
    try:
        import psycopg
        from psycopg.types.json import Jsonb

        imovel = execucao.get("_imovel_leilao")
        linha_imovel = [
            Jsonb(imovel.get(c)) if c in COLUNAS_JSON_IMOVEIS_LEILAO and imovel.get(c) is not None else imovel.get(c)
            for c in COLUNAS_IMOVEIS_LEILAO
        ] if imovel else None
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
                execucao = dict(execucao)
                if linha_imovel:
                    cursor.execute(sql_gravar_imovel_leilao(), linha_imovel)
                    execucao["id_imovel_leilao"] = cursor.fetchone()[0]
                linha = [
                    Jsonb(execucao.get(c)) if c in COLUNAS_JSON and execucao.get(c) is not None else execucao.get(c)
                    for c in COLUNAS_EXECUCOES
                ]
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
