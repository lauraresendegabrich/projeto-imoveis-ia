-- =============================================================================
-- Registro de cada avaliação (PostgreSQL / Neon)
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon. O app nunca cria tabelas: só insere.
-- Seguro para rodar de novo (IF NOT EXISTS). Mudanças num banco que já existe
-- ficam em db/migracoes/ (rodar na ordem).
--
-- imoveis_leilao : uma linha por imóvel da CAIXA (modalidade, datas, valores)
-- execucoes   : uma linha por avaliação feita pela interface
-- comparaveis : uma linha por anúncio da zona considerado pelo Agente 5
--               (entrou ou não no cálculo), ligada por id_execucao
-- vw_leiloes / vw_leiloes_ativos : etapa atual, encerramento, ativo e última avaliação
-- =============================================================================

CREATE TABLE IF NOT EXISTS imoveis_leilao (
    id                          BIGSERIAL PRIMARY KEY,
    banco                       TEXT NOT NULL DEFAULT 'CAIXA',
    codigo                      TEXT NOT NULL,             -- dígitos do número do imóvel, sem zeros à esquerda
    numero_imovel               TEXT,                      -- como aparece no site: "855552271653-1"
    link                        TEXT,
    modalidade                  TEXT NOT NULL CHECK (modalidade IN
                                    ('Leilão SFI', 'Licitação Aberta', 'Venda Online', 'Compra Direta')),

    -- Leilão SFI: 1º e 2º leilão (o valor do 2º pode ser MAIOR: no 2º o mínimo é a dívida)
    data_1_leilao               TIMESTAMP,
    valor_minimo_1              NUMERIC(14, 2),
    data_2_leilao               TIMESTAMP,
    valor_minimo_2              NUMERIC(14, 2),
    -- Licitação Aberta, Venda Online e Compra Direta (esta sem encerramento)
    valor_minimo                NUMERIC(14, 2),
    data_encerramento           TIMESTAMP,

    valor_avaliacao             NUMERIC(14, 2),            -- só informativo

    -- Imóvel (para a lista de leilões ativos)
    tipo                        TEXT,
    endereco                    TEXT,
    bairro                      TEXT,
    cidade                      TEXT,
    uf                          CHAR(2),

    -- Página da CAIXA (todos opcionais)
    edital                      TEXT,
    numero_item                 TEXT,
    leiloeiro                   TEXT,
    matricula                   TEXT,
    averbacao_leiloes_negativos TEXT,                      -- "Averbado" / "Em tratamento" / "Não se aplica"
    gravame                     BOOLEAN,                   -- aviso de gravame/penhora/indisponibilidade na matrícula
    gravame_texto               TEXT,
    formas_pagamento            JSONB,
    regras_despesas             TEXT,

    situacao                    TEXT NOT NULL DEFAULT 'ativo'
                                    CHECK (situacao IN ('ativo', 'vendido', 'retirado', 'suspenso')),
    criado_em                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (banco, codigo)
);

CREATE INDEX IF NOT EXISTS idx_imoveis_leilao_cidade_uf ON imoveis_leilao (uf, cidade);

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
    data_leilao                 DATE,                      -- data do leilão/venda informada
    formas_pagamento            JSONB,                     -- formas aceitas pela CAIXA (lista)
    regras_despesas             TEXT,                      -- condomínio/tributos, copiado do site da CAIXA

    -- Localização e busca -----------------------------------------------------
    localizacao_alvo            TEXT,                      -- endereco_completo / rua_numero / rua / bairro / coordenada_informada / nao_localizado
    escopo_busca                TEXT,                      -- rua+bairro / rua+bairro+proximidade / proximidade / cidade
    anuncios_por_proximidade    INTEGER,                   -- trazidos pela busca por proximidade (até 1,5 km)

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
    lance_maximo                NUMERIC(14, 2),            -- maior lance com ROI de 30% (services/leilao.py)
    sobra                       NUMERIC(14, 2),            -- lance máximo − valor mínimo (negativa = falta p/ "Oportunidade")
    decisao                     TEXT,                      -- Oportunidade / Margem apertada / Descartar / Sem estimativa
    tempo_venda                 TEXT,
    alertas                     JSONB,                     -- sinais automáticos de atenção (services/alertas.py)

    -- Entrada do usuário e checagem do próprio anúncio (migração 003) ---------
    entrada_usuario             JSONB,                     -- tudo o que o formulário mandou (digitado e lido)
    checagem_anuncio_alvo       JSONB,                     -- anúncios com mais sinais de serem o próprio imóvel

    -- Verificações automáticas (migração 004) --------------------------------
    verificacoes                JSONB,                     -- {agente, verificacao, esperado, encontrado, ok} (services/verificacoes.py)

    -- Imóvel de leilão (migração 005) -------------------------------------------
    id_imovel_leilao            BIGINT REFERENCES imoveis_leilao (id),
    etapa_avaliada              SMALLINT,                  -- 1 ou 2 (Leilão SFI); NULL nas outras
    roi                         NUMERIC(10, 4),            -- ROI pagando o valor mínimo da etapa
    lance_limite_descarte       NUMERIC(14, 2)             -- acima dele, ROI < 15%: descartar
);

