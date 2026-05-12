# Agente 2 — Identificador de Comparáveis

## Objetivo

Receber os imóveis coletados pelo Agente 1 e identificar quais são realmente comparáveis ao imóvel alvo — ou seja, quais um comprador consideraria como alternativa real de compra. O resultado é uma lista ranqueada com justificativa para cada classificação, além de uma validação geográfica da zona homogênea.

---

## Problema Central: O que é um "Comparável"?

Na avaliação imobiliária, um imóvel comparável não é simplesmente aquele com características numéricas próximas. Um terreno de 500m² não é comparável a uma casa de 170m², mesmo que o preço seja similar. Uma casa de 3 quartos com 160m² pode ser comparável a uma de 226m² se estiverem no mesmo bairro e faixa de preço/m². Uma casa com uso comercial (kitnets alugadas) não é comparável a uma residencial, mesmo com área idêntica.

Esse problema tem duas dimensões:
1. **Numérica** — área, quartos, preço/m², banheiros, vagas
2. **Semântica** — tipo de uso, padrão construtivo, contexto do anúncio

A abordagem adotada combina as duas: score numérico para triagem rápida e LLM para classificação semântica.

---

## Arquitetura

```
imoveis_completos.json (Agente 1)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  Separação de terrenos                               │
│  (propertyType == "Terrenos")                        │
│  → Terrenos NÃO entram no ranking/clustering         │
│  → Terrenos SIM entram na zona homogênea             │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  ETAPA 1 — Similaridade Numérica                     │
│  Score 0.0–1.0 por distância relativa                │
│  Campos: área, quartos, preço/m², banheiros, vagas   │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  ETAPA 2 — Clustering via LLM                        │
│  Groq (llama-3.3-70b-versatile)                      │
│  Cluster A (similar) ou B (não similar)              │
│  Ranking global 1–N + justificativa por imóvel       │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  ETAPA 3 — Zona Homogênea                            │
│  Google Maps Static API + Groq Vision                │
│  Raio dinâmico sugerido pela IA                      │
│  Classificação: na_zona / fora_zona                  │
└─────────────────────────────────────────────────────┘
        │
        ▼
imoveis_comparaveis.json + zona_homogenea.json + satelite_zona_homogenea.png
```

---

## Etapa 1 — Similaridade Numérica

### Fluxo completo

```
1. Para cada imóvel candidato, calcula distância relativa em cada campo:
   → distancia = |valor_alvo - valor_candidato| / max(alvo, candidato)
   → similaridade = 1 - distancia  (0 = totalmente diferente, 1 = idêntico)

2. Pondera cada similaridade pelo peso do campo:
   → área (m²):   30%  — fator mais determinante no preço absoluto
   → quartos:     25%  — define o perfil e público-alvo
   → preço/m²:    20%  — proxy do padrão construtivo
   → banheiros:   15%  — complementa o perfil
   → vagas:       10%  — relevante em centros urbanos

3. Se um campo está ausente em um dos imóveis:
   → Aplica penalidade de 50% naquele peso
   → (não ignora o campo — isso inflaria artificialmente o score)

4. Score final = soma(similaridade × peso) / soma(pesos usados)
   → Resultado: float de 0.0 a 1.0

5. Ordena todos os candidatos por score (maior primeiro)
   → Score NÃO é enviado para a LLM (evita viés de ancoragem)
   → Score é usado internamente para ordenação e fallback
```

### Como funciona
Para cada imóvel candidato, calcula um score de 0.0 a 1.0 usando distância relativa entre os campos numéricos do alvo e do candidato:

```
distancia_campo = |valor_alvo - valor_candidato| / max(valor_alvo, valor_candidato)
similaridade_campo = 1 - distancia_campo
score_final = soma(similaridade_campo × peso_campo) / soma(pesos_usados)
```

Se um campo está ausente em um dos imóveis, aplica penalidade de 50% naquele peso (em vez de ignorar o campo completamente, o que inflaria artificialmente o score).

### Pesos definidos

| Campo | Peso | Justificativa |
|---|---|---|
| Área (m²) | 30% | Fator mais determinante no preço absoluto |
| Quartos | 25% | Define o perfil do imóvel e o público-alvo |
| Preço/m² | 20% | Proxy do padrão construtivo — imóveis com preço/m² muito diferente têm padrão incompatível |
| Banheiros | 15% | Complementa o perfil, especialmente em imóveis de alto padrão |
| Vagas | 10% | Fator secundário, mas relevante em centros urbanos |

