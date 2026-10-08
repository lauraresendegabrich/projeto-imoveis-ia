-- =============================================================================
-- 001 — Alertas automáticos no lugar da conferência manual
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon, ANTES de colocar no ar o código que
-- grava a coluna "alertas" (sem ela, a gravação falha e as avaliações deixam de
-- ser registradas; o app continua funcionando). Seguro para rodar de novo.
--
-- alertas    : sinais automáticos de atenção de cada avaliação (services/alertas.py)
-- removidas  : faz_sentido e observacao (ninguém fará conferência manual por enquanto)
-- =============================================================================

ALTER TABLE execucoes ADD COLUMN IF NOT EXISTS alertas JSONB;

ALTER TABLE execucoes
    DROP COLUMN IF EXISTS faz_sentido,
    DROP COLUMN IF EXISTS observacao;
