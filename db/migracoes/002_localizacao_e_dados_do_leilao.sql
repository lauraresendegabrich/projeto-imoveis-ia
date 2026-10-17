-- =============================================================================
-- 002 — Localização do imóvel, origem dos anúncios e dados do leilão
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon, ANTES de colocar no ar o código que
-- grava estas colunas (sem elas, a gravação falha e as avaliações deixam de ser
-- registradas; o app continua funcionando). Seguro para rodar de novo.
--
-- localizacao_alvo         : precisão com que o imóvel foi achado no mapa
--                            (endereco_completo / rua_numero / rua / bairro /
--                            coordenada_informada / nao_localizado). Permite contar
--                            quantas avaliações foram feitas sem localização.
-- escopo_busca             : onde o Agente 1 buscou os anúncios (rua+bairro,
--                            rua+bairro+proximidade, proximidade, cidade)
-- anuncios_por_proximidade : anúncios trazidos pela busca por proximidade (até 1,5 km)
-- data_leilao              : data do leilão/venda informada no formulário
-- formas_pagamento         : formas aceitas pela CAIXA (lista)
-- regras_despesas          : regras de despesas (condomínio, tributos) copiadas da CAIXA
-- =============================================================================

ALTER TABLE execucoes
    ADD COLUMN IF NOT EXISTS localizacao_alvo         TEXT,
    ADD COLUMN IF NOT EXISTS escopo_busca             TEXT,
    ADD COLUMN IF NOT EXISTS anuncios_por_proximidade INTEGER,
    ADD COLUMN IF NOT EXISTS data_leilao              DATE,
    ADD COLUMN IF NOT EXISTS formas_pagamento         JSONB,
    ADD COLUMN IF NOT EXISTS regras_despesas          TEXT;

CREATE INDEX IF NOT EXISTS idx_execucoes_localizacao ON execucoes (localizacao_alvo);
