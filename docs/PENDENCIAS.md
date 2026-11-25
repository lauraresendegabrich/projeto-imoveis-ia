# Pendências

Itens identificados e ainda não resolvidos. Ao resolver um item, mova-o para
"Resolvido" no fim do arquivo e cite o commit.

## Coletas e base de anúncios

## Regras para levar ao professor

- [ ] **Confirmar o ID 4 dos testes** (1 comparável e valor exibido): provavelmente
  rodou em 19/09 antes do commit `e2c843e`, que criou a regra dos 3 comparáveis.
  Rodar os IDs 4 e 5 de novo para confirmar.

Questões de método do lote de 33 imóveis da CAIXA (nov/2026). **Não mudar o cálculo
nestes pontos sem a resposta do professor.**

- [ ] **Separação do terreno superavalia lote grande.** Em Estância Velha, o sistema deu
  R$ 1,02 mi, contra R$ 507 mil da CAIXA. Houve casos parecidos em Cambé e Gravataí. Em
  Guaíba (condomínio), deu R$ 1,97 mi, contra R$ 1,63 mi sem separar. O filtro de área dos
  terrenos (1/3 a 3×) e o "mesmo m² no desconto e na soma" foram testados em 03/11/2026 e
  quase não mudam o resultado.
- [ ] **Método evolutivo ou aceitar menos de 5 comparáveis** nas cidades com poucos
  anúncios (General Câmara e Gravataí ficaram sem estimativa).
- [ ] **Imóvel em construção ou inacabado** (Guaíba, 19/33): o sistema avalia como casa
  pronta. O registro `9692b705` ficou como está até a resposta.
- [ ] **Mistura das séries de m²**, terrenos com preço de casa ou condomínio na amostra e
  "alto padrão".

Pontos de atenção do teste do Leilão SFI (10 imóveis, nov/2026; planilha
`Testes_Leilao_SFI.xlsx`, fora do repositório):

- [ ] **Comparáveis diferentes do imóvel** (uma das duas causas principais).
  - Padrão ou idade diferentes: Campina da Barra, Colombo e Soledade.
  - Casas maiores: Cambé.
  - Imóveis muito fora do padrão: Campina Grande do Sul.
  - A nota do Agente 3 só afeta a liquidez, não o valor. O valor sai de R$ 18 mil a
    R$ 134 mil maior.
- [ ] **Terreno avaliado com lotes diferentes do imóvel** (a outra causa principal). O
  R$/m² vem de lotes maiores, comerciais, de avenida ou de outros bairros, porque o raio
  dos terrenos chegou a 675–1.500 m.
  - Em casas pequenas, geminadas ou de condomínio, soma de R$ 35 mil a R$ 91 mil.
  - Em lote grande soma bem mais: R$ 581 mil em Astorga, com 1.400 m². Lote grande também
    não tem desconto por m².
- [ ] **Valor alto vira "Oportunidade" falsa no 2º leilão.** Isso é consequência dos dois
  itens acima. Com o lance do 2º bem abaixo da avaliação, um valor inflado vira Oportunidade.
  - Campina da Barra deu ROI de 44%, Cambé de 84% e Colombo de 62%. Com o valor real, o ROI
    fica entre 0% e 30%.
  - Astorga deu "Margem apertada", com ROI real negativo.
  - A conta não inclui reforma.
- [ ] **Cidade pequena:** Astorga teve só 6 casas (4 sem distância verificada), e Cruz
  Machado só 1 anúncio. Cruz Machado ficou sem estimativa, o que está certo. O Apify, que é
  a busca reserva, estava sem crédito.
- [ ] **2º leilão mais caro que o 1º:** em Soledade e South Dakota, o mínimo do 2º passa
  da avaliação (é a dívida do antigo dono). O sistema calcula certo e mostra o ROI das duas
  etapas. Fica para explicar na apresentação.

## Pipeline e repetibilidade

- [ ] **Levar ao professor: o mesmo imóvel muda de valor de uma rodada para outra por
  causa do raio da zona.** Detalhes e exemplos na seção "Para o professor: o raio da zona
  muda o valor", logo abaixo.

### Para o professor: o raio da zona muda o valor

**Resumo:** avaliando o mesmo imóvel duas vezes, com o mesmo código, o valor pode mudar
5% a 30%. A causa principal é o raio da zona homogênea. Ele começa com um número escolhido
pela IA, que varia um pouco de uma rodada para outra, e depois é ampliado em saltos de 50%.
Uma diferença pequena no começo (400 m ou 450 m) faz o raio parar em lugares bem
diferentes (1.012 m ou 1.350 m), e a amostra de comparáveis muda.

**Como o raio é escolhido hoje** (`agents/comparables.py`):

1. A IA de visão (Gemini, `temperature=0`) olha a imagem de satélite e sugere um raio
   "visualmente homogêneo". Valores de 100 m a 3.000 m são aceitos.
2. Conta quantos comparáveis parecidos (Cluster A do Agente 2) ficam dentro desse raio.
3. Se forem menos de 5, o raio cresce **×1,5 por passo** (`FATOR_AMPLIACAO_RAIO`) até ter
   5 ou chegar a 1.500 m (`RAIO_PROXIMIDADE_M`). Para na **primeira** vez que chega a 5.
   Casas e terrenos são ampliados separadamente.
4. Se ainda faltar, entram os do mesmo bairro até 2.500 m e, por último, os sem distância
   verificada (com aviso de confiança baixa).

Os passos dependem do número inicial:

| Raio da IA | Passos da ampliação |
|---|---|
| 350 m | 525 → 787 → 1.181 → 1.500 |
| 400 m | 600 → 900 → 1.350 → 1.500 |
| 450 m | 675 → 1.012 → 1.500 |

