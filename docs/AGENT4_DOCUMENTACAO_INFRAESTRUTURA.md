# Agente 4 — Avaliador de Infraestrutura

## Objetivo

Analisa o entorno do imóvel alvo buscando POIs (pontos de interesse) via OpenStreetMap. Calcula score de infraestrutura 100% determinístico. LLM apenas interpreta (não modifica scores).

---

## Entrada

- `data/zona_homogenea_ag2.json` → coordenadas do alvo (lat/lon reutilizadas do Agente 2)
- Endereço do imóvel alvo (rua, número, bairro, cidade, estado)

---

## Fluxo

```
ETAPA 1 — Coordenadas do alvo (reutiliza do Agente 2)
ETAPA 2 — Busca de POIs (osmnx, até 1500m)
ETAPA 3 — Score por categoria (determinístico)
ETAPA 4 — Classificação (determinístico)
ETAPA 5 — Interpretação via LLM (apenas texto, não modifica scores)
```

---

## ETAPA 1 — Coordenadas

Reutiliza lat/lon do Agente 2 (`zona_homogenea_ag2.json`). Se não disponível, geocodifica via Nominatim → fallback Google Geocoding.

---

## ETAPA 2 — Busca de POIs

Busca TODOS os POIs até 1500m numa única query ao osmnx (OpenStreetMap).

Cada POI é classificado por distância real (Haversine) em 3 faixas:

| Faixa | Distância | Significado |
|-------|-----------|-------------|
| 0_400 | 0 a 400m | Microentorno (~5 min a pé) |
| 401_800 | 401 a 800m | Entorno caminhável (~10 min) |
| 801_1500 | 801 a 1500m | Regional (~15-20 min) |

Tolerância de 5% nos limites.

**Transporte:** busca separada com deduplicação espacial inteligente (paradas < 40m com mesmo nome/ref = mesma parada física).

---

## ETAPA 3 — Score por Categoria

8 categorias, cada uma com pesos por faixa:

| Categoria | 0-400m | 401-800m | 801-1500m | Normalizador |
|-----------|--------|----------|-----------|-------------|
| comercio | 1.00 | 0.60 | 0.20 | 5 |
| educacao | 1.00 | 0.70 | 0.30 | 3 |
| saude_basica | 1.00 | 0.65 | 0.25 | 4 |
| transporte | 1.00 | 0.70 | 0.30 | 6 |
| lazer | 1.00 | 0.70 | 0.35 | 3 |
| hospital | 1.00 | 0.90 | 0.70 | 2 |
| equipamentos_regionais | 1.00 | 0.90 | 0.70 | 2 |
| servicos_e_alimentacao | 1.00 | 0.60 | 0.20 | 4 |

### Fórmula

```
poi_efetivo = (qtd_0_400 × peso_0_400) + (qtd_401_800 × peso_401_800) + (qtd_801_1500 × peso_801_1500)
score_categoria = min(1.0, poi_efetivo / normalizador)
score_final = média simples dos 8 scores
```

### Regras especiais

**servicos_e_alimentacao** — limite por subtipo (evita inflação por concentração):
- restaurant: máx 2
- cafe: máx 2
- bank: máx 1
- atm: máx 1

**transporte** — deduplicação espacial:
- Paradas < 40m com mesmo nome/ref = mesma parada → conta 1 vez
- Status "servido" → calcula score normal
- Status "possui_indicios_de_atendimento" → score 0.4
- Status "dados_insuficientes" → score neutro 0.5

---

## ETAPA 4 — Classificação

| Score final | Classificação |
|-------------|---------------|
| < 0.30 | insuficiente |
| 0.30 – 0.49 | basica |
| 0.50 – 0.69 | moderada |
| 0.70 – 0.84 | boa |
| ≥ 0.85 | excelente |

**perfil_infraestrutura** e **impacto_infraestrutura**: calculados em Python (determinístico), NÃO pela LLM.

| Classificação | Perfil | Impacto |
|---------------|--------|---------|
| excelente | infraestrutura_muito_alta | muito_positivo |
| boa | infraestrutura_alta | positivo |
| moderada | infraestrutura_moderada | neutro |
| basica | infraestrutura_basica | negativo |
| insuficiente | infraestrutura_insuficiente | muito_negativo |

---

## ETAPA 5 — Interpretação LLM

A LLM (Groq, llama-3.1-8b-instant) recebe os scores prontos e produz **apenas texto interpretativo**:
- Perfil da região
- Pontos fortes (lista)
- Pontos de atenção (lista)

A LLM **NÃO modifica** nenhum score numérico.

---

## Tags OSM por Categoria

| Categoria | Tags (chave, valor) |
|-----------|---------------------|
| comercio | supermarket, marketplace, bakery, convenience, butcher, greengrocer |
| educacao | school, kindergarten |
| saude_basica | pharmacy, clinic, doctors, dentist |
| transporte | bus_stop, bus_station, platform, stop_position, station |
| lazer | park, fitness_centre, sports_centre, playground |
| hospital | hospital |
| equipamentos_regionais | university, college, mall |
| servicos_e_alimentacao | restaurant, cafe, bank, atm |

---

## Saída

### `data/infra_avaliada_ag4.json`

```json
{
  "scores": {
    "score_final": 1.0,
    "scores_categoria": {
      "comercio": 1.0,
      "educacao": 1.0,
      "saude_basica": 1.0,
      "transporte": 1.0,
      "lazer": 1.0,
      "hospital": 1.0,
      "equipamentos_regionais": 1.0,
      "servicos_e_alimentacao": 1.0
    },
    "detalhes_score": { ... },
    "classificacao_infraestrutura": "excelente",
    "perfil_infraestrutura": "infraestrutura_muito_alta",
    "impacto_infraestrutura": "muito_positivo"
  },
  "interpretacao_llm": {
    "perfil_regiao": "Região urbana consolidada com infraestrutura completa...",
    "pontos_fortes": ["Excelente cobertura de transporte", "..."],
    "pontos_atencao": []
  },
  "metadados": {
    "fonte_infraestrutura": "osmnx/OpenStreetMap",
    "raio_maximo_metros": 1500,
    "total_pois_validos": 371
  }
}
```

---

## Quem usa a saída

| Agente | O que pega | Pra que |
|--------|-----------|---------|
| **Agente 5** | `score_final` | Liquidez experimental (peso 40%) |
| **Interface** | scores por categoria, classificação, pontos fortes/atenção | Exibe pro usuário |

---

## Dependências

| Pacote/Serviço | Uso |
|---|---|
| osmnx | Busca POIs no OpenStreetMap |
| Groq (llama-3.1-8b-instant) | Interpretação textual |
| Nominatim | Geocodificação (grátis) |
| Google Geocoding | Fallback geocodificação |

---

## Resultado do Teste (Cambuí, Campinas)

```
POIs encontrados:
  0_400:    28 POIs
  401_800:  77 POIs
  801_1500: 218 POIs
  Transporte: 61 paradas

Scores:
  comercio:               1.000
  educacao:               1.000
  saude_basica:           1.000
  transporte:             1.000
  lazer:                  1.000
  hospital:               1.000
  equipamentos_regionais: 1.000
  servicos_e_alimentacao: 1.000
  score_final:            1.000

Classificação: excelente
```
