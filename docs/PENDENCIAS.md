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

- [ ] **Socorro do Agente 5 com o alvo localizado (levar ao professor; não mexer
  antes da decisão sobre raio e socorro).** Quando a zona não confirma nenhum
  comparável, o Agente 5 usa todo o Cluster A do Agente 2 ("sem validação"),
  inclusive anúncios que a zona classificou como FORA do raio. Deveria valer só
  quando o alvo não foi localizado. Ex.: Cuiabá (10/10/2026) — alvo localizado,
  raio 350 m, 0 no círculo, 60 comparáveis pelo socorro, decisão "Descartar";
  enquanto Curitiba com 2 no círculo deu "Sem estimativa".
- [ ] **Agente 4 tem geocodificação própria** (`agents/infra_evaluator.py`,
  `_geocodificar`) sem a checagem de precisão do Agente 2. Usada só para buscar
  pontos de interesse perto do imóvel; não afeta o valor. Avaliar se deve usar a
  mesma função.
- [ ] **Ligação com a decisão do raio (levar ao professor).** Se o professor escolher
  "ampliar o raio até ter 5 comparáveis", a busca por proximidade do Agente 1 já
  fornece os anúncios até 1,5 km do imóvel (`RAIO_PROXIMIDADE_M`); seria preciso só
  aumentar esse raio junto com o da zona.
- [ ] **Branch `busca-cidade-poucos-locais` guardado, sem merge.** Buscar a cidade
  inteira traz os anúncios mais recentes, não os mais próximos (Londrina/Aritana: 353
  anúncios, 0 casas no círculo, +114 s). Substituído pela busca por proximidade.

## Agente 3 — Analisador qualitativo (`agents/text_analyzer.py`)

- [ ] **Ordem dos provedores para comparáveis.** Hoje Groq → NVIDIA → Gemini. No
  teste: Groq recusou 7 de 11 por limite de uso (429, modelo qwen3.8-27b); NVIDIA
  respondeu texto em vez de JSON em 3 de 6; Gemini acertou 4 de 4. Sugestão:
  Groq → Gemini → NVIDIA (~1 min a menos). Atenção ao limite por minuto do Gemini
  gratuito.

## Resolvido

- **Busca por proximidade no Agente 1** (branch `busca-proximidade`): com o imóvel
  localizado com precisão de rua ou bairro, a consulta ao Athena traz também os
  anúncios a até 1,5 km (caixa de lat/lon + distância), ordenados por rua → bairro →
  mais próximos. Marcados `origem_busca="proximidade"`: só entram se o círculo da
  zona confirmar (nunca pelo fallback da zona nem pelo socorro do Agente 5).
  Londrina/Aritana (casa típica, raio 450 m): antes 2 anúncios e sem amostra; depois
  9 casas e 57 terrenos no círculo, status ok, R$ 498.104. Tempo total 201 s →
  507 s (o Agente 3 passou a ter comparáveis para analisar: 14 s → 218 s).
  Curitiba/Cajuru: 0 anúncios por proximidade, mesmos 320 anúncios (Agente 1
  ~5–10 s mais lento). Itaboraí: sem mudança (imóvel sem localização).

- **IA do Agente 2 recusando por bairro** (branch `comparaveis-sem-bairro`): o pedido
  de comparabilidade não leva mais bairro/rua e diz que a localização é julgada
  depois pela zona. Itaboraí (casas da cidade inteira, 18 julgadas pela IA): antes
  0 aprovadas e 18 recusas citando bairro (2 rodadas); depois 14 e 11 aprovadas,
  nenhuma recusa por bairro. Curitiba/Cajuru: aprovadas 50 → 44 (variação da IA);
  zona igual (6 casas e 4 terrenos confirmados); tempo do Agente 2 90 s → 115 s e
  zona 24 s → 22 s (variam com o provedor da IA).

- **Localização imprecisa tratada como exata** (branch `geocodificacao-precisa`):
  `_geocodificar` recusa resultados com precisão de cidade (Nominatim
  addresstype/type city, town, municipality…; Google types locality/
  administrative_area_level_* ou APPROXIMATE com partial_match) e segue para a
  próxima tentativa (rua → bairro). A tela usa a mesma função para o imóvel; sem
  precisão de rua ou bairro, segue "sem localização" com aviso. Anúncios a menos de
  300 m do centro da cidade (Nominatim ou Google) ou com a mesma coordenada em 3+
  anúncios de bairros diferentes viram `zona_nao_verificada` — só quando a
  coordenada veio pronta do portal (`coordenadas_athena`); a da nossa
  geocodificação não é rebaixada. O nível gravado é o achado (rua_numero/rua/
  bairro), não o pesquisado. Centro de Curitiba (apartamento): 1 de 31 anúncios
  rebaixado (coordenada do portal perto do centro). Itaboraí: o imóvel
  estava no centro da cidade como "endereço completo" e terrenos entravam a 0–53 m.
  Curitiba/Cajuru: classificação idêntica antes e depois.

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