Mesmo com `temperature=0`, a IA não devolve sempre o mesmo número. Nos exemplos abaixo,
ela alternou entre 350, 400 e 450 m para o mesmo endereço.

**Exemplos reais (mesmo imóvel, mesmo código de cálculo):**

| Imóvel | Rodada | Raio da IA | Raio final | Casas usadas | Terrenos usados | Valor |
|---|---|---|---|---|---|---|
| Arapongas, Jd. Interlagos (casa 70 m², terreno 128 m²) | 23/11, tela | 450 m | 1.012 m | 5 | 0 | R$ 299.122 |
| | 24/11, tela | 400 m | 1.350 m | 11 | 8 | R$ 314.244 (+5%) |
| Alvorada do Sul, Jd. Novo Ideal | 28/10 16:58 | 350 m | 1.500 m (terrenos 1.181 m) | 0 | 11 | sem estimativa |
| | 28/10 17:14 | 400 m | 1.500 m (terrenos 1.350 m) | 0 | 25 | sem estimativa |
| Palhoça, Praia do Sonho (Ens. Brito) | 20/10 22:16 | — | 1.500 m | 1 | 9 | R$ 1.200.000 (não confiável) |
| | 20/10 23:34 | — | 750 m | 4 | 11 | R$ 1.565.714 (não confiável, +30%) |

Em Palhoça as duas rodadas ficaram abaixo do mínimo de 5 (valor mostrado como não
confiável). O raio da IA não era gravado em outubro.

O que aconteceu em Arapongas, passo a passo:
- Em 23/11 a IA disse 450 m. Com 675 m ainda faltavam casas; com 1.012 m chegou a 5 e
  parou. A zona confirmou 5 terrenos em 675 m, mas o Agente 5 não usou nenhum (falta
  conferir por quê). Resultado: o valor saiu do m² total de 5 casas, sem separar o terreno.
- Em 24/11 a IA disse 400 m. Com 600 m e 900 m faltavam casas; o passo seguinte foi
  1.350 m, que pegou 11 casas de uma vez. Os terrenos foram até 900 m e entraram 8, um
  deles de R$ 2,3 milhões. Resultado: o valor saiu com o terreno separado.
- A diferença não veio da IA que escolhe os comparáveis nem das fotos. Veio de onde o raio
  parou.

**Onde a variação pesa mais:** com amostra grande, quase não muda (São José do Rio Preto,
outubro: 35 a 47 casas na zona, R$ 542 mil e R$ 548 mil). Pesa nas cidades pequenas e
bairros com poucos anúncios, que são justamente a maioria dos imóveis da CAIXA.

**Caminhos possíveis (para o professor escolher, nada foi mudado):**
1. **Raio fixo ou por faixas** (ex.: 500 m, 1 km, 1,5 km), sem a IA decidir o número.
   A IA de visão continuaria só como observação.
2. **Os N mais próximos:** em vez de raio, usar os 5 (ou 8, ou 10) comparáveis parecidos
   mais próximos do imóvel, a qualquer distância até um limite. A amostra fica sempre do
   mesmo tamanho.
3. **Passos menores na ampliação** (ex.: +100 m em vez de ×1,5), para o raio parar perto
   do mínimo necessário.
4. **Mínimo maior que 5** comparáveis, para que um imóvel a mais ou a menos pese menos.
5. **Repetir a escolha do raio** 3 vezes e usar a mediana.

Pergunta para ele: qual desses (ou outro) é o mais correto pelo método da planilha, e se a
variação de 5% entre rodadas é aceitável para o trabalho.

## Leilão e telas

- [ ] **Cronômetro dos leilões** (`app/cronometro.py`) usa `st.components.v1.html`. O
  Streamlit avisava que esse recurso seria removido depois de 01/06/2026. Conferir se o
  cronômetro ainda aparece e trocar pelo substituto indicado pelo Streamlit.
- [ ] **Botão "Salvar" dos cards** (grava a situação: ativo, vendido...). O texto sozinho
  confunde; sugestão: "Salvar situação".

## Infraestrutura e segurança

- [ ] **Trocar a chave do Qwen e a senha do banco Neon**, que circularam em
  conversa; atualizar `.env` e Secrets.

## Agente 1 — Repetidos entre portais (`agents/identidade.py`)

- [ ] **Anúncios repetidos não juntados (São Paulo, Jardim Consórcio, 21/10/2026).**
  - A verificação "Repetidos prováveis entre os usados" (⚠️; mesmo preço ≤0,5%, mesma
    área ≤2%, mesma rua, com ou sem número) encontrou 17 grupos nos 103 usados, com 49
    anúncios. Cada grupo devia contar 1 vez, então são 32 anúncios a mais na média.
  - 13 grupos (33 anúncios) têm números compatíveis (iguais ou sem número). 4 grupos (16
    anúncios) têm números diferentes na mesma rua (Pedro Rendon 08, 1, 101, 36): podem
    ser casas iguais de loteamento ou números inventados ("9999").
  - Decidir se o Agente 1 deve juntar esses casos e com qual regra.
- [ ] **O que ainda impede juntar os repetidos da Av. João Peixoto Viegas, 888 (21/10/2026).**
  Depois de `c5e157a`, os 9 anúncios a R$ 830.000 dessa rodada são 4 imóveis distintos.
  O que sobra:
  - Chaves na Mão 46815748 (KAZZA): número 800 (os outros, 888) e área trocada no link
    (203 no link, 135 no anúncio). Decisão da usuária: fica como está.
  - Chaves na Mão 47235519 (FOXTER, 203 m²): sem número e sem código em comum.
  - Chaves na Mão 46262870 (AM Imóveis): "Casa / Sobrado em Condomínio", sem área.
  - Efeito de `f0dbc29`: com o mesmo endereço e preço, áreas entre 2% e 10% também
    juntam (ex.: Av. João Batista Di Vitoriano, 268: 3,8%), e antes ficavam sem prova.
