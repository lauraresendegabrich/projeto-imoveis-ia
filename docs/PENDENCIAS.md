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

- [ ] **Socorro com o imóvel localizado: usar só os parecidos mais próximos.** Hoje,
  quando a zona não confirma nenhum comparável, o socorro do Agente 5 usa todos os
  parecidos (Cluster A). Proposta: com o imóvel localizado, usar só os mais próximos
  (ex.: os 5 mais perto, até 3 km), em vez de todos.
- [ ] **Imóvel não localizado e sem anúncios no bairro.** O socorro usa parecidos da
  cidade toda, sem verificar distância. Aceitar com aviso (como hoje) ou dar
  "sem estimativa"?
- [ ] **Mínimo de terrenos incoerente no Agente 5** (`agents/price_liquidity.py`).
  Casa com área de terreno informada: com 0 terrenos na zona, o valor sai pelo m²
  das casas (sem separar o terreno); com 1 a 4 terrenos, o terreno é separado e,
  por não chegar a 5, a avaliação dá "sem estimativa", mesmo com muitas casas.
  Ou seja, achar poucos terrenos dá resultado pior do que não achar nenhum. A
  busca por proximidade diminui o caso (traz mais terrenos), mas não elimina.
  Proposta: com menos de 5 terrenos, não separar o terreno (calcular como no caso
  de 0 terrenos). Não alterado: muda o método.
- [ ] **Confirmar o ID 4 dos testes** (1 comparável e valor exibido): provavelmente
  rodou em 19/09 antes do commit `e2c843e`, que criou a regra dos 3 comparáveis.
  Rodar os IDs 4 e 5 de novo para confirmar.

## Infraestrutura e segurança

- [ ] **Rodar a migração `db/migracoes/002_localizacao_e_dados_do_leilao.sql` no
  Neon ANTES de publicar o código que grava as colunas novas** (sem ela, nenhuma
  avaliação é gravada). Confirmar também que a `001` já foi rodada.
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
  par — portal mais confiável, a menor ou a média; (2) alerta quando as áreas do
  par diferirem mais de 5%. Escolhido: menor área + alerta. A menor área NÃO é a
  opção conservadora (com o mesmo preço, dá m² maior e lance maior); foi escolhida
  porque costuma ser a certa: o erro mais comum é o portal mostrar a área do
  terreno no lugar da construída. Não há dados para ranquear portais, e a média
  mistura o valor certo com o errado.

## Agente 2 — Zona homogênea (`agents/comparables.py`)

- [ ] **Socorro do Agente 5 com o alvo localizado (levar ao professor; não mexer
  antes da decisão sobre raio e socorro).** Quando a zona não confirma nenhum
  comparável, o Agente 5 usa todo o Cluster A do Agente 2 ("sem validação"),
  inclusive anúncios que a zona classificou como FORA do raio. Deveria valer só
  quando o alvo não foi localizado. Ex.: Cuiabá (10/10/2026) — alvo localizado,
  raio 350 m, 0 no círculo, 60 comparáveis pelo socorro, decisão "Descartar";
  enquanto Curitiba com 2 no círculo deu "Sem estimativa".
- [ ] **Trava `ORIGENS_SO_COM_CIRCULO` inclui "cidade" sem efeito hoje**
  (`agents/comparables.py`). Ela garante que anúncios trazidos de fora da rua/bairro
  só entram com o círculo confirmando. "proximidade" é marcado pelo Agente 1; "cidade"
  ficou para a busca na cidade inteira (branch `busca-cidade-poucos-locais`, sem
  merge), então hoje o Agente 1 nunca marca `origem_busca="cidade"` e essa parte da
  trava não tem efeito. Os anúncios da busca antiga na cidade (sem nenhum na
  rua/bairro) não são marcados e podem entrar pelo fallback e pelo socorro.
- [ ] **Agente 4 tem geocodificação própria** (`agents/infra_evaluator.py`,
  `_geocodificar`) sem a checagem de precisão do Agente 2. Usada só para buscar
  pontos de interesse perto do imóvel; não afeta o valor. Avaliar se deve usar a
  mesma função.
- [ ] **Prioridade baixa. Apify sem contar a proximidade.** O Agente 1 aciona a coleta
  complementar do Apify quando a rua e o bairro têm menos de 10 anúncios, sem contar
  os que vieram por proximidade. Em Londrina/Aritana o Apify rodou mesmo com 319
  anúncios por proximidade. Melhoria: contar também os por proximidade até ~500 m
  antes de acionar o Apify, para não rodar à toa quando a proximidade já trouxe amostra.
- [ ] **Decisão registrada: a proximidade fica dentro da mesma cidade.** A consulta por
  proximidade mantém o filtro de cidade e estado, então vizinhos de outro município
  (ex.: imóvel na divisa) não entram, mesmo a menos de 1,5 km. Decisão conservadora
  (17/10/2026); rever se aparecerem casos de divisa.
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

- **Comparáveis por fallback contam para o mínimo de 5.** Decisão do professor
  (17/10/2026): manter; aviso com números na tela, no laudo e nos logs. A tela
  mostra, abaixo do valor e no bloco do leilão, quantos comparáveis foram
  confirmados perto do imóvel e quantos estão com a distância não verificada
  (`services/leilao.py`, `texto_aviso_zona`); a tabela dos imóveis usados mostra
  "Confirmado na zona" ou "Distância não verificada"; o Agente 5 e o resumo da
  execução registram a contagem no log. No Excel e no alerta, "Fora da zona
  (fallback)" virou "Distância não verificada" (não estão comprovadamente longe).
- **Raio da zona muda entre rodadas do mesmo imóvel.** Decisão do professor
  (17/10/2026): manter o raio escolhido pela IA a cada avaliação. A variação entre
  rodadas é uma limitação conhecida; o raio usado fica registrado no banco
  (`raio_zona_m`) e no Excel.

- **Banco e Excel passaram a registrar a localização e os dados do leilão** (branch
  `registro-localizacao-leilao`, migração `002`). Novas colunas em `execucoes`:
  `localizacao_alvo` (endereco_completo / rua_numero / rua / bairro /
  coordenada_informada / nao_localizado), `escopo_busca`, `anuncios_por_proximidade`,
  `data_leilao`, `formas_pagamento` e `regras_despesas`. Antes não dava para contar
  quantas avaliações ficaram sem localização (o alerta "fora da zona" junta esse caso
  com "nenhum comparável confirmado"). Data, formas de pagamento e regras de despesas
  entram por campos novos do formulário e só são registradas (não entram no cálculo).

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
