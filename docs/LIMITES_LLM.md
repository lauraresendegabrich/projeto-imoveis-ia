# Limites das LLMs — Consumo e Capacidade

## Resumo de Limites (Free Tier)

| Serviço | Modelo | Limite diário | Limite por minuto | Configuração |
|---------|--------|---------------|-------------------|--------------|
| Groq (conta 1) | llama-3.3-70b-versatile | 100.000 tokens/dia | 12.000 tokens/min | GROQ_API_KEY |
| Groq (conta 2) | llama-3.3-70b-versatile | 100.000 tokens/dia | 12.000 tokens/min | GROQ_API_KEY_2 |
| Groq (qualquer conta) | qwen3.6-27b (visão) | Compartilha limite da conta | 8.000 tokens/min | GROQ_API_KEY |
| Gemini | gemini-3.5-flash-lite | **500 requests/dia** | 15 req/min, 250k tokens/min | GOOGLE_API_KEY_2 |
| NVIDIA NIM | llama-3.2-11b-vision | Sem limite diário | ~5 req/min | NVIDIA_API_KEY |

**Total disponível por dia:** 200.000 tokens Groq + 500 req Gemini + NVIDIA ilimitado

---

## Consumo por Avaliação Completa (~200 imóveis)

| Agente | O que consome | Requests/tokens estimados |
|--------|---------------|---------------------------|
| Agente 2 (clustering) | 10 lotes × ~6.000 tokens | ~60.000 tokens Groq |
| Agente 2 (zona homogênea) | 1 chamada visão | ~2.000 tokens Groq (qwen3.6-27b) |
| Agente 3 (alvo) | 1 chamada multimodal | 1 request Gemini |
| Agente 3 (comparáveis) | 20 imóveis × 1 chamada | 20 requests Gemini |
| Agente 4 (interpretação) | 1 chamada | ~1.000 tokens Groq |
| **Total por avaliação** | | **~63.000 tokens Groq + 21 requests Gemini** |

---

## Quantas Avaliações por Dia

| Cenário | Avaliações/dia | Observação |
|---------|----------------|------------|
| Gemini como limitante | **~23** | 500 req ÷ 21 req/avaliação |
| Groq como limitante | ~3 | 200k tokens ÷ 63k tokens/avaliação |
| **Na prática** | **16-23** | Gemini faz a visão, Groq faz o clustering |

**Antes (gemini-2.5-flash, 20 req/dia):** 1 avaliação esgotava tudo
**Agora (gemini-3.5-flash-lite, 500 req/dia):** 16-23 avaliações por dia

---

## Cadeia de Fallback (ordem de tentativa)

```
Agente 2 (clustering):
  1. Groq conta 1 (GROQ_API_KEY) — llama-3.3-70b-versatile
  2. Groq conta 2 (GROQ_API_KEY_2) — llama-3.3-70b-versatile
  3. Gemini (GOOGLE_API_KEY) — gemini-3.5-flash-lite
  4. Fallback numérico (score ≥ 0.60 → Cluster A)

Agente 2 (zona homogênea — visão):
  1. Groq (GROQ_API_KEY) — qwen3.6-27b (max 4096 tokens saída)

Agente 3 (análise visual — fotos):
  1. Gemini (GOOGLE_API_KEY_2) — gemini-3.5-flash-lite (até 8 fotos)
  2. Groq (GROQ_API_KEY) — qwen3.6-27b (até 3 fotos, 8k tokens/min)
  3. NVIDIA NIM (NVIDIA_API_KEY) — llama-3.2-11b-vision (1 foto por vez, ~25-130s)
  4. Score neutro 0.50

Agente 4 (interpretação textual):
  1. Groq (GROQ_API_KEY) — llama-3.1-8b-instant (sempre funciona, consome pouco)
```

---

## Quando os Limites Resetam

| Serviço | Reset |
|---------|-------|
| Groq (tokens por dia) | Meia-noite UTC (~21h Brasília) |
| Groq (tokens por minuto) | A cada 60 segundos |
| Gemini (requests por dia) | Meia-noite Pacific Time (~4h Brasília) |

---

## Chaves de API por Agente

| Chave | Agente | Uso |
|-------|--------|-----|
| `AWS_ACCESS_KEY_ID` + `SECRET` + `REGION` | Ag.1 | Consulta Athena (banco S3) |
| `APIFY_TOKEN_2` | Ag.1 (fallback) | Scraping portais se Athena < 10 |
| `GROQ_API_KEY` | Ag.2, Ag.3 (fallback), Ag.4 | Clustering, zona visão, interpretação |
| `GROQ_API_KEY_2` | Ag.2 (fallback) | Quando 1ª conta Groq esgota |
| `GOOGLE_API_KEY` | Ag.2 (fallback clustering) | Gemini texto |
| `GOOGLE_API_KEY_2` | Ag.3 (principal) | Gemini multimodal (fotos) |
| `NVIDIA_API_KEY` | Ag.3 (fallback final) | NVIDIA NIM visão |
| `GOOGLE_MAPS_KEY` | Ag.2, Ag.4 | Imagem satélite + geocoding |

---

## Como Economizar Quotas

1. **Gemini agora tem 500 req/dia** — não precisa mais se preocupar tanto
2. **Groq é o gargalo** (100k tokens/dia por conta) — 2 contas = ~3 avaliações de clustering
3. **Se Groq esgotar:** Gemini assume o clustering (consome da quota de 500)
4. **Horário:** limites Groq resetam ~21h Brasília, Gemini ~4h Brasília
5. **Não rodar > 3x seguidas** — o clustering consome muitos tokens Groq

---

## Modelos Utilizados

| Modelo | Provider | Tipo | Usado em |
|--------|----------|------|----------|
| llama-3.3-70b-versatile | Groq | Texto | Ag.2 clustering |
| qwen3.6-27b | Groq | Visão (imagem) | Ag.2 zona homogênea |
| gemini-3.5-flash-lite | Google | Multimodal (texto+imagem) | Ag.3 fotos, Ag.2 fallback |
| llama-3.2-11b-vision | NVIDIA NIM | Visão (1 foto) | Ag.3 fallback final |
| llama-3.1-8b-instant | Groq | Texto | Ag.4 interpretação |