- [ ] **Mesmo imóvel com fotos de imobiliárias diferentes (Jardim Consórcio, 21/10/2026).**
  - O anúncio da Scheid (R$ 750.000, VivaReal 2915942556) e o da Monte Alegre
    (R$ 700.000, VivaReal 2904140532) são a mesma casa, mas cada imobiliária fez as
    próprias fotos (ângulos e enquadramentos diferentes, cada uma com a sua marca d'água).
  - O hash perceptual não separa os casos:
    - mesma casa: menor distância 20 (phash) e 18 (dhash); 0 pares com distância ≤ 10;
    - casas diferentes do mesmo bairro: menor distância 18 (phash) e 12 (dhash).
    Comparação visual por hash não foi implementada.
  - O anúncio da Monte Alegre continua no cálculo, agora como "provável anúncio do próprio
    imóvel" (aviso em destaque; `4a19d7b`). Caminhos
    possíveis: perguntar no formulário "este é o mesmo imóvel?" para os suspeitos, ou
    comparar por IA de visão.

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

- [ ] **Lote diferente entra sem desconto do terreno (infla o valor; decidir com a usuária
  e depois do lote em andamento).** O Agente 2 deixa de eliminar casas pelo tamanho do lote
  quando há 5 ou mais terrenos **coletados** (`MIN_TERRENOS_TERRENO_NAO_ELIMINA`) e avisa a
  IA que "o valor do terreno é descontado no cálculo". O Agente 5 só desconta com 5 ou mais
  terrenos válidos **na zona** (`MIN_AMOSTRAS_CONFIAVEL`). Com 5+ na região e menos de 5 na
  zona, casas de lote muito maior entram pelo m² total, sem correção.
  - Proposta (25/11/2026): no Agente 5, quando o terreno não for descontado e o imóvel tiver
    terreno informado, tirar do cálculo as casas com lote mais de 30% maior **ou menor** que o
    do imóvel (sempre 30%, sem o relaxamento de 45%); casa sem lote no anúncio continua.
  - Efeito esperado: algumas avaliações caem de valor e outras viram "Sem estimativa".
    Antes de ligar, refazer a conta do Agente 5 nas avaliações gravadas para medir.
  - Não é a causa de Cambé (Jardim do Café 2, 10/11/2026): lá o terreno foi descontado e as
    casas tinham lote parecido. O valor alto veio de casas maiores/novas (3 quartos, até
    R$ 6.800/m²) e dos terrenos de 250–335 m² de outros bairros (+R$ 55 mil no desconto).

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

- [ ] **Apify: confirmar que voltou.** Os créditos tinham acabado (erro 403), mas em
  24/11/2026 a conta mostrava US$ 0,63 usados de US$ 5 no mês (renovou). Confirmar numa
  avaliação de cidade pequena. O Apify é só reserva do Agente 1 (a Athena é a fonte
  principal).

- [ ] **Ordem dos provedores para comparáveis.** Hoje Groq → NVIDIA → Gemini. No
  teste: Groq recusou 7 de 11 por limite de uso (429, modelo qwen3.8-27b); NVIDIA
  respondeu texto em vez de JSON em 3 de 6; Gemini acertou 4 de 4. Sugestão:
  Groq → Gemini → NVIDIA (~1 min a menos). Atenção ao limite por minuto do Gemini
  gratuito.

## Resolvido

- **Terminal desatualizado em relação à tela → fluxo único** (24/11/2026). O `app/graph.py`
  não mudava desde 07/10 e tinha fluxo próprio. Ele não localizava o alvo antes da coleta,
  mandava os terrenos para a zona por outro caminho, não passava o imóvel ao Agente 3 e não
  avaliava o leilão. Em Arapongas, deu R$ 338 mil, contra R$ 299 mil pela tela, com o mesmo
  raio. Agora a tela e o terminal chamam `services/pipeline.executar_avaliacao`. Conferido
  no mesmo imóvel: o terminal, com a IA escolhendo 450 m, deu exatamente R$ 299.121,75,
  igual à tela em 23/11. `tests/test_pipeline_unico.py` falha se alguém voltar a chamar os
  agentes direto da tela ou do terminal.

- **Modelos da NVIDIA desativados** (24/11/2026). O `llama-3.2-11b-vision-instruct` (erro
  410 desde 05/11) e o `gpt-oss-20b` (saiu do ar em 18/11) foram trocados pelo
  `nemotron-3.5-super-vl-120b-a12b` (visão) e pelo `nemotron-3.5-lightning-30b-a3b`
  (texto), com o "pensar" desligado. A chave da NVIDIA também foi trocada: a antiga dava
  403 em todos os modelos. Os nomes dos modelos agora ficam no `.env` (`services/ia.py`,
  `docs/MODELOS_LLM.md`).
- **Qwen (Colab) lento para tarefas reais → desligado** (24/11/2026). Desde 06/10/2026
  nenhuma tarefa real terminava no limite (60–90 s), e em 24/11 o Colab estava fora do ar.
  `QWEN_API_URL` e `QWEN_API_KEY` estão comentadas no `.env`; sem elas, o código pula o
  Qwen. **Para religar:** descomentar as duas linhas, pôr `qwen` no começo das `ORDEM_*`
  desejadas (`docs/MODELOS_LLM.md`) e, no Streamlit Cloud, colocar tudo nos Secrets.
- **Lote do Agente 2: 15 ou 8 candidatos por chamada? → mantido em 15** (medido em
  24/11/2026, decisão da equipe). Medição com os 15 primeiros candidatos reais de Arapongas
  (casa de 70 m²), sem mudar o código:
  - **Histórico:** em 65 avaliações gravadas, o Groq (`gpt-oss-120b`) classificou 2.430
    candidatos em lotes de 15; só 1 foi para uma reserva (Qwen, 10/10/2026). Nenhum lote
    ficou sem classificação por tamanho.
  - **Tokens:** lote de 15 ≈ 4.000 de entrada + 800 de saída (limite do Groq: 8.000 por
    minuto por conta). Lote de 8 ≈ 2.550 + 730. Cada lote repete ~820 tokens de
    instruções fixas: com 30 candidatos, lotes de 8 gastam ~35% mais tokens (≈ 12.800 contra
    9.400), o que pesa no limite diário do Groq.
  - **Reservas com 15:** Gemini (5 s), NVIDIA (7 s) e Z.AI (22 s) devolveram classificação
    completa e válida.
  - **Efeito no resultado:** o mesmo grupo de 15, classificado 3 vezes em cada formato:
    "A" em lote de 15 = 15, 14, 15; em 8 + 7 = 13, 14, 13. Em lote menor a IA fica um pouco
    mais exigente; os que caíram para "B" foram quase sempre os mesmos (55 m² e 2 quartos;
    88 m² em outro bairro). Variação natural com o mesmo lote: 1 candidato oscilando.
  - **Conclusão:** lote de 8 gasta mais, muda um pouco quem entra na conta e não resolve
    nenhuma falha observada. Fica 15 (`TAMANHO_LOTE` em `identificar_comparaveis`). Só
    reavaliar se o Groq passar a recusar lotes de 15 (erro de tamanho ou 429 por minuto
    frequente no Ag.2) ou se as reservas passarem a devolver lotes incompletos.
- **`DATABASE_URL` nos Secrets do Streamlit Cloud** (confirmado em 24/11/2026): o app
  publicado grava as avaliações no banco.

- **Conferência na tela, avisos de repetidos e do próprio anúncio** (21/10/2026; branch
  `conferencia-e-avisos`).
  - `e168040` (A): `_pode_ser_condominio` não dispara mais com "Casa E Terreno À
    Venda", "fora de condomínio" e "não é condomínio".
  - `4a19d7b` (D): "provável anúncio do próprio imóvel". Vale para o suspeito com
    mesma rua, área até 1%, mesmos quartos, banheiros e vagas e preço até 10% diferente.
    Continua no cálculo, mas aparece no topo, em destaque, no laudo e como ⚠️ nas
    verificações. Caso da Monte Alegre (VivaReal 2904140532). Os avisos de
    possível/provável anúncio do próprio imóvel dizem o motivo em uma linha.
  - `065050f` (C): "Possível repetido no cálculo" com os anúncios agrupados logo
    abaixo ("Ver os N anúncios que podem ser repetidos", "Grupo 1: nº 888, R$ 830.000,
    203 m²"), sem a coluna Motivo.
  - `b4a11d9` (B): a conferência saiu do topo e foi para o fim da tela, fechada. Tem
    título de uma linha e uma frase simples por agente. O detalhe técnico continua no
    Excel e no banco.

- **Repetidos entre portais: número no link, códigos do portal, siglas do anunciante**
  (`c5e157a`, 21/10/2026).
  - ImovelWeb sem número na rua: o número é lido do começo do link quando as letras
    terminam com as iniciais da rua ("jcjpv-888-…").
  - Códigos "MI-<13 dígitos>-…" (ImovelWeb, ~22 mil anúncios de Rankim e Sucursal) são
    gerados pelo portal e não vetam. "IMCX…SP" é do sistema da imobiliária (igual nos
    três portais) e continua vetando.
  - Nome do anunciante: "B E G" = "B&G" = "BG".

- **Repetidos da Av. João Peixoto Viegas, 888** (`f0dbc29`, 21/10/2026).
  `_pode_ser_condominio` deixou de disparar com "Casa 3 dormitórios", "sem condomínio"
  e o aviso "valores de condomínio e IPTU podem sofrer alterações". Casa com mesma rua,
  mesmo número e preço idêntico, sem indício de condomínio, junta mesmo com área
  diferente: usa a menor área e marca o alerta "área diferente entre portais". Na
  coleta do Jardim Consórcio, a regra nova juntou 25 anúncios (888: 17 em 1; Antônio
  Zouro, 82: 4; Francisco Ramos, 79: 4).

- **Verificação de repetidos prováveis e texto do terreno** (21/10/2026).
  - `eef9c57`: verificação "Repetidos prováveis entre os usados", com o novo estado
    ⚠️ `"alerta"` (pede conferência, mas pode não ser erro).
  - Commit `tela:` seguinte: o passo a passo do Agente 5 diz o motivo exato de o terreno
    não entrar ("terreno do imóvel não informado", "só N terrenos à venda na região",
    "não há terrenos comparáveis na zona", "o imóvel é apartamento").

- **Revisão dos commits de 20 e 21/10** (21/10/2026).
  - `717c04b`: a verificação que refaz a conta do Agente 5 calcula o R$/m² de cada
    terreno pela mesma regra de `calcular_valores_m2_terreno`: fator 0,80 para
    topografia "acentuado" e o preço/m² do anúncio quando a área é inválida. Antes,
    dividia preço por área e daria ❌ falso nesses casos. O Agente 5 passou a gravar
    `topografia` e `preco_m2_anuncio` no resumo de cada terreno usado (só registro).
  - `665f3b7`: o código da imobiliária (ex.: "CA0406") só confirma o anúncio do
    próprio imóvel com preço igual (≤0,5%) ou área igual (≤2%), e sem veto. Sem isso,
    vira suspeita (sinal `codigo_imobiliaria(X, sem preço ou área iguais)`), porque os
    códigos são sequenciais em cada imobiliária e se repetem entre imobiliárias.
  - `3d07780`: saiu o gráfico de dispersão Área × Preço do bloco do Agente 3. Ele
    mostrava o anúncio excluído como comparável, mostrava "Valor estimado" sem
    estimativa confiável, e a tendência não tem relação com o método.

- **Agente 1: dados para as verificações automáticas** (21/10/2026; aprovado pela
  usuária). As três verificações do Agente 1 que apareciam como ⚪ passaram a ser
  verificadas numa coleta nova:
  - `7df21e1`: `id_execucao` e `coletado_em` em cada anúncio (`coletar_imoveis(...,
    id_execucao=)`). Confere se os dados são desta execução.
  - `60ab144`: `resumo_coleta.fontes` com a situação do Athena (consultas que
    responderam, falhas por subtipo ou "indisponível") e do Apify (se foi consultado
    e por quê, se respondeu, o erro). O erro do Apify é gravado sem o token, porque
    as URLs das chamadas levam `?token=`. Antes, as falhas só iam para o log, e o
    Apify devolvia lista vazia em qualquer erro.
  - `c2994e7`: `resumo_coleta.contagem` com brutos, leilões removidos, total antes de
    juntar os repetidos, repetidos, únicos, cortados pelo limite por tipo, mantidos.
    Confere: encontrados = únicos + repetidos; únicos = mantidos + cortados; e
    mantidos e repetidos iguais aos do resultado.
  - Testes: `tests/test_coleta_registro.py` (10, com Athena e Apify simulados e `data/`
    numa pasta temporária).

- **Verificações automáticas ao final de cada execução** (20/10/2026).
  - `services/verificacoes.verificar_execucao(resultado)` devolve uma lista de
    `{agente, verificacao, esperado, encontrado, ok}`. Não muda nenhum cálculo: só lê o
    resultado de cada agente.
  - Onde aparece:
    - no modo conferência, no topo do resultado, como lista ❌ / ⚪ / ✅, com as falhas
      primeiro;
    - no banco, na coluna `execucoes.verificacoes` (migração 004, rodada no Neon em
      21/10/2026: coluna `verificacoes` JSONB conferida);
    - no Excel, na aba "Verificações".
  - O que é conferido:
    - Geral: cada anúncio aparece em uma só etapa do funil; os resultados dos Agentes
      2 a 5 têm o `id_execucao` desta execução.
    - Agente 1: cidade/UF dos anúncios. Mais três verificações sem dado ainda (ver
      "Agente 1 — Dados que as verificações automáticas precisam").
    - Agente 2: decisão de cada imóvel (quantos pela pré-classificação, pela IA, com o
      modelo, e pela reserva); distância dos confirmados menor ou igual ao raio;
      checagem do próprio anúncio em todos.
    - Agente 3: avaliados = os que chegaram, até o limite de 10; notas entre 0 e 1.
    - Agente 4: nota entre 0 e 1 com localização precisa, ou o aviso de nota neutra.
    - Agente 5:
      - conta refeita de forma independente (média aparada 0,5, terreno e desconto;
        tolerância de R$ 1);
      - usados na zona;
      - nenhum anúncio do próprio imóvel nos usados;
      - terrenos usados coerentes com a decisão de separar o terreno;
      - sem valor ⇔ menos de 5 válidos (ou outro motivo registrado).
  - A verificação de terrenos foi confirmada com o código anterior ao `0b47594`: casa
    sem área do terreno com 6 terrenos dava "6 terrenos usados" e falha; com o código
    atual dá 0 e passa.
  - Nos arquivos reais de `data/`, a conta refeita bateu com a do Agente 5 (diferença
    de R$ 0,00).
  - Testes: `tests/test_verificacoes.py` (20; um caso que passa e um que falha para
    cada verificação, mais tela, Excel e banco).

- **Funil: nomes das etapas e a conta de cada anúncio** (20/10/2026).
  - As etapas de saída começam com "Saiu no": "Saiu no Agente 1 (busca)", "Saiu no
    Agente 2 (parecidos)", "Saiu no Agente 2 (zona)" e "Saiu no Agente 5 (cálculo)".
  - "✅ Entrou no cálculo" virou "✅ Chegou ao cálculo".
  - Para os que chegaram ao cálculo, o Motivo diz o que aconteceu na conta:
    - "R$ X/m², usado na média";
    - "R$ X/m², cortado pela média aparada";
    - numa casa, o mesmo R$/m² entra nas duas séries e pode sair "usado na média uma
      vez (a outra cópia foi cortada)";
    - "não houve cálculo: N comparáveis < mínimo de 5".
  - A situação na zona (confirmado, distância não verificada, ampliação do raio) foi
    para a coluna "Zona", na tela e na aba Funil do Excel.
  - Não existia um bloco "Conta do Agente 5": para o funil saber o que foi cortado, o
    Agente 5 passou a gravar em cada comparável usado o `conta_m2`, com o R$/m² e a
    indicação de se ele ficou na média aparada (`marcar_media_aparada`, o mesmo corte de
    `calcular_media_aparada`). O valor calculado não muda.

- **Tela de resultado e formulário: ajustes** (20/10/2026; branch `ajustes-tela-resultado`).
  - Coisas que confundiam:
    - ao clicar em "Avaliar Imóvel", o resultado anterior sai da tela antes de começar;
    - ao terminar, o cabeçalho vira "✅ Avaliação concluída em N segundos" e saem o aviso
      do F5, a barra e o status;
    - a contagem da zona explica a diferença: "5 comparáveis na zona (1 é o anúncio do
      próprio imóvel e saiu do cálculo)", e o aviso de amostra do Agente 5 diz o mesmo;
    - sem valor, aparece o motivo exato no lugar de "verifique a área informada"
      (`services/textos_tela.motivo_sem_valor`; ex.: "Faltou 1 casa para o mínimo de 5")
      e o que fazer (o raio já foi ampliado até X m, a busca já incluiu a cidade toda,
      informe a área do terreno), na tela, no bloco do Agente 5 e no laudo. Não existia
      um bloco "Por que deu este resultado" no modo conferência: a lógica foi criada
      nessa função.
  - No topo: o aviso do anúncio do próprio imóvel (excluído ou suspeito, com o link)
    aparece logo abaixo do valor e no laudo; sem valor confiável, os comparáveis válidos
    aparecem como referência, com o aviso "Não é uma estimativa".
  - Acabamento:
    - avisos e justificativa do Agente 5 com acento (e o "10%%" do laudo corrigido);
    - plural nas contagens da tela, dos alertas e dos avisos de zona e de raio;
    - funil com "–" no lugar de vazio e preço como "R$ 1.200.000";
    - UF em linha própria;
    - Vagas começa vazio. Vazio = não informado, 0 = sem vaga, e a checagem do próprio
      anúncio segue isso: 0 vaga agora veta um apartamento com vaga;
    - aviso de terreno vazio;
    - sem o bloco "Imobiliária mais próxima" na tela. O Agente 4 ainda faz essa busca;
      dá para tirar depois, se ela não for usada.
  - Testes: `tests/test_tela_resultado.py` (13), mais os ajustes em funil, identidade,
    alertas e Agente 5.

- **Checagem do próprio anúncio: provas mais fortes que a descrição** (20/10/2026).
  Novos sinais em `_eh_anuncio_do_alvo`, do mais forte ao mais fraco:
  - **Link do anúncio**: campo novo no formulário, "Link do anúncio deste imóvel (se
    tiver)", gravado em `entrada_usuario.link_anuncio`. Extrai o portal e o id
    (VivaReal e ZAP compartilham o id; também ImovelWeb, Chaves na Mão e Lugar Certo).
    Se bater, confirma mesmo com veto de atributo. Sinal `link_do_anuncio(grupozap:2903862416)`.
  - **Foto em comum**: compara o código da foto, sem o tamanho e sem os parâmetros (hash
    de 32 caracteres do VivaReal/ZAP e do Lugar Certo, número da foto no ImovelWeb,
    código no Chaves na Mão). Casa: confirma, desde que não haja veto. Apartamento: só
    suspeita. Sinal `foto_em_comum(<código>)`. Só casa fotos do mesmo serviço de
    imagens: uma foto do VivaReal não casa com a mesma foto no ImovelWeb.
  - **Código da imobiliária** ("CÓDIGO DO IMÓVEL : CA0406", "Cód.", "Ref.",
    "Referência"; letras e números, 4 caracteres ou mais) nas duas descrições: confirma,
    desde que não haja veto. Sinal `codigo_imobiliaria(CA0406)`.
  - **Descrição**: o rodapé da imobiliária ("Agende sua visita", "Atendemos…", CRECI,
    telefone, nome da imobiliária) sai antes da comparação, e anúncios diferentes da
    mesma imobiliária deixam de parecer iguais.
  - Os repetidos absorvidos agora guardam fotos e banheiros (`CAMPOS_IDENTIDADE`), e
    todos os sinais valem também contra eles (`via_duplicata`). Os sinais aparecem em
    `checagem_alvo` e em `checagem_anuncio_alvo`, no banco.
  - Testes: `tests/test_provas_anuncio_alvo.py` (15).
