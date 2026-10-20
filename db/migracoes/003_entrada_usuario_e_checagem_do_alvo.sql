-- =============================================================================
-- 003 — Entrada completa do formulário e checagem do próprio anúncio
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon, ANTES de colocar no ar o código que
-- grava estas colunas (sem elas, a gravação falha e as avaliações deixam de ser
-- registradas; o app continua funcionando). Seguro para rodar de novo.
--
-- entrada_usuario       : tudo o que o formulário mandou, como foi digitado e
--                         como foi lido (endereço, área, quartos, banheiros, vagas,
--                         preço, descrição completa, fotos, dados do leilão).
-- checagem_anuncio_alvo : resultado da checagem "é o anúncio do próprio imóvel?"
--                         do Agente 2 — quantos foram testados, confirmados e
--                         suspeitos, e os 10 com mais sinais (resultado, pontuação,
--                         sinais, portal, preço, área, bairro, link).
-- =============================================================================

ALTER TABLE execucoes
    ADD COLUMN IF NOT EXISTS entrada_usuario       JSONB,
    ADD COLUMN IF NOT EXISTS checagem_anuncio_alvo JSONB;