### Por que o score numérico não é suficiente sozinho
O score captura proximidade numérica, mas não semântica. Exemplos de falsos positivos que o score não detecta:
- Terreno de 200m² vs casa de 170m² — área similar, mas tipos incomparáveis
- Casa com 3 kitnets alugadas vs casa residencial — uso diferente
- Casa de R$ 8M vs casa de R$ 1.4M no mesmo bairro — padrão incompatível que o preço/m² pode não capturar se as áreas forem muito diferentes

Por isso o score é usado como **pré-triagem e ordenação interna**, mas não como critério final de classificação.

### Por que o score NÃO é enviado para a LLM
Decisão deliberada para evitar viés de ancoragem. Se a LLM recebe o score numérico, tende a confirmar a classificação numérica em vez de fazer sua própria análise semântica. A LLM recebe apenas as características brutas do imóvel.

---

## Etapa 2 — Clustering via LLM

### Fluxo completo

```
1. Separa terrenos (propertyType == "Terrenos") antes de qualquer processamento
   → Terrenos NÃO entram no clustering (score distorcido sem quartos/banheiros/vagas)
   → Terrenos SIM entram na Etapa 3 (zona homogênea)
   → Terrenos recebem cluster="terreno" e ranking_llm=null no resultado final

2. Monta prompt com características do alvo + todos os candidatos (sem score)
   → Inclui: tipo, área, quartos, banheiros, vagas, preço, preço/m², bairro, rua, descrição
   → Score numérico NÃO é incluído (evita viés de ancoragem)

3. Envia prompt para Groq (llama-3.3-70b-versatile) em uma única chamada
   → Modelo retorna JSON com classificação de todos os imóveis

4. Parseia resposta JSON da LLM:
   → cluster:      "A" (similar) ou "B" (não similar)
   → ranking:      posição global 1–N (1 = mais similar ao alvo)
   → justificativa: 1 frase explicando a classificação

5. Se LLM falhar ou retornar JSON inválido → fallback numérico:
   → Score ≥ 0.60 → Cluster A
   → Score < 0.60 → Cluster B
   → Ranking = posição no score

6. Ordena resultado final:
   → Cluster A primeiro (ordenado por ranking_llm)
   → Cluster B depois
   → Terrenos por último (cluster="terreno")

7. Salva em data/imoveis_comparaveis.json
```

### Modelo escolhido: llama-3.3-70b-versatile (Groq)
Testamos diferentes modelos para a tarefa de clustering:

| Modelo | Resultado | Motivo da escolha/descarte |
|---|---|---|
| llama-3.1-8b-instant | Classificações inconsistentes | Modelo pequeno (8B) não captura nuances imobiliárias |
| llama-3.3-70b-versatile | ✅ Classificações coerentes | 70B parâmetros, melhor raciocínio contextual |
| gemma2-9b-it | Não testado para clustering | Reservado como fallback do llm_service |

O modelo 70B é mais lento (~6s vs ~0.5s do 8B), mas a tarefa de clustering é feita em **uma única chamada** com todos os imóveis — o tempo total é aceitável.

### Decisão sobre terrenos: separar antes da LLM
**Problema identificado:** Quando terrenos eram enviados junto com casas para a LLM, ela os classificava corretamente como Cluster B (não similar), mas gastava tokens e tempo avaliando algo que nunca seria comparável a uma casa construída.

**Solução:** Separar terrenos antes do clustering. Terrenos não têm quartos, banheiros nem vagas — o score numérico seria distorcido (penalidade de 50% em 3 dos 5 campos). A LLM não precisa avaliar tipo incomparável.

**Porém:** Terrenos são enviados para a Etapa 3 (zona homogênea). A presença de terrenos na mesma zona do imóvel alvo é informação relevante para a avaliação — indica potencial construtivo da região e pode influenciar o valor do solo.

**No resultado final:** Terrenos aparecem com `cluster="terreno"` e `ranking_llm=null`, claramente separados dos comparáveis ranqueados.

### Prompt engineering
O prompt foi iterado várias vezes. Problemas encontrados e soluções:

**Problema 1:** LLM muito restritiva — colocava no Cluster B imóveis com diferença de 1 banheiro.
**Solução:** Adicionar instrução explícita: "Diferença de 1 banheiro ou 1 vaga NÃO desqualifica um imóvel. Seja GENEROSO no Cluster A."

**Problema 2:** LLM confundia "não similar" com "não é bom imóvel".
**Solução:** Reformular critério: "Cluster B = imóvel que um comprador NÃO consideraria como alternativa ao alvo (tipo diferente, área >2x, uso diferente)."

**Problema 3:** Resposta fora do formato JSON esperado.
**Solução:** Instrução explícita "RESPONDA EXATAMENTE neste formato JSON (sem texto antes ou depois)" + parser com regex para extrair o JSON mesmo se houver texto extra.

### Fallback (se LLM falhar)
Se a LLM não responder ou retornar JSON inválido, o sistema usa apenas o score numérico:
- Score ≥ 0.60 → Cluster A
- Score < 0.60 → Cluster B
- Ranking = posição no score (1 = maior score)

O threshold de 0.60 foi definido empiricamente — scores abaixo disso geralmente indicam diferença de área ou quartos acima de 40%, que na prática torna o imóvel não comparável.

---

## Etapa 3 — Zona Homogênea

### Fluxo completo

```
1. Geocodifica endereço do alvo
   → Nominatim (OpenStreetMap) — gratuito, sem key, 1 req/s
   → Fallback: Google Geocoding API (se Nominatim falhar)
   → Resultado: lat/lng do imóvel alvo

2. Google Maps Static API gera imagem de satélite
   → maptype=hybrid (satélite + nomes de ruas)
   → size=640x640, scale=2 → 1280×1280px efetivos
   → Marcador vermelho no imóvel alvo
   → Gasta 1 chamada das 10.000/mês gratuitas

3. Groq Vision (Llama 4 Scout 17B) analisa a imagem e retorna JSON:
   → tipo_regiao          (centro_urbano, residencial, comercial, misto...)
   → uso_predominante     (residencial, comercial, misto, institucional...)
   → padrao_construtivo   (casas, sobrados, predios_baixos, torres_altas, misto...)
   → densidade_urbana     (baixa, media, alta)
   → homogeneidade_visual (alta, media, baixa)
   → infraestrutura_aparente         (lista de elementos visíveis)
   → elementos_que_influenciam_valor (lista)
   → elementos_que_podem_quebrar_homogeneidade (lista)
   → raio_sugerido_metros (int — raio adequado para aquela região)
   → justificativa_raio   (1 frase explicando o raio)
   → descricao_zona_homogenea (até 3 frases descrevendo a zona)
   → confianca            (alta, media, baixa)
   → limitacoes           (o que não pode ser confirmado só pela imagem)

4. Geocodifica cada imóvel (Nominatim, 1 req/s)
   → Calcula distância em metros via fórmula de Haversine
   → Imóveis sem rua: assume na_zona se mesmo bairro

5. Classifica cada imóvel:
   → na_zona:   distância ≤ raio sugerido pela LLM (mínimo 400m)
   → fora_zona: distância > raio
```

### Saídas da Etapa 3
```
data/zona_homogenea.json        — análise visual + classificação de cada imóvel
data/satelite_zona_homogenea.png — imagem 1280×1280px com marcador no alvo
```

### O que é zona homogênea na avaliação imobiliária
Zona homogênea é o conceito técnico da NBR 14653 (norma brasileira de avaliação de imóveis) que define a região com características urbanas similares ao imóvel avaliado — mesmo uso do solo, mesmo padrão construtivo, mesma densidade. Imóveis fora da zona homogênea podem ter preços influenciados por fatores diferentes (proximidade de polo comercial, infraestrutura diferente) e distorcer a estimativa.

### Abordagem adotada: raio dinâmico via visão computacional

**Abordagem descartada — raio fixo:**
Usar um raio fixo (ex: 500m ou 1km) é simples mas impreciso. Em centros urbanos densos, 500m pode incluir bairros com padrão completamente diferente. Em cidades menores, 1km pode excluir imóveis perfeitamente comparáveis.

**Abordagem adotada — raio sugerido por IA:**
1. Gerar imagem de satélite da região (Google Maps Static API, hybrid, 1280×1280px)
2. Enviar para modelo de visão (Groq Vision, Llama 4 Scout 17B)
3. O modelo analisa visualmente a região e sugere o raio adequado com justificativa