- **Checagem do próprio anúncio: descrição parcial não confirmava** (20/10/2026). Em
  Palhoça, o início da descrição (até "a 570m da praia") contra a completa dava 0,60
  (casa exige 0,75) e o próprio anúncio entrou no cálculo. `_similaridade_descricao`
  passou a calcular também a continência (proporção das palavras do texto mais curto
  que aparecem no mais longo) e retorna a maior das duas; só vale com o texto curto de
  pelo menos 120 caracteres e 15 palavras distintas (rodapé padrão e textos genéricos
  não casam). O trecho de Palhoça passou a dar 1,00. A regra de identidade não mudou.
- **Agente 5: terrenos apareciam como "Entrou no cálculo" sem terem sido usados**
  (20/10/2026). Sem o terreno do imóvel informado, o cálculo é pelo m² das casas, mas
  os terrenos da zona saíam em `comparaveis_usados` (funil, banco e Excel; Palhoça: 11
  terrenos). Agora, sempre que o terreno não é separado (sem área, poucos terrenos,
  apartamento), nenhum terreno é usado e todos vão para os descartados com o motivo
  ("terreno do imóvel não informado: o valor foi calculado pelo m² das casas"). O valor
  não mudou.

- **Migração `db/migracoes/002_localizacao_e_dados_do_leilao.sql` rodada no Neon**
  (20/10/2026; as 6 colunas conferidas: localizacao_alvo, escopo_busca,
  anuncios_por_proximidade, data_leilao, formas_pagamento, regras_despesas).
