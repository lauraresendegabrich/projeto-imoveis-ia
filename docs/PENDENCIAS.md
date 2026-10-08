# Pendências

Itens identificados e ainda não resolvidos. Ao resolver um item, mova-o para
"Resolvido" no fim do arquivo e cite o commit.

## Coletas e base de anúncios

- [ ] **ImovelWeb em SP ainda coletando** (07/10/2026: 24 estados prontos, só SP em
  andamento; Chaves na Mão completo). A migração já está no `main` e usa o que
  existe; quando SP terminar, registrar as pastas novas no Athena:
  `.venv/Scripts/python.exe -m tools.atualizar_particoes` (só roda
  `MSCK REPAIR TABLE`). Ideal: a coleta (repositório scraper-imoveis) rodar isso
  ao fim de cada estado.

## Regras para levar ao professor

- [ ] **Comparáveis por fallback contam para o mínimo de 3.** Quando menos de 3
  comparáveis são confirmados na zona homogênea, os "zona não verificada" são
  anexados e o Agente 5 os conta normalmente (ex.: ID 20 dos testes). Também
  contam os do Cluster A do Agente 2 quando o alvo não é geocodificado. Não foi
  alterado; o bloco de leilão avisa "Valor baseado em imóveis fora da região
  exata" nesses casos.
- [ ] **Confirmar o ID 4 dos testes** (1 comparável e valor exibido): provavelmente
  rodou em 19/09 antes do commit `e2c843e`, que criou a regra dos 3 comparáveis.
  Rodar os IDs 4 e 5 de novo para confirmar.

## Infraestrutura e segurança

- [ ] **`DATABASE_URL` nos Secrets do Streamlit Cloud** (Settings → Secrets). Sem
  ela o app publicado funciona, mas não grava as avaliações no banco.
- [ ] **Trocar a chave do Qwen e a senha do banco Neon**, que circularam em
  conversa; atualizar `.env` e Secrets.
- [ ] **Qwen (Colab) lento para tarefas reais.** Em 06/10/2026 respondia "OK" em
  3 s, mas nenhuma tarefa real terminou dentro do limite (60–90 s) e os pedidos
  abandonados ficaram em fila no Colab, travando-o; a avaliação do Sion foi de
  7,2 para 13,2 min. Enquanto não houver solução, deixar `QWEN_API_URL`/
  `QWEN_API_KEY` comentadas no `.env`. Opções: checar o Colab no início da
  avaliação e pular o Qwen se ele demorar; fazer o notebook cancelar pedidos
  abandonados; GPU mais forte.

## Agente 3 — Analisador qualitativo (`agents/text_analyzer.py`)

- [ ] **Ordem dos provedores para comparáveis.** Hoje Groq → NVIDIA → Gemini. No
  teste: Groq recusou 7 de 11 por limite de uso (429, modelo qwen3.8-27b); NVIDIA
  respondeu texto em vez de JSON em 3 de 6; Gemini acertou 4 de 4. Sugestão:
  Groq → Gemini → NVIDIA (~1 min a menos). Atenção ao limite por minuto do Gemini
  gratuito.

## Resolvido

- **Migração para a tabela `anuncios` (4 portais) no `main`** — 07/10/2026, com o
  ImovelWeb SP ainda incompleto (decisão da usuária).
- **Situação C: agentes usando arquivos de uma avaliação anterior** — `id_execucao`
  em todos os JSONs (`agents/execucao.py`); sem a zona desta avaliação, o Agente 5
  devolve `sem_amostra` com mensagem específica. Commits `7ad69c6`, `56b58e6`.
- **Tarefa 1 — avaliação de leilão CAIXA** (`services/leilao.py`) — commit `31c904a`.
- **Tarefa 2 — gravação de cada avaliação no Neon** (`services/banco.py`,
  `db/schema.sql`, guia em `docs/BANCO.md`).
- **Agente 5 listava como "usados" anúncios cortados pela faixa de sanidade de
  R$/m²** — agora separa usados e descartados; o valor calculado não mudou.
- **Avaliação completa de casa pela interface** — Santa Mônica/BH, 03/10/2026.
- **Agente 3: chamada à NVIDIA sem limite de tempo** — agora 60 s e sem repetir,
  como no Ag2/Ag4.
- **Agente 3: nota do imóvel-alvo sem evidência** — sem fotos e com descrição
  gerada pela interface, aplica a nota neutra (0,50) sem chamar LLM; a tela avisa
  que não dá para comparar com a vizinhança em vez de dizer "abaixo da média".
  Teste (Sion, 06/10/2026): Agentes 3+4 de 868 s para 186 s; avaliação de ~19 min
  para 7,2 min.
