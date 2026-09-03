# Agente 2 — Identificador de Comparáveis

## Objetivo

Recebe os imóveis coletados pelo Agente 1 e identifica quais são realmente comparáveis ao imóvel alvo. Usa score numérico + LLM para classificar, depois valida geograficamente com imagem de satélite.

---

## Entrada

- `data/imoveis_completos_ag1.json` (saída do Agente 1)
- Características do imóvel alvo (área, quartos, banheiros, vagas, tipo, bairro, rua)

---

## Fluxo Completo

```
ETAPA 1 — Separação de terrenos
ETAPA 2 — Score numérico de similaridade
ETAPA 3 — Clustering via LLM (Groq gpt-oss-120b)
ETAPA 4 — Zona Homogênea (Google Maps + Groq qwen3.8-27b)
```

---

## ETAPA 1 — Separação de Terrenos

Antes de qualquer análise, separa terrenos dos construídos:

- **Terrenos** (`propertyType == "Terrenos"`) → NÃO entram no ranking/LLM
- **Casas/Apartamentos** → seguem para score + clustering

Por quê: não faz sentido comparar terreno vazio com casa construída. Score numérico seria distorcido (terreno não tem quartos, banheiros, vagas).

Os terrenos ficam no resultado final com `cluster="terreno"` e **passam pela mesma validação geográfica** da zona homogênea (geocodificação + distância ao alvo). São separados em `terrenos_confirmados` (na zona), `terrenos_fora_zona` e `terrenos_nao_verificados`. Isso importa porque o terreno influencia diretamente a decomposição de preço de casas no Agente 5 — um terreno distante distorceria o m² de terreno de referência.

---

## ETAPA 2 — Score Numérico (instantâneo, sem LLM)

Para cada imóvel construído, calcula score 0.0 a 1.0:

| Campo | Peso | Justificativa |
|-------|------|---------------|
| área (m²) | 30% | Fator mais determinante no preço |
| quartos | 25% | Define perfil e público-alvo |
| preço/m² | 20% | Proxy do padrão construtivo |
| banheiros | 15% | Complementa o perfil |
| vagas | 10% | Relevante em centros urbanos |

**Fórmula por campo:**
```
distância = |valor_alvo - valor_candidato| / max(alvo, candidato)
similaridade = 1 - distância
```

**Score final:** média ponderada das similaridades × pesos

**Campo ausente:** penalidade de 50% naquele peso (não ignora)

**Importante:** O score numérico NÃO é enviado pra LLM (evita viés de ancoragem).

---

## ETAPA 3 — Clustering via LLM

### Cadeia de fallback

| Prioridade | LLM | Modelo | Configuração |
|---|---|---|---|
| 1ª | Qwen3-VL-8B | Colab | QWEN_API_URL + QWEN_API_KEY |
| 2ª | Groq | openai/gpt-oss-120b | GROQ_API_KEY |
| 3ª | Groq | openai/gpt-oss-120b | GROQ_API_KEY_2 (2ª conta) |
| 4ª | Gemini | gemini-3.5-flash-lite | GOOGLE_API_KEY_2 / GOOGLE_API_KEY |
| 5ª | NVIDIA NIM | openai/gpt-oss-20b | NVIDIA_API_KEY |
| 6ª | Fallback numérico | top 20 do ranking Python → A | — |

> Nota de modelos (verificado em 2026-09): a NVIDIA descontinuou `meta/llama-3.3-70b-instruct` (EOL 2026-08-26); o substituto vivo no endpoint gratuito é `openai/gpt-oss-20b` (o `gpt-oss-120b` não é servido pela NVIDIA).

### Lotes

- **Tamanho:** 15 candidatos por lote
- **Pausa:** 3 segundos entre lotes
- Toda resposta é validada integralmente (IDs 1..N, cluster A/B, score 0..100, justificativa) antes de ser aceita.
- **199 imóveis = 10 lotes**

### O que a LLM recebe