- **Checagem do próprio anúncio: maior pontuação do grupo no banco** (20/10/2026).
  Quando nenhum anúncio do grupo é confirmado nem suspeito, `checagem_alvo` grava a
  maior pontuação entre o anúncio que ficou e os repetidos absorvidos, com os sinais
  dele e `via_duplicata(portal:listing_id)` quando vem de um repetido. Antes gravava só
  o anúncio que ficou, e um repetido mais parecido com o imóvel não aparecia entre os 10
  de maior pontuação. A regra de confirmado/suspeito não mudou.

- **Alerta "possível anúncio do próprio imóvel" com o bairro escrito diferente**
  (decisão da usuária, 20/10/2026). A comparação de bairro da checagem do próprio
  anúncio passou a aceitar nome parecido (sem acento/maiúsculas, um contido no outro),
  como o resto do sistema: "Praia Do Sonho Ens Brito" × "Praia do Sonho". Só o alerta
  muda; a exclusão do cálculo continua exigindo preço + área + descrição parecida (ou
  rua + número, ou coordenada). Palhoça (anúncio VivaReal 2903862416, sem descrição):
  antes nada; agora "possível anúncio do próprio imóvel". A proposta de excluir a
  casa sem descrição quando preço, área, cômodos e bairro batem não foi feita.

