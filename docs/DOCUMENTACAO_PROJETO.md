# Documentação do Projeto — Pipeline Multiagente de Precificação Imobiliária

## Visão Geral

Sistema multiagente que coleta imóveis comparáveis, identifica os mais similares ao imóvel alvo e estima o valor de mercado com base em dados reais de portais imobiliários brasileiros.

---

## Estado Atual do Pipeline

| Agente | Status | Como rodar |
|---|---|---|
| Agente 1 — Coletor | ✅ Implementado e testado | `python -m tests.test_coleta` |
| Agente 2 — Comparáveis | ✅ Implementado e testado | `python -m tests.test_comparaveis` |
| Pipeline (Ag. 1 + 2) | ✅ Conectado em `app/graph.py` | `python app/main.py` |
| Agente 3 — Analisador Textual | ⚠️ Implementado, pendente integração | `python app/main.py` (isolado) |
| Agente 4 — Infraestrutura | ❌ Pendente | — |
| Agente 5 — Preço e Liquidez | ❌ Pendente | — |

### Fluxo funcionando hoje

```
app/main.py
    │
    ▼
app/graph.py → executar_pipeline(imovel_alvo)
    │
    ├── Agente 1 (agents/collector.py)
    │       Apify ocrad → VivaReal + LugarCerto
    │       requests.get → publishedAt + description
    │       ↓ imoveis_completos.json
    │
    ├── Agente 2 (agents/comparables.py)
    │       Separa terrenos
    │       Score numérico de similaridade
    │       Groq LLM → Cluster A / B + ranking
    │       Google Maps + Groq Vision → zona homogênea
    │       ↓ imoveis_comparaveis.json
    │       ↓ zona_homogenea.json
    │       ↓ satelite_zona_homogenea.png
    │
    └── retorna dict com comparaveis, terrenos, zona_homogenea, resumo
```

### Resultado real (Centro de Itajaí/SC — maio 2026)
```
Agente 1:
  95 imóveis coletados (77 casas + 18 terrenos)
  100% com publishedAt
  Tempo: ~4.7 minutos

Agente 2:
  28 casas analisadas (17 terrenos separados)
  14 Cluster A (similares) | 14 Cluster B (não similares)
  Zona homogênea: raio 500m sugerido pelo Groq Vision
  45 na zona | 17 fora da zona
```

---

## Documentação Detalhada por Agente

| Arquivo | Conteúdo |
|---|---|
| `docs/AGENT1_DOCUMENTACAO_COLETOR.md` | Agente 1 — portais testados, ferramentas descartadas, enriquecimento, limites por URL |
| `docs/AGENT2_DOCUMENTACAO_COMPARAVEIS.md` | Agente 2 — score numérico, clustering LLM, zona homogênea, decisão sobre terrenos |

---



```
Agente 1 — Coletor
    ↓  data/imoveis_completos.json
Agente 2 — Comparáveis (ranking + clustering + zona homogênea)
    ↓  data/imoveis_comparaveis.json
    ↓  data/zona_homogenea.json
Agente 3 — Analisador Textual          (implementado, pendente integração)
Agente 4 — Avaliador de Infraestrutura (pendente)
Agente 5 — Estimador de Preço          (pendente)
```

---

## Agente 1 — Coletor (`agents/collector.py`)

### O que faz
Coleta imóveis comparáveis nos portais imobiliários brasileiros via Apify (actor `ocrad/brazil-real-estate-scraper`) e enriquece os dados com `publishedAt` e `description` via `requests.get`.

### Portais ativos
| Portal | Coleta | publishedAt | Motivo |
|---|:-:|:-:|---|
| VivaReal | ✅ | ✅ | Principal fonte — dados completos no HTML estático |
| LugarCerto | ✅ | ✅ | Fonte secundária |
| OLX | ❌ comentado | ❌ | Cloudflare bloqueia `requests.get` — sem publishedAt |
| ImovelWeb | ❌ comentado | — | Actor não extrai resultados |
| MercadoLivre | ❌ comentado | — | Actor não extrai resultados |
| ZAP Imóveis | ❌ removido | — | 95% duplicata do VivaReal (mesmo grupo) |

### Limites por URL (definidos em `_montar_urls_listagem`)
| Tipo | Limite |
|---|---|
| Casa | 20 itens por URL |
| Terreno | 10 itens por URL |
| Apartamento | 30 itens por URL |

### Arquivos gerados
| Arquivo | Conteúdo |
|---|---|
| `data/imoveis_brutos_ocrad.json` | Brutos do actor (schema original) |
| `data/imoveis_coletados.json` | Normalizados e filtrados (todos) |
| `data/imoveis_completos.json` | Só imóveis com publishedAt |

### Como rodar
```bash
.venv/Scripts/python.exe -m tests.test_coleta
```

### Dependências externas
- **Apify** — `APIFY_TOKEN_2` no `.env` (gratuito, $5/mês de crédito)
  - Criar em: https://console.apify.com → Settings → Integrations → API tokens

---

## Agente 2 — Comparáveis (`agents/comparables.py`)

### O que faz
Recebe os imóveis do Agente 1 e identifica quais são realmente comparáveis ao imóvel alvo usando três etapas combinadas.

### Etapa 1 — Similaridade Numérica
Score de 0.0 a 1.0 calculado por distância relativa entre alvo e candidato:
| Campo | Peso |
|---|---|
| Área (m²) | 30% |
| Quartos | 25% |
| Preço/m² | 20% |
| Banheiros | 15% |
| Vagas | 10% |

