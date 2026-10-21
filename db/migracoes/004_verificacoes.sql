-- =============================================================================
-- 004 — Verificações automáticas de cada execução
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon, ANTES de colocar no ar o código que
-- grava esta coluna (sem ela, a gravação falha e as avaliações deixam de ser
-- registradas; o app continua funcionando). Seguro para rodar de novo.
--
-- verificacoes : lista das verificações automáticas feitas ao final da execução
--                (services/verificacoes.py), uma por regra:
--                {agente, verificacao, esperado, encontrado, ok}
--                ok = true (passou), false (falhou) ou null (não verificável:
--                o agente não grava o dado).
-- =============================================================================

ALTER TABLE execucoes
    ADD COLUMN IF NOT EXISTS verificacoes JSONB;
