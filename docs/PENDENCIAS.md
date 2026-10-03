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

- [ ] **Chamada à NVIDIA sem limite de tempo (causa principal da lentidão).** Em
  `_analisar_imovel_vision_nvidia`, o cliente `OpenAI(...)` é criado sem `timeout`
  e sem `max_retries`: o padrão da biblioteca espera até 10 min e repete 2 vezes.
  No teste, 2 chamadas travaram ~5 min cada até o servidor devolver 504
  (~10,5 min no total). Os Agentes 2 e 4 já usam
  `timeout=httpx.Timeout(30/60, connect=10), max_retries=0`
  (`comparables.py`, `infra_evaluator.py`). Correção: aplicar o mesmo padrão.
  Ganho estimado: Agente 3 de ~14,5 para ~5 min.
- [ ] **Nota do imóvel-alvo sem evidência.** Alvo sem fotos e com a descrição
  gerada pela interface (`descricao_gerada=True`, ex.: "Apartamento com 140m²,
  4 quartos...") → Gemini e Groq respondem "inconclusivo" (correto), mas o
  roteamento insiste na NVIDIA, que devolve "bom / padrão médio" sem base. Daí
  saem o score 0,67 "favorável", a frase "seu imóvel está abaixo da média da
  vizinhança" e a entrada do tempo de venda. Sugestão: nesse caso aplicar direto a
  regra "sem evidência = neutro (0,50)", sem chamar LLM. Muda a nota exibida e o
  tempo de venda estimado — decidir antes de mudar.
- [ ] **Ordem dos provedores para comparáveis.** Hoje Groq → NVIDIA → Gemini. No
  teste: Groq recusou 7 de 11 por limite de uso (429, modelo qwen3.8-27b); NVIDIA
  respondeu texto em vez de JSON em 3 de 6; Gemini acertou 4 de 4. Sugestão:
  Groq → Gemini → NVIDIA (~1 min a menos). Atenção ao limite por minuto do Gemini
  gratuito.