CREATE INDEX IF NOT EXISTS idx_execucoes_data_hora ON execucoes (data_hora DESC);
CREATE INDEX IF NOT EXISTS idx_execucoes_cidade_uf ON execucoes (uf, cidade);
CREATE INDEX IF NOT EXISTS idx_execucoes_decisao ON execucoes (decisao);
CREATE INDEX IF NOT EXISTS idx_execucoes_localizacao ON execucoes (localizacao_alvo);
CREATE INDEX IF NOT EXISTS idx_execucoes_imovel_leilao ON execucoes (id_imovel_leilao, data_hora DESC);


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


-- Etapa atual e encerramento: mesma regra de services/leilao.py (etapa_atual).
CREATE OR REPLACE VIEW vw_leiloes AS
WITH agora AS (
    SELECT (now() AT TIME ZONE 'America/Sao_Paulo') AS agora
),
etapas AS (
    SELECT i.*,
           CASE
               WHEN i.modalidade <> 'Leilão SFI' THEN NULL
               WHEN i.data_1_leilao IS NOT NULL AND a.agora <= i.data_1_leilao THEN 1
               WHEN i.data_2_leilao IS NOT NULL AND a.agora <= i.data_2_leilao THEN 2
               WHEN i.data_1_leilao IS NULL AND i.data_2_leilao IS NULL
                   THEN CASE WHEN i.valor_minimo_1 IS NOT NULL OR i.valor_minimo_2 IS NULL THEN 1 ELSE 2 END
               WHEN i.data_2_leilao IS NOT NULL THEN 2
               ELSE 1
           END AS etapa_atual,
           a.agora
    FROM imoveis_leilao i CROSS JOIN agora a
),
prazos AS (
    SELECT e.*,
           CASE e.etapa_atual WHEN 1 THEN e.data_1_leilao WHEN 2 THEN e.data_2_leilao
                ELSE e.data_encerramento END                                   AS encerramento,
           CASE e.etapa_atual WHEN 1 THEN e.valor_minimo_1 WHEN 2 THEN e.valor_minimo_2
                ELSE e.valor_minimo END                                        AS valor_minimo_atual
    FROM etapas e
)
SELECT p.id, p.banco, p.codigo, p.numero_imovel, p.link, p.modalidade,
       p.tipo, p.endereco, p.bairro, p.cidade, p.uf,
       p.etapa_atual, p.encerramento, p.valor_minimo_atual, p.valor_avaliacao,
       (p.encerramento IS NOT NULL AND p.agora > p.encerramento)                  AS encerrado,
       (p.situacao = 'ativo' AND NOT (p.encerramento IS NOT NULL AND p.agora > p.encerramento)) AS ativo,
       p.situacao, p.gravame, p.gravame_texto, p.averbacao_leiloes_negativos,
       u.id_execucao        AS ultima_execucao,
       u.data_hora          AS avaliado_em,
       u.decisao,
       u.roi,
       u.lance_maximo,
       u.lance_limite_descarte,
       u.liquidez,
       u.etapa_avaliada,
       -- A última avaliação foi feita em outra etapa (ex.: no 1º leilão, e o 1º já
       -- passou): o ROI gravado não vale para o valor mínimo atual.
       (p.etapa_atual IS DISTINCT FROM u.etapa_avaliada AND u.id_execucao IS NOT NULL) AS etapa_mudou
FROM prazos p
LEFT JOIN LATERAL (
    SELECT e.id_execucao, e.data_hora, e.decisao, e.roi, e.lance_maximo, e.lance_limite_descarte,
           e.liquidez, e.etapa_avaliada
    FROM execucoes e
    WHERE e.id_imovel_leilao = p.id
    ORDER BY e.data_hora DESC
    LIMIT 1
) u ON TRUE;

CREATE OR REPLACE VIEW vw_leiloes_ativos AS
SELECT * FROM vw_leiloes WHERE ativo
ORDER BY encerramento NULLS LAST;