- **Entrada completa do formulário e checagem do próprio anúncio no banco**
  (decisão da usuária, 20/10/2026; branch `entrada-usuario-no-banco`, migração 003
  rodada no Neon em 20/10/2026).
  `entrada_usuario`: tudo o que foi digitado e como foi lido. `checagem_anuncio_alvo`:
  testados, confirmados, suspeitos e os 10 anúncios com mais sinais (ex.:
  `casa_preco_area_descricao(area_dif=0.0, desc=0.954)`). Motivo: em Palhoça
  (20/10/2026) o anúncio do próprio imóvel entrou no cálculo e não dava para saber,
  pelo banco, o que o formulário tinha mandado. O campo **Preço** passou a aceitar o
  formato brasileiro ("1.200.000", "1.200.000,00"), como a área e os valores do leilão.

- **Funil dos anúncios na tela, para conferência** (decisão da usuária, 20/10/2026;
  branch `funil-conferencia`). Bloco "🔎 Funil dos anúncios (conferência)" no fim do
  resultado e aba "Funil" no Excel: cada anúncio com a etapa em que saiu (Agente 1 ·
  busca, Agente 2 · parecidos, Agente 2 · zona, Agente 5 · cálculo) ou "Entrou no
  cálculo", e o motivo (regra de repetido, motivo da pré-classificação, justificativa da
  IA, distância e raio, motivo do descarte no Agente 5, próprio anúncio). O Agente 5
  passou a gravar `motivo_descarte` nos descartados (o cálculo não muda). Desligar:
  `MOSTRAR_FUNIL=0` no `.env`/Secrets; tirar de vez: apagar `app/funil.py` e a chamada
  na tela. Palhoça: 408 anúncios (13 no cálculo, 1 próprio anúncio excluído, 67 fora
  da zona, 195 não parecidos, 132 repetidos).