Para cada lote:
- Características do imóvel alvo (tipo, área, quartos, banheiros, vagas, preço, bairro, rua, descrição)
- Características de cada candidato (mesmos campos + amenities, condomínio, IPTU, terreno)
- Critérios de avaliação imobiliária

### O que a LLM retorna

Para cada imóvel:
- `cluster`: "A" (comparável) ou "B" (não comparável)
- `score_similaridade`: 0-100
- `ranking`: posição 1-N (sem empates)
- `justificativa`: frase curta

### Critérios da LLM

**Eliminatórios (→ Cluster B):**
- Tipo incompatível (apartamento vs terreno)
- Uso diferente (comercial vs residencial)
- Área >2× ou <½ do alvo
- Padrão claramente incompatível (kitnet vs cobertura luxo)

**Principais (ordem de importância):**
1. Tipo do imóvel
2. Localização (mesmo bairro)
3. Área (±50% aceitável)
4. Quartos (±1 aceitável)

**NÃO eliminatórios:**
- Preço (pode estar sub/superavaliado)
- Diferença de 1 banheiro/vaga/suíte
- Dados ausentes

### Fallback numérico (se LLM falhar)

```
score ≥ 0.60 → Cluster A
score < 0.60 → Cluster B
ranking = posição no score
```

---

## ETAPA 4 — Zona Homogênea

Valida geograficamente quais imóveis estão na mesma vizinhança.

### Passo a passo

1. **Geocodifica** o endereço do alvo (Nominatim → lat/lng; fallback: Google Geocoding)
2. **Gera imagem** de satélite (Google Maps Static API, hybrid, 1280×1280, scale=2, marcador vermelho)
3. **LLM de visão** analisa a imagem e retorna (cadeia: Qwen Colab → Groq qwen3.8-27b → Gemini → NVIDIA visão → fallback de raio):
   - padrão construtivo, homogeneidade visual, densidade urbana, transição visual
   - **raio sugerido** livre em metros + justificativa
   - descrição da zona e confiança
   - A resposta só é aceita se trouxer **todos os 8 campos** obrigatórios preenchidos; caso contrário, tenta o próximo provider (mesmo rigor do clustering). O Groq usa JSON Schema Mode.
4. **Usa lat/lon do Athena** direto para cada imóvel (não geocodifica de novo)
5. **Calcula distância** (Haversine) de cada imóvel ao alvo
6. **Classifica:**
   - `na_zona` = distância ≤ raio sugerido
   - `fora_zona` = distância > raio
   - `zona_nao_verificada` = sem coordenadas nem geocodificação (não assume na_zona)
7. **Cluster A + terrenos** vão para validação geográfica (Cluster B não vai)

### Raio livre com barreira de sanidade

A LLM escolhe o raio livremente (437, 615, 882, 1340...). Não há lista fixa. Só aplicamos uma barreira de sanidade para evitar valores absurdos por erro de geração: valores abaixo de **100m** sobem para 100m e acima de **3000m** descem para 3000m. Raio inválido (≤ 0) cai no fallback de 500m.

---

## Saída

### `data/imoveis_comparaveis_ag2.json`

```json
{
  "imovel_alvo": { ... },
  "comparaveis": [
    {
      "cluster": "A",
      "score_similaridade": 0.92,
      "ranking_llm": 1,
      "justificativa": "Area e quartos proximos, mesmo bairro...",
      // + todos os campos originais do imóvel
    },
    {
      "cluster": "B",
      "score_similaridade": 0.35,
      "ranking_llm": 15,
      "justificativa": "Area muito diferente..."
    },
    {
      "cluster": "terreno",
      "score_similaridade": null,
      "ranking_llm": null,
      "justificativa": "Terreno excluido do ranking"
    }
  ],
  "terrenos": [ ... ],
  "resumo": {
    "total_analisados": 199,
    "cluster_a": 75,
    "cluster_b": 124,
    "terrenos_excluidos": 0,
    "metodo": "similaridade_numerica + clustering_llm"
  }
}
```

