-- =============================================================================
-- 005 — Imóveis de leilão (uma linha por imóvel) e leilões ativos
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon, ANTES de colocar no ar o código que
-- grava estas tabelas/colunas (sem elas, a gravação falha e as avaliações deixam
-- de ser registradas; o app continua funcionando). Seguro para rodar de novo.
--
-- imoveis_leilao : um imóvel da CAIXA, com a modalidade, as datas e os valores do
--                  site. Vive mais que uma avaliação: é avaliado várias vezes, as
--                  datas mudam e ele deixa de estar ativo sem ninguém rodar nada.
--                  Chave: banco + codigo (só os dígitos do número do imóvel, sem
--                  zeros à esquerda: "855552271653-1" e o link "...=8555522716531"
--                  dão o mesmo código).
-- execucoes      : passa a apontar para o imóvel (id_imovel_leilao) e guarda a
--                  etapa avaliada, o ROI e o lance acima do qual descarta.
-- vw_leiloes     : cada imóvel com a etapa atual, o próximo encerramento, se está
--                  ativo e a última avaliação. vw_leiloes_ativos = só os ativos.
--
-- Datas/horas: horário de Brasília, como aparecem no site (TIMESTAMP sem fuso).
-- Data sem hora vale até o fim do dia (o app grava 23:59:59).
-- "Ativo" é calculado (situação manual 'ativo' e prazo não encerrado), não gravado.
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

ALTER TABLE execucoes
    ADD COLUMN IF NOT EXISTS id_imovel_leilao       BIGINT REFERENCES imoveis_leilao (id),
    ADD COLUMN IF NOT EXISTS etapa_avaliada         SMALLINT,          -- 1 ou 2 (Leilão SFI); NULL nas outras
    ADD COLUMN IF NOT EXISTS roi                    NUMERIC(10, 4),    -- ROI pagando o valor mínimo da etapa
    ADD COLUMN IF NOT EXISTS lance_limite_descarte  NUMERIC(14, 2);    -- acima dele, ROI < 15%: descartar

CREATE INDEX IF NOT EXISTS idx_execucoes_imovel_leilao ON execucoes (id_imovel_leilao, data_hora DESC);


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