- **Mais 3 alertas na tela, com explicação** (decisão da usuária, 19/10/2026; branch
  `tomtom-geocodificacao`): `terreno_fora_do_padrao`, `possivel_repetido_no_calculo` e
  `area_diferente_entre_portais` aparecem como o de amostra concentrada (aviso + expander
  "Ver os anúncios" com endereço, preço, área, portal, link e motivo). As regras não
  mudaram; o texto é o mesmo na tela, no laudo e no Excel (no laudo termina com
  "Confira os anúncios na tela ou no Excel."). Nenhum texto mostrado menciona mais o
  "cenário conservador": saiu do alerta de terreno e da linha "Faixa da estimativa"
  em "Como chegamos neste valor".

- **Alerta de amostra concentrada na tela, com explicação** (decisão da usuária,
  19/10/2026; branch `tomtom-geocodificacao`). A regra do alerta não mudou; só o
  texto, que agora é o mesmo na tela, no laudo e no Excel: "Amostra concentrada:
  {qtd} dos {total} imóveis usados no cálculo ({parcela}) têm exatamente a mesma
  área: X m² / o mesmo preço: R$ X. Isso costuma indicar um mesmo empreendimento…
  Confira os anúncios abaixo." A tela mostra um aviso para área e outro para preço
  (se os dois dispararem), junto dos outros avisos do resultado, cada um com um
  expander "Ver os {qtd} anúncios iguais" (endereço, preço, área, portal e link). O
  laudo traz a frase, sem a lista.

- **Lançamentos: anúncios iguais juntados como 1 imóvel, com aviso** (decisão da
  usuária, 19/10/2026; branch `tomtom-geocodificacao`). A regra de repetidos
  (`agents/identidade.py`) não muda. Depois de juntar, o Agente 1 marca como
  `provavel_lancamento` o grupo de apartamentos com 5 ou mais anúncios
  (`MIN_ANUNCIOS_LANCAMENTO`) de pelo menos 5 imobiliárias diferentes, todos com o
  mesmo preço e a mesma área. Alerta `provavel_lancamento` (banco e aba Alertas) e
  aviso na tela, no laudo e no Excel ("Provável lançamento"): "{n} anúncios iguais
  (mesmo preço e área, imobiliárias diferentes; provável lançamento) foram contados
  como 1 imóvel." Log `[Ag1] provavel lancamento`. Grupo da mesma imobiliária
  (mesmo anúncio em vários portais) não conta. São Paulo/Barra Funda (ID 22, Rua
  Vitorino Carmilo, 444): 6 grupos com 54 anúncios no total (de 6 a 12 cada, de 6 a
  10 imobiliárias), contados como 6 imóveis.

- **Google aceitava rua homônima de outro bairro (`partial_match`).** Decisão da
  usuária (19/10/2026): o Google com `partial_match` é recusado quando o bairro
  devolvido (sublocality / sublocality_level_1 / neighborhood) difere do informado
  (sem acento e sem maiúsculas) ou quando não devolve bairro; a recusa cai na TomTom.
  Com o mesmo bairro, ou sem `partial_match`, nada muda. A TomTom não passa por essa
  checagem. Itaboraí ("Rua Nossa Senhora da Conceição, Jardim Itajubá"): antes o
  Google punha o imóvel numa rua homônima a 17,3 km de Porto das Caixas; agora a
  TomTom acha a rua a 136 m. Curitiba/Cajuru e Londrina/Aritana: nenhuma recusa nova
  e nenhuma chamada à TomTom (imóvel e anúncios iguais).

