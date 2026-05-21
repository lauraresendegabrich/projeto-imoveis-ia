# Agente 4 — Avaliador de Infraestrutura

## Objetivo

Analisar o entorno do imóvel alvo buscando pontos de interesse (POIs) em três faixas de distância via OpenStreetMap (osmnx). Calcula um score de infraestrutura urbana e classifica o perfil da região, gerando um fator de impacto no valor do imóvel.

---

## Problema Central

A localização influencia diretamente o valor de um imóvel, mas de forma diferente dependendo do tipo de infraestrutura. Uma escola a 300m é mais relevante do que uma a 1km. Um hospital não precisa estar a 400m para valorizar o imóvel — basta estar acessível. O agente resolve isso com análise multifaixa com pesos diferenciados por categoria e distância.

---

## Histórico de Decisões

### 1. Google Places API vs OpenStreetMap
**Google Places:** cobertura excelente para cidades brasileiras, mas custa $17/1.000 requests. Requer faturamento ativo no Google Cloud.

**OpenStreetMap via Overpass API:** gratuito, sem key, sem cadastro. Testamos os servidores públicos (`overpass-api.de`, `overpass.kumi.systems`, `maps.mail.ru`) — todos retornaram erros 406/403/timeout durante os testes.

**Solução adotada:** usar a biblioteca `osmnx`, que acessa o OSM de forma mais robusta com retry automático e cache local. Resolveu o problema de instabilidade dos servidores públicos.

**Cobertura do OSM em Itajaí:** o mapa tem dados da cidade (confirmado no site do OSM), mas a cobertura de alguns tipos de POI é menor que o Google Places. Isso é documentado como limitação.

### 2. Raio fixo vs multifaixa
**Raio fixo (descartado):** usar um único raio (ex: 500m) é impreciso. Em centros urbanos densos, 500m pode incluir regiões com padrão diferente. Além disso, hospital e universidade não precisam estar a 500m para valorizar o imóvel.

**Multifaixa adotada:** três faixas com pesos diferentes por categoria:
- 0–400m: microentorno imediato (~5 min a pé) — comércio, escola, farmácia, transporte, lazer
- 401–800m: entorno caminhável (~10 min a pé) — supermercados, hospitais, universidades
- 801–1500m: infraestrutura regional (~15-20 min a pé) — hospitais, shoppings, universidades

### 3. Tolerância de 5% nos limites de faixa
**Problema:** um POI a 408m seria excluído da faixa 0–400m, mesmo estando praticamente no limite.

**Solução:** tolerância de 5% — limite de 400m aceita até 420m. A distância real é mantida no JSON.

### 4. Transporte público: tags expandidas
**Problema inicial:** a busca por `highway=bus_stop` retornava 0 paradas em Itajaí, levando o agente a classificar transporte como "dados_insuficientes" e aplicar score neutro.

**Causa:** o OSM de Itajaí usa outras tags para paradas de ônibus além de `highway=bus_stop`.

**Solução:** expandir as tags buscadas:
- `highway=bus_stop`
- `public_transport=platform`
- `public_transport=stop_position`
- `amenity=bus_station`
- `route=bus` (rotas)
- `route_master=bus`

**Resultado:** 54 paradas encontradas no Centro de Itajaí. Status mudou de "dados_insuficientes" para "servido", score de transporte subiu para 1.00.

### 5. Classificação do perfil da região
**Problema:** o LLM às vezes retornava "residencial_servido" para regiões com alta infraestrutura educacional, hospitalar e universitária.

**Solução:** regra explícita no prompt e no código: se score >= 0.70 com alta pontuação em educação, saúde, hospital e grandes equipamentos → `regiao_mista_com_alta_infraestrutura`.

### 6. Impacto no valor: positivo_forte vs positivo_moderado
**Problema:** o LLM classificava como "positivo_forte" mesmo quando comércio e lazer tinham scores baixos.

**Solução:** regra no código Python (não no LLM): `positivo_forte` só se TODAS as categorias tiverem score >= 0.70. Se comércio ou lazer forem baixos → forçar `positivo_moderado`.

### 7. Limitação OSM sempre presente
**Decisão:** mesmo quando o resultado é bom, sempre incluir a observação: "Nenhuma limitação crítica foi identificada no teste, mas os resultados dependem da completude dos dados disponíveis no OpenStreetMap." O OSM é colaborativo e a cobertura varia por região.

---

## Fluxo Completo

```
1. Carrega imovel_alvo de imoveis_analisados_ag3.json

2. Geocodifica o endereço do alvo
   → Nominatim (OpenStreetMap) — gratuito, sem key
   → Fallback: Google Geocoding API (GOOGLE_MAPS_KEY no .env)

3. Busca POIs via osmnx em uma única query até 1500m
   → Classifica cada POI na faixa correta pela distância real
   → Sem duplicação entre faixas
   → Tolerância de 5% nos limites

4. Busca transporte público com tags expandidas (separado)
   → highway=bus_stop, public_transport=platform/stop_position
   → amenity=bus_station, route=bus, route_master=bus
   → Classifica: servido | possui_indicios_de_atendimento | dados_insuficientes

5. Calcula score multifaixa por categoria com pesos diferenciados

6. Envia resumo para LLM (llama-3.1-8b-instant) classificar perfil e impacto

7. Python aplica regras de classificação (positivo_forte só se todas >= 0.70)

8. Salva em data/infra_avaliada_ag4.json
```

---

## Faixas e Categorias