Isso permite que o raio seja calibrado para cada região específica — um centro urbano denso recebe raio menor (500m), uma área residencial homogênea recebe raio maior (800m).

### Geocodificação: Nominatim como principal, Google como fallback

**Por que Nominatim primeiro:**
- Gratuito, sem key, sem limite de cadastro
- Baseado no OpenStreetMap — boa cobertura de ruas brasileiras
- Limite de 1 req/s (respeitado com `time.sleep(1)` entre requests)

**Por que Google como fallback:**
- Nominatim falha em endereços com numeração incorreta ou ruas pouco mapeadas
- Google Geocoding tem cobertura mais completa e tolerância a variações de escrita
- Consome da cota de 10.000 requests/mês gratuitos (compartilhada com Maps Static API)

### Fórmula de Haversine
Calcula distância em metros entre duas coordenadas geográficas considerando a curvatura da Terra. Precisão de ~0.5% para distâncias curtas (< 10km) — suficiente para o contexto urbano do projeto.

### Raio mínimo de 400m
Mesmo que o Groq Vision sugira raio menor, aplicamos mínimo de 400m. Justificativa: em centros urbanos muito densos, a IA pode sugerir raios pequenos (200–300m) que excluiriam imóveis perfeitamente comparáveis a poucos quarteirões de distância.

### Imóveis sem coordenadas
Quando o Nominatim não consegue geocodificar um imóvel (endereço incompleto, rua não mapeada), o sistema assume `na_zona` se o imóvel estiver no mesmo bairro do alvo. Essa decisão conservadora evita descartar imóveis válidos por limitação do geocodificador.

### Resultado do teste (Centro de Itajaí/SC)
```
Análise visual do Groq Vision:
  Tipo:          centro_urbano
  Uso:           misto (comércio + serviços)
  Padrão:        misto (casas, sobrados, prédios baixos)
  Densidade:     média
  Homogeneidade: baixa
  Raio sugerido: 500m
  Confiança:     média

Classificação geográfica (62 imóveis):
  Na zona (≤ 500m):  45 imóveis
  Fora da zona:      17 imóveis
    → Rua Tijucas (828m)
    → Av. Joca Brandão (897m)
    → Rua Felipe Schmidt (942m)
    → Av. Ministro Victor Konder (1060m)
```

---

## Resultado dos Testes (Centro de Itajaí/SC)

```
Imóveis carregados:        45
Terrenos separados:        17  (não entram no clustering)
Casas/aptos para análise:  28

Score numérico — Top 5:
  [1] score=1.000 | 170m² | 3q | R$ 1.395.000 | Rua Franklin Máximo Pereira
  [2] score=0.948 | 160m² | 3q | R$ 1.590.000 | Rua Juvenal Garcia
  [3] score=0.938 | 157m² | 3q | R$ 1.600.000 | Rua Juvenal Garcia
  [4] score=0.910 | 160m² | 3q | R$ 1.590.000 | Rua Juvenal Garcia
  [5] score=0.909 | 160m² | 3q | R$ 1.600.000 | Centro

Clustering LLM (llama-3.3-70b-versatile, ~4s):
  Cluster A (similares):     14 imóveis
  Cluster B (não similares): 14 imóveis

Zona homogênea (raio 500m):
  Na zona:   45 imóveis
  Fora zona: 17 imóveis
```

---

## Arquivos Gerados

| Arquivo | Conteúdo |
|---|---|
| `data/imoveis_comparaveis.json` | Ranking completo: cluster, score, ranking_llm, justificativa, terrenos |
| `data/zona_homogenea.json` | Análise visual da região + classificação geográfica de cada imóvel |
| `data/satelite_zona_homogenea.png` | Imagem de satélite 1280×1280px com marcador no imóvel alvo |

