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
ETAPA 3 — Clustering via LLM (Groq llama-3.3-70b)
ETAPA 4 — Zona Homogênea (Google Maps + Groq qwen3.6-27b)
```

---

## ETAPA 1 — Separação de Terrenos

Antes de qualquer análise, separa terrenos dos construídos:

- **Terrenos** (`propertyType == "Terrenos"`) → NÃO entram no ranking/LLM
- **Casas/Apartamentos** → seguem para score + clustering

Por quê: não faz sentido comparar terreno vazio com casa construída. Score numérico seria distorcido (terreno não tem quartos, banheiros, vagas).

Os terrenos ficam no resultado final com `cluster="terreno"` e vão para a zona homogênea (validação geográfica é relevante pra qualquer tipo).

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
| 1ª | Groq | llama-3.3-70b-versatile | GROQ_API_KEY |
| 2ª | Groq | llama-3.3-70b-versatile | GROQ_API_KEY_2 (2ª conta) |
| 3ª | Gemini | gemini-2.5-flash | GOOGLE_API_KEY |
| 4ª | Fallback numérico | score ≥ 0.60 → A | — |

### Lotes

- **Tamanho:** 20 candidatos por lote (~6.000 tokens, metade do limite Groq)
- **Pausa:** 5 segundos entre lotes
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
3. **Groq (qwen3.6-27b)** analisa a imagem visualmente e retorna:
   - padrão construtivo, homogeneidade visual, densidade urbana
   - **raio sugerido** em metros (300-1500m)
   - justificativa e confiança
4. **Usa lat/lon do Athena** direto para cada imóvel (não geocodifica de novo)
5. **Calcula distância** (Haversine) de cada imóvel ao alvo
6. **Classifica:**
   - `na_zona` = distância ≤ raio sugerido
   - `fora_zona` = distância > raio
7. **Só envia Cluster A + terrenos** para validação (Cluster B não vai)
8. **Sem localização verificável = fora_zona** (não assume na_zona)

### Raio mínimo

Mesmo que a LLM sugira raio menor, aplica mínimo de 400m. Evita excluir comparáveis a poucos quarteirões em centros densos.

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

**Usado por:**
- **Agente 3** → pega `comparaveis_confirmados` com cluster=A + na_zona → analisa fotos/descrição
- **Agente 4** → pega `coordenadas_alvo` (lat/lon) → busca POIs no entorno
- **Agente 5** → pega `comparaveis_confirmados` + terrenos → calcula preço

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
| Groq | llama-3.3-70b-versatile | Clustering semântico | `GROQ_API_KEY` + `GROQ_API_KEY_2` |
| Groq | qwen3.6-27b | Análise visual satélite | `GROQ_API_KEY` |
| Gemini | gemini-2.5-flash | Fallback clustering | `GOOGLE_API_KEY` |
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
