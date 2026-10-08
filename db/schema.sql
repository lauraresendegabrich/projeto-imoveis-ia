-- =============================================================================
-- Registro de cada avaliação (PostgreSQL / Neon)
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon. O app nunca cria tabelas: só insere.
-- Seguro para rodar de novo (IF NOT EXISTS).
--
-- execucoes   : uma linha por avaliação feita pela interface
-- comparaveis : uma linha por anúncio da zona considerado pelo Agente 5
--               (entrou ou não no cálculo), ligada por id_execucao
-- =============================================================================

CREATE TABLE IF NOT EXISTS execucoes (
    -- Identificação ---------------------------------------------------------
    id_execucao                 TEXT PRIMARY KEY,          -- mesmo id gravado nos JSONs dos agentes
    data_hora                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    versao_codigo               TEXT,                      -- hash do commit git ("desconhecida" se não houver)
    parametros                  JSONB,                     -- fator de lucro, mínimo de comparáveis, raio da zona...
    fontes                      JSONB,                     -- portais/coletas do Athena, Apify, Google Maps, Qwen...
    modelos_ia                  JSONB,                     -- serviço de IA usado em cada agente
    tempo_s                     NUMERIC(10, 1),
    falhas                      JSONB,                     -- lista de falhas/avisos da execução

    -- Entrada (o que o usuário informou) --------------------------------------
    origem                      TEXT NOT NULL DEFAULT 'CAIXA',
    codigo_caixa                TEXT,
    link                        TEXT,
    modalidade                  TEXT,                      -- ex.: "Leilão SFI (valor do 1º leilão)"
    tipo                        TEXT,                      -- casa / apartamento
    endereco                    TEXT,                      -- rua e número
    bairro                      TEXT,
    cidade                      TEXT,
    uf                          CHAR(2),
    area_privativa              NUMERIC(12, 2),
    area_terreno                NUMERIC(12, 2),
    quartos                     INTEGER,
    banheiros                   INTEGER,
    campos_presumidos           JSONB,                     -- campos supostos quando não informados (hoje vazio)
    valor_minimo                NUMERIC(14, 2),            -- valor mínimo de venda CAIXA
    valor_avaliacao             NUMERIC(14, 2),            -- valor de avaliação CAIXA (só informativo)

    -- Funil -------------------------------------------------------------------
    anuncios_encontrados        INTEGER,                   -- imóveis únicos entregues pelo Agente 1
    repetidos                   INTEGER,                   -- anúncios do mesmo imóvel descartados
    parecidos                   INTEGER,                   -- Cluster A do Agente 2
    confirmados_na_zona         INTEGER,
    usados_por_fallback         INTEGER,                   -- usados no cálculo sem confirmação na zona
    terrenos_usados             INTEGER,
    raio_zona_m                 INTEGER,

    -- Cálculo (Agente 5) ---------------------------------------------------------
    valor_m2_construcao         NUMERIC(14, 2),
    valor_m2_terreno            NUMERIC(14, 2),
    valor_mercado               NUMERIC(14, 2),            -- valor médio estimado
    liquidez                    NUMERIC(14, 2),            -- valor médio − 10%

    -- Resposta ----------------------------------------------------------------
    status_agente5              TEXT,                      -- ok / sem_amostra / valor_nao_estimado / amostra_insuficiente
    qtd_comparaveis_construcao  INTEGER,
    qtd_terrenos                INTEGER,
    lance_maximo                NUMERIC(14, 2),            -- liquidez ÷ fator de lucro
    sobra                       NUMERIC(14, 2),            -- lance máximo − valor mínimo (negativa = falta)
    decisao                     TEXT,                      -- Não descartar / Descartar / Sem estimativa
    tempo_venda                 TEXT,

    -- Conferência manual (preenchida depois) -----------------------------------
    faz_sentido                 BOOLEAN,
    observacao                  TEXT
);

CREATE INDEX IF NOT EXISTS idx_execucoes_data_hora ON execucoes (data_hora DESC);
CREATE INDEX IF NOT EXISTS idx_execucoes_cidade_uf ON execucoes (uf, cidade);
CREATE INDEX IF NOT EXISTS idx_execucoes_decisao ON execucoes (decisao);


CREATE TABLE IF NOT EXISTS comparaveis (
    id                  BIGSERIAL PRIMARY KEY,
    id_execucao         TEXT NOT NULL REFERENCES execucoes (id_execucao) ON DELETE CASCADE,
    tipo                TEXT NOT NULL CHECK (tipo IN ('construcao', 'terreno')),
    preco               NUMERIC(14, 2),
    area                NUMERIC(12, 2),
    valor_m2            NUMERIC(14, 2),                    -- preço ÷ área do anúncio
    endereco            TEXT,
    bairro              TEXT,
    portal              TEXT,
    link                TEXT,
    status_zona         TEXT CHECK (status_zona IN ('confirmado', 'fallback', 'sem_validacao')),
    entrou_no_calculo   BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comparaveis_execucao ON comparaveis (id_execucao);