### Etapa 2 — Clustering via LLM (Groq, llama-3.3-70b-versatile)
- **Terrenos são separados antes** — tipo incomparável com imóvel construído (score distorcido sem quartos/banheiros/vagas)
- Apenas casas/apartamentos são enviados para a LLM clusterizar e ranquear
- LLM retorna: `cluster` (A = similar, B = não similar), `ranking_llm`, `justificativa`
- Terrenos entram no resultado final com `cluster="terreno"` e `ranking_llm=null`
- Terrenos **são enviados para a Etapa 3** (zona homogênea) — validação geográfica é relevante independente do tipo

**Fallback** (se LLM falhar): usa só o score numérico — score ≥ 0.60 → Cluster A

### Etapa 3 — Zona Homogênea (Google Maps + Groq Vision)
1. Geocodifica o endereço do alvo (Nominatim → lat/lng; fallback: Google Geocoding API)
2. Google Maps Static API gera imagem hybrid 1280×1280 scale=2 com marcador vermelho
3. Groq Vision (Llama 4 Scout 17B) analisa a imagem e retorna: `tipo_regiao`, `uso_predominante`, `padrao_construtivo`, `densidade_urbana`, `homogeneidade_visual`, `raio_sugerido_metros`, `confianca`, `limitacoes`
4. Geocodifica cada imóvel e calcula distância (fórmula de Haversine)
5. Classifica: `na_zona` (até o raio sugerido pela LLM) ou `fora_zona` (acima)

### Arquivos gerados
| Arquivo | Conteúdo |
|---|---|
| `data/imoveis_comparaveis.json` | Ranking completo com cluster, score, justificativa e terrenos |
| `data/zona_homogenea.json` | Resultado da validação geográfica |
| `data/satelite_zona_homogenea.png` | Imagem de satélite da região do alvo |

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

### Como rodar
```bash
.venv/Scripts/python.exe -m tests.test_comparaveis
```

### Dependências externas
- **Groq** — `GROQ_API_KEY` no `.env` (gratuito, 14.400 req/dia)
  - Criar em: https://console.groq.com → API Keys
- **Google Maps** — `GOOGLE_MAPS_KEY` no `.env` (gratuito até $200/mês, requer faturamento ativo)
  - APIs necessárias: Maps Static API + Geocoding API
  - Criar em: https://console.cloud.google.com → APIs e Serviços → Credenciais

---

## Agente 3 — Analisador Textual (`agents/text_analyzer.py`)

### O que faz
Analisa a descrição do anúncio com LLM e extrai fatores qualitativos:
- Padrão construtivo (baixo / médio / alto)
- Estado de conservação (ruim / regular / bom / excelente)
- Diferenciais (piscina, varanda, reformado, etc.)
- Impacto estimado no valor e na liquidez

### Status
Implementado e funcional de forma isolada. Pendente integração no pipeline principal (`app/graph.py`).

### Como rodar
```bash
.venv/Scripts/python.exe app/main.py
```

---

## Agentes 4 e 5 — Pendentes

| Agente | Responsabilidade |
|---|---|
| Agente 4 — Infraestrutura | Avalia entorno: escolas, hospitais, comércio via OSM/Google Places |
| Agente 5 — Preço e Liquidez | Consolida tudo e estima preço que maximize a liquidez |

---

## Configuração do Ambiente

### Pré-requisitos
- Python 3.11+ (testado com 3.14)
- Contas nas APIs externas (ver seção de dependências de cada agente)

### Instalação
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pip install langchain-groq langchain-google-genai apify-client openai
```

### Arquivo `.env`
```env
# Apify — coleta de imóveis
APIFY_TOKEN_2=seu_token_apify

# Groq — LLM para clustering e análise textual
GROQ_API_KEY=sua_chave_groq

# Google Maps — imagem de satélite e geocoding (opcional, zona homogênea)
GOOGLE_MAPS_KEY=sua_chave_google

# Google Gemini — LLM alternativo (opcional, fallback do Groq)
# GOOGLE_API_KEY=sua_chave_gemini
```

---

## Estrutura de Arquivos

```
projeto-imoveis-ia/
├── agents/
│   ├── collector.py        # Agente 1 — coleta via Apify
│   ├── comparables.py      # Agente 2 — ranking, clustering, zona homogênea
│   ├── text_analyzer.py    # Agente 3 — análise textual via LLM
│   ├── infra_evaluator.py  # Agente 4 — infraestrutura (pendente)
│   └── price_liquidity.py  # Agente 5 — preço e liquidez (pendente)
├── app/
│   ├── main.py             # Ponto de entrada — roda pipeline (Ag. 1 + 2)
│   └── graph.py            # Orquestrador — conecta os agentes implementados
├── data/
│   ├── imoveis_brutos_ocrad.json       # Brutos do Apify
│   ├── imoveis_coletados.json          # Normalizados (todos)
│   ├── imoveis_completos.json          # Com publishedAt
│   ├── imoveis_comparaveis.json        # Ranking + clusters
│   ├── zona_homogenea.json             # Validação geográfica
│   └── satelite_zona_homogenea.png     # Imagem de satélite
├── docs/
│   ├── DOCUMENTACAO_PROJETO.md              # Este arquivo — visão geral e estado atual
│   ├── AGENT1_DOCUMENTACAO_COLETOR.md       # Agente 1 — detalhes técnicos e decisões
│   └── AGENT2_DOCUMENTACAO_COMPARAVEIS.md   # Agente 2 — detalhes técnicos e decisões
├── services/
│   ├── llm_service.py      # Configuração do LLM (Groq → Gemini → Ollama)
│   └── chroma_service.py   # Serviço de embeddings (pendente)
├── tests/
│   ├── test_coleta.py      # Teste do Agente 1
│   └── test_comparaveis.py # Teste do Agente 2
├── visuals/
│   └── dashboard.py        # Dashboard de visualização (pendente)
├── .env                    # Chaves de API (não versionar)
└── requirements.txt        # Dependências fixadas
```