**Usado por:** Agente 3 (fallback se zona_homogenea não existir)

### `data/zona_homogenea_ag2.json`

```json
{
  "zona_homogenea": {
    "raio_sugerido_metros": 700,
    "padrao_construtivo": "predios_baixos",
    "homogeneidade_visual": "media",
    "densidade_urbana": "alta",
    "justificativa_raio": "...",
    "confianca": "media"
  },
  "comparaveis_confirmados": [
    {
      "cluster": "A",
      "classificacao_zona": "na_zona",
      "distancia_metros": 250,
      // + todos os campos do imóvel
    }
  ],
  "fora_zona": [ ... ],
  "coordenadas_alvo": { "lat": -22.884, "lon": -47.059 }
}
```

O JSON também traz `terrenos_confirmados`, `terrenos_fora_zona` e `terrenos_nao_verificados`. Os terrenos confirmados são incluídos em `comparaveis_confirmados` (o Agente 5 separa por tipo ao ler).

**Usado por:**
- **Agente 3** → pega `comparaveis_confirmados` com cluster=A + na_zona → analisa fotos/descrição
- **Agente 4** → pega `coordenadas_alvo` (lat/lon) → busca POIs no entorno
- **Agente 5** → pega `comparaveis_confirmados` (construídos + terrenos validados na zona) → calcula preço

> Isolamento por `run_id`: quando uma avaliação usa `run_id`, o Agente 2 lê a entrada **apenas** da pasta daquela execução. Nunca cai no arquivo global, evitando misturar dados de avaliações diferentes.

### `data/satelite_zona_homogenea_ag2.png`

Imagem de satélite 1280×1280px com marcador vermelho no imóvel alvo.

**Usado por:** Interface Streamlit (exibe pro usuário)

---

## Resultado de Teste (Cambuí, Campinas/SP — apartment 89m²)

```
Total analisados: 199
Cluster A (similares): 75
Cluster B (não similares): 124
Terrenos excluídos: 0
Método: similaridade_numerica + clustering_llm

10 lotes de 20 processados:
  Lotes 1-7: Groq 1 (com retries automáticos em rate limit)
  Lotes 8-9: Groq 1 falhou → GROQ_API_KEY_2 assumiu ✅
  Lote 10: Groq 1 OK
  Gemini: não precisou ser acionado
  Fallback numérico: 0 lotes (todos respondidos pela LLM)

Tempo total: ~4 min
```

---

## Dependências

| Serviço | Modelo | Uso | Configuração |
|---|---|---|---|
| Groq | openai/gpt-oss-120b | Clustering semântico | `GROQ_API_KEY` + `GROQ_API_KEY_2` |
| NVIDIA NIM | openai/gpt-oss-20b | Fallback clustering (texto) | `NVIDIA_API_KEY` |
| Gemini | gemini-3.5-flash-lite | Fallback clustering + visão | `GOOGLE_API_KEY_2` / `GOOGLE_API_KEY` |
| Qwen3-VL-8B | Colab | Visão zona (1º) + clustering (1º) | `QWEN_API_URL` + `QWEN_API_KEY` |
| Groq | qwen/qwen3.8-27b | Análise visual satélite | `GROQ_API_KEY` |
| NVIDIA NIM | meta/llama-3.2-11b-vision-instruct | Análise visual satélite (fallback) | `NVIDIA_API_KEY` |
| Google Maps Static API | — | Imagem de satélite | `GOOGLE_MAPS_KEY` |
| Nominatim (OpenStreetMap) | — | Geocodificação (grátis) | — |
| Google Geocoding API | — | Geocodificação (fallback) | `GOOGLE_MAPS_KEY` |

---

## Como Rodar

```bash
# Teste isolado (usa dados já coletados pelo Agente 1)
.venv/Scripts/python.exe tests/test_ag2_isolado.py

# Pipeline completo
.venv/Scripts/python.exe -m app.main
```
