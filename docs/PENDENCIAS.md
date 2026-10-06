# Pendências

Itens identificados e ainda não resolvidos. Ao resolver um item, remova-o daqui
(ou mova para o histórico no fim do arquivo) e cite o commit.

## Migração para a tabela `anuncios` (branch `migracao-tabela-anuncios`)

- [ ] **Não unir ao `main` antes de as coletas terminarem.** O push no `main`
  atualiza o app publicado no Streamlit Cloud automaticamente. Em 03/10/2026:
  ImovelWeb sem SC, SP, RO, RR, SE, TO; Chaves na Mão sem SP (6 partes), RJ, PR,
  RS, SC, MS. A aplicação usa sempre a coleta mais recente de cada portal; com a
  coleta incompleta, esses estados ficam sem anúncios desses portais.
  Decidido esperar e subir tudo junto. No dia:
  1. `.venv/Scripts/python.exe -m tools.atualizar_particoes`
  2. avaliação completa de teste (de preferência em SP)
  3. merge de `migracao-tabela-anuncios` no `main`
- [ ] **Registrar estados novos no Athena** quando as coletas avançarem:
  `.venv/Scripts/python.exe -m tools.atualizar_particoes` (só roda
  `MSCK REPAIR TABLE`). Ideal: a coleta (repositório scraper-imoveis) rodar isso
  ao fim de cada estado.
- [ ] **Avaliação completa de casa pela interface.** Só a coleta e a deduplicação de
  casa foram testadas com dados reais (Santa Mônica/BH e Taquaral/Campinas).

## Agente 3 — Analisador qualitativo (`agents/text_analyzer.py`)

Investigado em 03/10/2026 numa avaliação de apartamento no Sion (BH): o Agente 3
levou ~14,5 min de uma avaliação de ~19 min (o Agente 4, em paralelo, levou 22 s).

- [ ] **Ordem dos provedores para comparáveis.** Hoje Groq → NVIDIA → Gemini. No
  teste: Groq recusou 7 de 11 por limite de uso (429, modelo qwen3.8-27b); NVIDIA
  respondeu texto em vez de JSON em 3 de 6; Gemini acertou 4 de 4. Sugestão:
  Groq → Gemini → NVIDIA (~1 min a menos). Atenção ao limite por minuto do Gemini
  gratuito.

## Resolvido

- **Agente 3: chamada à NVIDIA sem limite de tempo** — agora 60 s e sem repetir,
  como no Ag2/Ag4.
- **Agente 3: nota do imóvel-alvo sem evidência** — sem fotos e com descrição
  gerada pela interface, aplica a nota neutra (0,50) sem chamar LLM; a tela avisa
  que não dá para comparar com a vizinhança em vez de dizer "abaixo da média".
  Teste (Sion, 06/10/2026): Agentes 3+4 de 868 s para 186 s; avaliação de ~19 min
  para 7,2 min.
