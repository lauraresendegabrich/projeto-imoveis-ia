# Limites das LLMs — Consumo e Capacidade

## Resumo de Limites (Free Tier)

| Serviço | Modelo | Limite diário | Limite por minuto | Configuração |
|---------|--------|---------------|-------------------|--------------|
| Groq (conta 1) | llama-3.3-70b-versatile | 100.000 tokens/dia | 12.000 tokens/min | GROQ_API_KEY |
| Groq (conta 2) | llama-3.3-70b-versatile | 100.000 tokens/dia | 12.000 tokens/min | GROQ_API_KEY_2 |
| Groq (qualquer conta) | qwen3.6-27b (visão) | Compartilha limite da conta | — | GROQ_API_KEY |
| Gemini | gemini-2.5-flash | 20 requests/dia | — | GOOGLE_API_KEY |
| NVIDIA NIM | llama-3.2-11b-vision | Sem limite diário | ~5 req/min | NVIDIA_API_KEY |

**Total disponível por dia:** 200.000 tokens Groq + 20 req Gemini + NVIDIA ilimitado

---

## Consumo por Avaliação Completa (~200 imóveis)

| Agente | O que consome | Tokens/requests estimados |
|--------|---------------|---------------------------|
| Agente 2 (clustering) | 9-10 lotes × ~6.000 tokens | ~55.000 tokens Groq |
| Agente 2 (zona homogênea) | 1 chamada visão | ~1.000 tokens Groq (qwen3.6-27b) |
| Agente 3 (análise fotos) | 20 imóveis × 1 chamada | 20 requests Gemini OU ~20.000 tokens Groq |
| Agente 4 (interpretação) | 1 chamada | ~1.000 tokens Groq |
| **Total por avaliação** | | **~57.000-77.000 tokens Groq + 20 req Gemini** |

---

## Quantas Avaliações por Dia

| Cenário | Avaliações/dia | Observação |
|---------|----------------|------------|
| Só Groq 1 (100k tokens) | ~1-2 | Esgota rápido se testar várias vezes |
| Groq 1 + Groq 2 (200k tokens) | ~3 | Sem fallback numérico |
| Groq 1 + Groq 2 + Gemini | ~3-4 | Gemini cobre quando Groq esgota |
| Com fallback numérico | Ilimitado | Lotes excedentes usam score ≥ 0.60 |

**Para demonstração ao professor:** 2-3 avaliações por dia sem problema.

**Para testes repetidos:** Espaçar ao longo do dia ou usar no dia seguinte (limites resetam à meia-noite UTC).

---

## Cadeia de Fallback (ordem de tentativa)

```
Agente 2 (clustering):
  1. Groq conta 1 (GROQ_API_KEY)
  2. Groq conta 2 (GROQ_API_KEY_2)
  3. Gemini (GOOGLE_API_KEY)
  4. Fallback numérico (score ≥ 0.60 → Cluster A)

Agente 3 (análise visual):
  1. Gemini 2.5 Flash (até 8 fotos)
  2. Groq qwen3.6-27b (até 3 fotos)
  3. NVIDIA NIM llama-3.2-11b (1 foto por vez, ~90s)
  4. Score neutro 0.50

Agente 4 (interpretação):
  1. Groq llama-3.1-8b-instant (sempre funciona, consome pouco)
```

---

## Quando os Limites Resetam

| Serviço | Reset |
|---------|-------|
| Groq (tokens por dia) | Meia-noite UTC (~21h Brasília) |
| Groq (tokens por minuto) | A cada 60 segundos |
| Gemini (requests por dia) | Meia-noite Pacific Time (~4h Brasília) |

---

## Resultado Real do Teste (Barueri/SP — 13/08/2026)

```
175 imóveis para análise + 65 terrenos = 240 total

Agente 2 (clustering):
  Lotes 1-2: Groq 1 OK
  Lotes 3-6: Groq 1 esgotou → Groq 2 respondeu
  Lote 7: Groq 1+2 esgotaram → Gemini respondeu
  Lotes 8-9: TUDO esgotado → fallback numérico
  Resultado: 129 similares | 46 não similares

Zona Homogênea:
  Groq Vision (qwen3.6-27b) OK → raio 700m
  99 na zona | 95 fora

Consumo total estimado desta execução:
  Groq 1: ~12.000 tokens (2 lotes)
  Groq 2: ~30.000 tokens (4 lotes + retries)
  Gemini: 1 request (lote 7)
  Fallback: 2 lotes (35 imóveis por score numérico)
```

---

## Como Economizar Tokens

1. **Não rodar várias vezes no mesmo dia** — os limites são diários
2. **Usar cache:** se os dados do Agente 1 não mudaram, o Agente 2 pode reusar o resultado anterior
3. **Testar localmente:** rodando no computador, o consumo é o mesmo mas não gasta o deploy do Streamlit
4. **Horário:** se precisa de mais capacidade, usar após 21h Brasília (reset do Groq)

---

## Upgrade (se necessário no futuro)

| Serviço | Plano | Custo | Capacidade |
|---------|-------|-------|------------|
| Groq Dev Tier | On-demand | $10/mês | 1.000.000 tokens/dia |
| Gemini Pay-as-you-go | Por uso | ~$0.001/req | Sem limite diário |
| NVIDIA NIM | Free | Gratuito | Sem limite |