- **TomTom como última tentativa de geocodificação** (decisão da usuária, 17/10/2026;
  branch `tomtom-geocodificacao`). Ordem em cada tentativa: Nominatim → Google →
  TomTom, só quando os dois primeiros falham ou são recusados por imprecisão; vale
  para o imóvel e para os anúncios (e para o Agente 4, que usa a mesma função).
  Aceita `Point Address`, `Address Range`, `Street`/`Cross Street` (nível rua) e
  `Geography` com `MunicipalitySubdivision`/`Neighbourhood` (nível bairro); recusa
  cidade/estado e resultado de outra cidade. Sem `TOMTOM_API_KEY`, pula sem erro;
  erro, 429 ou tempo esgotado ficam no log. Limite de 200 chamadas por avaliação
  (`LIMITE_TOMTOM_POR_AVALIACAO`). Banco: `fontes.tomtom_localizacoes` e
  `fontes.tomtom_chamadas`. Não existe `.env.example` no repositório.

- **Agente 4 tinha geocodificação própria.** Decisão da usuária (17/10/2026): sem a
  coordenada da zona do Agente 2, o Agente 4 usa `_geocodificar_com_fallback` (com
  checagem de precisão, sem aceitar cidade). Sem localização precisa, não avalia a
  infraestrutura (antes avaliava a partir do centro da cidade): a nota fica vazia e a
  tela mostra "Infraestrutura não avaliada (endereço não localizado)". O tempo de
  venda usa a nota neutra 0,50 e os pesos de sempre (35/40/25; fórmula sem mudança)
  e avisa na tela, no laudo e no Excel: "Tempo estimado sem a infraestrutura do
  entorno (endereço não localizado no mapa): a infraestrutura foi considerada média.
  Confira o entorno do imóvel." Quando a nota falta por outro motivo (o Agente 4
  falhou: tempo esgotado, serviço fora do ar), o aviso é: "Tempo estimado sem a
  infraestrutura do entorno (a avaliação da infraestrutura falhou nesta rodada): a
  infraestrutura foi considerada média." Para distinguir, o Agente 4 grava o status
  `endereco_nao_localizado` no seu arquivo. Log: `[Ag5] liquidez sem nota de
  infraestrutura … | motivo=endereco_nao_localizado` ou `motivo=falha_agente4`.

- **ImovelWeb em SP: coleta concluída** (17/10/2026). `tools.atualizar_particoes`
  rodado (só `MSCK REPAIR TABLE`): nenhuma partição nova — a pasta de SP já estava
  registrada. No Athena, SP (coleta mais recente de cada portal): ImovelWeb
  3.887.261 linhas de 642 cidades (última coleta gravada em 12/10/2026), Chaves na
  Mão 2.890.862 (574), VivaReal 2.929.346 (608), Lugar Certo 3.365 (79). Ideal
  continua: a coleta (repositório scraper-imoveis) rodar o registro ao fim de cada
  estado.

- **Mínimo de terrenos incoerente no Agente 5.** Decisão da usuária (17/10/2026):
  casa com área de terreno separa o terreno só com 5 ou mais terrenos na zona
  (`MIN_AMOSTRAS_CONFIAVEL`). Com 1 a 4, calcula como com 0: pelo m² das casas, sem
  separar; os terrenos ficam fora do cálculo (`comparaveis_descartados`; banco e Excel
  mostram "Terrenos no cálculo: 0") e a tela, o laudo e o Excel avisam: "Só {n}
  terreno(s) à venda na região (mínimo de 5). O valor foi calculado pelo m² das casas
  parecidas, sem separar o terreno…". Antes, com 1 a 4 terrenos dava
  amostra_insuficiente. Terreno puro e apartamento não mudaram. Ex.: Curitiba/Cajuru
  (4 terrenos): R$ 913.061,64 com o terreno separado → R$ 920.256,98 pelo m² das casas.

- **Imóvel não localizado e sem anúncios no bairro: socorro usa parecidos da cidade
  toda.** Decisão (17/10/2026): aceitar com aviso. O aviso já existe
  (`texto_aviso_zona`, escopo "cidade"). Não alterar o código.

- **Raio da zona ampliado até ter 5 comparáveis** (decisão da usuária, 17/10/2026;
  branch `raio-ampliado`). Depois de classificar os anúncios no raio escolhido pela
  IA de visão, se houver menos de 5 confirmados (`MIN_CONFIRMADOS_ZONA`), o Agente 2
  amplia o raio em passos de ×1,5 até ter 5 ou chegar a 1.500 m
  (`RAIO_PROXIMIDADE_M`); raio da IA ≥ 1.500 m não é ampliado. Casas/aptos e
  terrenos são ampliados separadamente (5 de cada). Não chama a IA nem geocodifica de
  novo: usa a distância já calculada, e só de posições exatas (anúncio localizado só
  pelo bairro ou com coordenada genérica continua "zona não verificada"). O fallback
  dos "zona não verificada" só entra depois, se ainda faltar. Banco: `raio_zona_m` é
  o raio final; `parametros` guarda `raio_ia_m`, `raio_final_m`,
  `raio_final_terrenos_m` e o aviso. Excel: "Raio escolhido pela IA", "Raio usado no
  cálculo", "Raio usado para os terrenos" e "Ampliação do raio". Tela e laudo
  mostram o aviso. Convive com a decisão do professor de manter o raio da IA: a
  variação da IA continua; a ampliação só entra quando faltam comparáveis.

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