| Categoria | 0–400m | 401–800m | 801–1500m | Justificativa |
|---|:-:|:-:|:-:|---|
| comercio | 1.0 | 0.6 | — | Precisa estar perto |
| educacao | 1.0 | 0.6 | — | Escola próxima é diferencial |
| saude_basica | 1.0 | 0.6 | — | Farmácia/clínica: uso cotidiano |
| transporte | 1.0 | 0.6 | — | Quanto mais perto melhor |
| lazer | 1.0 | 0.6 | — | Parque/academia: uso frequente |
| hospital | — | 0.6 | 1.0 | Não precisa estar a 400m |
| grande_equipamento | — | 0.6 | 1.0 | Shopping/universidade: regional |

---

## Cálculo do Score

```
score_categoria = sum(qtd_faixa × peso_faixa) / normalizador
score_categoria = min(score_categoria, 1.0)
score_final = média dos scores por categoria
```

**Normalizadores** (qtd esperada para score=1.0):
- comercio: 5 | educacao: 3 | saude_basica: 4 | transporte: 6
- lazer: 3 | hospital: 2 | grande_equipamento: 2

**Transporte especial:**
- status=servido → score calculado normalmente
- status=possui_indicios → score=0.4
- status=dados_insuficientes → score=0.5 (neutro, sem penalização)

---

## Classificação do Perfil

| Perfil | Quando usar |
|---|---|
| `regiao_mista_com_alta_infraestrutura` | score >= 0.70 com alta pontuação em educação, saúde, hospital e grandes equipamentos |
| `residencial_com_alta_infraestrutura` | score >= 0.70 predominantemente residencial |
| `residencial_servida` | score 0.50–0.69 com serviços essenciais |
| `regiao_pouco_servida` | score < 0.50 |

## Classificação da Infraestrutura

| Score | Classificação |
|---|---|
| >= 0.80 | excelente |
| >= 0.65 | boa |
| >= 0.45 | regular |
| < 0.45 | insuficiente |

## Impacto no Valor

| Condição | Impacto |
|---|---|
| Todas as categorias >= 0.70 | positivo_forte |
| Score >= 0.70 mas alguma categoria < 0.70 | positivo_moderado |
| Score 0.50–0.69 | neutro |
| Score < 0.50 | negativo_moderado ou negativo_forte |

---

## Arquivos Gerados

| Arquivo | Conteúdo |
|---|---|
| `data/infra_avaliada_ag4.json` | Análise completa: POIs por faixa, transporte, scores, perfil, impacto |

---

## Schema de Saída

```json
{
  "imovel_alvo": { ... },
  "coordenadas": { "lat": -26.911896, "lon": -48.664273 },
  "faixas_metros": {
    "microentorno_imediato": "0-400m",
    "entorno_caminhavel": "401-800m",
    "infraestrutura_ampliada": "801-1500m"
  },
  "tolerancia_pct": 5.0,
  "pois_por_faixa": { ... },
  "transporte": {
    "paradas": [...],
    "estacoes": [],
    "rotas": [],
    "status": "servido"
  },
  "scores": {
    "comercio": 0.36,
    "educacao": 1.00,
    "saude_basica": 1.00,
    "transporte": 1.00,
    "lazer": 0.60,
    "hospital": 0.90,
    "grande_equipamento": 1.00,
    "score_final": 0.837,
    "transporte_status": "servido"
  },
  "resumo_scores": {
    "score_final": 0.837,
    "classificacao_infraestrutura": "excelente",
    "perfil_regiao": "regiao_mista_com_alta_infraestrutura",
    "impacto_estimado_no_valor": "positivo_moderado",
    "pontos_fortes": [...],
    "pontos_de_atencao": [...],
    "limitacoes": [...]
  },
  "analise_llm": { ... }
}
```

---

## Resultado dos Testes (Centro de Itajaí/SC — maio 2026)

```
Faixas:
  0–400m:    5 POIs (2 escolas, 3 saúde)
  401–800m: 27 POIs (10 educação, 6 saúde, 3 hospitais, 3 lazer, 3 comércio, 2 universidades)
  801–1500m: 1 POI  (Uniasselvi 1555m — aceito pela tolerância de 5%)

Transporte: 54 paradas encontradas (tags expandidas) — status=servido

Scores:
  educacao:           1.00
  saude_basica:       1.00
  transporte:         1.00
  grande_equipamento: 1.00
  hospital:           0.90
  lazer:              0.60
  comercio:           0.36
  score_final:        0.84

Classificação: excelente
Perfil:        regiao_mista_com_alta_infraestrutura
Impacto:       positivo_moderado
  (comércio 0.36 e lazer 0.60 impedem positivo_forte)
```

---

## Dependências Externas

| Serviço | Uso | Custo | Configuração |
|---|---|---|---|
| osmnx | Busca de POIs via OSM | Gratuito | `pip install osmnx` |
| Nominatim (OSM) | Geocodificação principal | Gratuito, sem key | Sem configuração |
| Google Geocoding API | Fallback de geocodificação | Gratuito (10.000/mês) | `GOOGLE_MAPS_KEY` no `.env` |
| Groq (llama-3.1-8b-instant) | Análise do perfil da região | Gratuito (14.400 req/dia) | `GROQ_API_KEY` no `.env` |

---

## Instalação das Dependências

```bash
.venv/Scripts/pip install osmnx langchain-groq
```

## Como Rodar

```bash
.venv/Scripts/python.exe -m tests.test_infra_evaluator
```

**Pré-requisitos:**
- `data/imoveis_analisados_ag3.json` gerado pelo Agente 3
- `GROQ_API_KEY` no `.env`
- `GOOGLE_MAPS_KEY` no `.env` (opcional — fallback de geocodificação)
