-- =============================================================================
-- 006 — Resultado completo de cada execução (tela "Ver avaliação completa")
-- =============================================================================
-- Rodar MANUALMENTE no SQL Editor do Neon, ANTES de colocar no ar o código que
-- grava esta coluna (sem ela, a gravação falha e as avaliações deixam de ser
-- registradas; o app continua funcionando). Seguro para rodar de novo.
--
-- resultado_completo : o resultado dos 5 agentes, como a tela de resultado o usa,
--                      sem fotos e descrições dos anúncios
--                      (services/detalhe_leilao.py):
--                      {versao, resultado, tela}
--                      A página "Leilões ativos" remonta com ele a mesma tela de
--                      quando a avaliação acaba de rodar. Avaliações antigas ficam
--                      com NULL (o detalhe mostra só o que as outras colunas têm).
-- =============================================================================

ALTER TABLE execucoes
    ADD COLUMN IF NOT EXISTS resultado_completo JSONB;
