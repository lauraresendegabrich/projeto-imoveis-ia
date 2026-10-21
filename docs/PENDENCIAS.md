# Pendências

Itens identificados e ainda não resolvidos. Ao resolver um item, mova-o para
"Resolvido" no fim do arquivo e cite o commit.

## Coletas e base de anúncios

## Regras para levar ao professor

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