### Schema de saída (`imoveis_comparaveis.json`)
```json
{
  "imovel_alvo": { ... },
  "comparaveis": [
    {
      "cluster": "A",
      "ranking_llm": 1,
      "score_similaridade": 0.94,
      "justificativa": "Casa com área similar, mesmo bairro e preço/m² compatível"
    },
    {
      "cluster": "B",
      "ranking_llm": 15,
      "score_similaridade": 0.78,
      "justificativa": "Casa com área muito maior e preço/m² incompatível"
    },
    {
      "cluster": "terreno",
      "ranking_llm": null,
      "score_similaridade": null,
      "justificativa": "Terreno excluído do ranking — tipo incomparável com imóvel construído"
    }
  ],
  "terrenos": [ ... ],
  "resumo": {
    "total_analisados": 28,
    "cluster_a": 14,
    "cluster_b": 14,
    "terrenos_excluidos": 17,
    "metodo": "similaridade_numerica + clustering_llm"
  }
}
```

---

## Dependências Externas

| Serviço | Uso | Custo | Configuração |
|---|---|---|---|
| Groq (llama-3.3-70b) | Clustering semântico | Gratuito (14.400 req/dia) | `GROQ_API_KEY` no `.env` |
| Groq Vision (Llama 4 Scout) | Análise da imagem de satélite | Gratuito | `GROQ_API_KEY` no `.env` |
| Google Maps Static API | Imagem de satélite | Gratuito (10.000/mês, requer faturamento ativo) | `GOOGLE_MAPS_KEY` no `.env` |
| Google Geocoding API | Fallback de geocodificação | Gratuito (10.000/mês, requer faturamento ativo) | `GOOGLE_MAPS_KEY` no `.env` |
| Nominatim (OSM) | Geocodificação principal | Gratuito, sem key, 1 req/s | Sem configuração |

### Nota sobre o Google Maps e faturamento
O Google exige conta de faturamento ativa mesmo para uso dentro do limite gratuito ($200/mês de crédito). Dependendo do método de pagamento cadastrado, pode exigir depósito inicial (R$50 reembolsável). Caso o faturamento não esteja ativo, a Etapa 3 é pulada automaticamente — o pipeline continua funcionando sem a análise visual e sem a imagem de satélite.

---

## Como Rodar

```bash
.venv/Scripts/python.exe -m tests.test_comparaveis
```

**Pré-requisitos:**
- `data/imoveis_completos.json` gerado pelo Agente 1
- `GROQ_API_KEY` no `.env`
- `GOOGLE_MAPS_KEY` no `.env` (opcional — zona homogênea é pulada sem ela)

---

## Entrada

### `imovel_alvo` — campos utilizados

| Campo | Tipo | Usado em | Descrição |
|---|---|---|---|
| `area` | int | Etapa 1 | Área em m² |
| `bedrooms` | int | Etapa 1 | Número de quartos |
| `bathrooms` | int | Etapa 1 | Número de banheiros |
| `parkingSpaces` | int | Etapa 1 | Número de vagas |
| `pricePerSqm` | float | Etapa 1 | Preço por m² (R$) |
| `propertyType` | str | Etapa 2 | Tipo do imóvel ("Casas", "Apartamentos") |
| `neighborhood` | str | Etapa 2 | Bairro |
| `street` | str | Etapa 2 + 3 | Rua |
| `description` | str | Etapa 2 | Descrição do anúncio |
| `rua` | str | Etapa 3 | Rua (para montar endereço de geocodificação) |
| `numero` | str | Etapa 3 | Número (para geocodificação) |
| `bairro` | str | Etapa 3 | Bairro (para geocodificação) |
| `cidade` | str | Etapa 3 | Cidade |
| `estado` | str | Etapa 3 | Estado (sigla, ex: "SC") |

### `imoveis_coletados` — fonte dos dados
- Padrão: carrega automaticamente de `data/imoveis_completos.json` (gerado pelo Agente 1)
- Alternativo: passar lista diretamente via parâmetro `imoveis_coletados` da função `identificar_comparaveis()`

---

## Instalação das Dependências

```bash
# Dependências do requirements.txt (já instaladas no setup inicial)
.venv/Scripts/pip install -r requirements.txt

# Pacotes adicionais necessários para o Agente 2
.venv/Scripts/pip install langchain-groq langchain-google-genai openai
```

Pacotes utilizados pelo Agente 2:
| Pacote | Uso |
|---|---|
| `langchain-groq` | Chamada ao Groq LLM (clustering) |
| `openai` | Chamada ao Groq Vision via API compatível OpenAI |
| `requests` | Geocodificação via Nominatim e Google |
| `python-dotenv` | Leitura do `.env` |
