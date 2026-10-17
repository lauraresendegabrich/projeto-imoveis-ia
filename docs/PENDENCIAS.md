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

- [ ] **Comparáveis por fallback contam para o mínimo de 5** (era 3 até 17/10/2026).
  Quando menos de 5 comparáveis (ou terrenos) são confirmados na zona homogênea, os "zona não verificada" são
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

## Agente 1 — Repetidos entre portais (`agents/identidade.py`)

- [x] **Resolvido em 17/10/2026: menor área + alerta `area_diferente_entre_portais`.** Área do par juntado dependia do anúncio que fica. Ao
  juntar o mesmo imóvel de dois portais, fica o anúncio mais completo (mais campos
  preenchidos) com a área dele, sem comparar com a do outro. Curitiba/Cajuru
  (10/10/2026): 6 de 123 pares tinham área mais de 2% diferente, todos com mesmo
  código e mesmo preço. Em 3 o outro portal mostrou a área do terreno (ex.: VivaReal
  80 m² × Chaves na Mão 110 m², terreno 110) e ficou a área certa; em 3 não dá para
  saber (R$ 660.000: 117 × 127 m², e o link do VivaReal diz 127; R$ 699.000: 117 ×
  109 m²; R$ 2.290.000: 600 × 506 m²). Saídas possíveis: (1) regra para a área do
  par — portal mais confiável, a menor (mais conservadora) ou a média; (2) alerta
  quando as áreas do par diferirem mais de 5%. Recomendação: menor área + alerta
  (sem dados para ranquear portais; a média mistura o valor certo com o errado).

## Agente 2 — Zona homogênea (`agents/comparables.py`)

- [ ] **Raio da zona muda entre rodadas do mesmo imóvel.** Quem escolhe o raio é a
  IA de visão olhando a imagem de satélite, e ela não responde igual toda vez. Teste
  de 10/10/2026: Curitiba/Cajuru (Rua Raul de Oliveira) saiu com 450 m e, na rodada
  seguinte, 350 m. Os anúncios disponíveis eram os mesmos, mas a amostra caiu de 4
  para 2 casas e a decisão foi de "Não descartar" (sobra R$ 207 mil) para "Sem
  estimativa". São José do Rio Preto variou de 450 para 400 m. Com poucos anúncios
  na região, 100 m a menos derrubam a amostra abaixo do mínimo (hoje 5). Levar ao
  professor; opções: fixar o raio, usar a média de algumas leituras, ou guardar o
  raio por endereço. Não mexer sem decisão (fora do escopo atual).

## Agente 3 — Analisador qualitativo (`agents/text_analyzer.py`)

- [ ] **Ordem dos provedores para comparáveis.** Hoje Groq → NVIDIA → Gemini. No
  teste: Groq recusou 7 de 11 por limite de uso (429, modelo qwen3.8-27b); NVIDIA
  respondeu texto em vez de JSON em 3 de 6; Gemini acertou 4 de 4. Sugestão:
  Groq → Gemini → NVIDIA (~1 min a menos). Atenção ao limite por minuto do Gemini
  gratuito.

## Resolvido

- **Mínimo de comparáveis passou de 3 para 5** (17/10/2026, decisão da usuária):
  - Agente 5 (`MIN_AMOSTRAS_CONFIAVEL = 5`): menos de 5 casas/apartamentos, ou menos
    de 5 terrenos quando a casa separa o terreno → "Sem estimativa".
  - Casa sem nenhum terreno na zona (ou sem área de terreno informada) continua
    calculando pelo preço/m² total das casas, e só exige 5 casas.
  - Agente 2 (`MIN_CONFIRMADOS_ZONA = 5`): com menos de 5 confirmados na zona,
    anexa os "zona não verificada" (fallback). Terrenos agora seguem a mesma regra
    (antes: só quando nenhum terreno era confirmado).
  - Alerta "poucos comparáveis/terrenos" passou de 3–4 para 5–6.

- **Apartamento contado duas vezes na média do Agente 5** — a planilha junta as
  colunas F e G (`MÉDIA.INTERNA($F$38:$G$57)`), que para apartamento/sala são
  iguais. Com 3, 6, 7, 10, 11, 14 ou 15 comparáveis isso mudava o valor (BH/Floresta,
  6 aptos: R$ 620.394 → R$ 623.600). Não era intencional (confirmado em
  17/10/2026): para apartamento/sala o código usa uma série só. Casa não muda.
  Testes em `tests/test_calculo_ag5.py`.

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
