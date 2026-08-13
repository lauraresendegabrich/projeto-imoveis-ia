# Modelos LLM Utilizados no Pipeline

## Resumo Geral

| Agente | Tarefa | Modelo Principal | Fallbacks | Provider |
|--------|--------|-----------------|-----------|----------|
| Ag.2 | Clustering de comparáveis | openai/gpt-oss-120b | gpt-oss-20b → Gemini 2.5 Flash → numérico | Groq |
| Ag.2 | Zona homogênea (visão) | qwen/qwen3.6-27b | fallback regex | Groq |
| Ag.3 | Análise qualitativa (visão) | Gemini 2.5 Flash | qwen/qwen3.6-27b → NVIDIA NIM llama-3.2-11b | Google / Groq / NVIDIA |
| Ag.4 | Interpretação infraestrutura | openai/gpt-oss-20b | — | Groq |

---

## Agente 2 — Clustering (texto)

### Cadeia de fallback:
```
1. openai/gpt-oss-120b (KEY 1)    → 200k tokens/dia
   ↓ se falhar
2. openai/gpt-oss-20b (KEY 1)     → 200k tokens/dia (limite separado)
   ↓ se falhar
3. openai/gpt-oss-120b (KEY 2)    → 200k tokens/dia (outra conta)
   ↓ se falhar
4. Gemini 2.5 Flash               → 20 requests/minuto
   ↓ se falhar
5. Fallback numérico              → score >= 0.60 = A, < 0.60 = B
```

### Detalhes:
- Processa em lotes de 20 imóveis
- Cada lote gasta ~6.000-7.000 tokens
- Total típico: 5-13 lotes = 30k-91k tokens por execução
- Com 400k tokens/dia disponíveis, suporta 4-5 execuções/dia sem esgotar

### Por que GPT-OSS:
- Suporta JSON Object Mode e JSON Schema Mode (respostas estruturadas)
- Limites mais generosos que o Llama antigo (200k vs 100k/dia)
- Recomendado pela Groq como substituto do llama-3.3-70b

---

## Agente 2 — Zona Homogênea (visão)

### Modelo: qwen/qwen3.6-27b (Groq)
- Envia 1 imagem de satélite (1280x1280 JPEG 85%)
- Limite: 20MB por request (imagem fica ~400KB)
- Máximo 5 imagens por request (usa apenas 1)
- Context window: 131k tokens
- Responde com bloco `<think>` antes do JSON — parser remove

### Prompt reduzido (evita truncamento):
- Pede análise de padrão construtivo, homogeneidade, densidade, transições
- Raios discretos: 300, 500, 700, 1000 ou 1500 metros
- Resposta: JSON com campos padronizados

---

## Agente 3 — Análise Qualitativa (visão)

### Cadeia de fallback:
```
1. Gemini 2.5 Flash    → 8 fotos + texto (1 chamada, ~15-25s)
   ↓ se falhar (429 quota / 500 erro)
2. Groq qwen3.6-27b   → 2 fotos + texto curto (1 chamada, ~10s)
   ↓ se falhar (413 payload)
3. NVIDIA NIM llama-3.2-11b → 1 foto principal + 7 extras (~30-90s)
```

### Gemini 2.5 Flash (principal):
- Aceita múltiplas imagens por chamada (até 8)
- Prompt completo com critérios detalhados de avaliação
- Limite: 20 requests/minuto no free tier
- Retry automático quando der 500

### Groq qwen3.6-27b (fallback 1):
- Aceita imagens via URL
- Limite: 8000 tokens/minuto (TPM)
- Usa apenas 2 fotos (primeira + do meio) pra caber no limite
- Prompt simplificado (200 chars descrição, 150 chars título)

### NVIDIA NIM (fallback 2):
- Modelo: meta/llama-3.2-11b-vision-instruct
- Sem limite rígido de requests
- 1 chamada principal (texto + 1 foto) + 7 chamadas extras (1 foto cada)
- Mais lento (~30-90s por imóvel) mas sempre funciona

### Limite de comparáveis:
- Máximo 20 imóveis analisados (top por ranking_llm)
- + 1 imóvel alvo = 21 chamadas total
- Tempo estimado: 5-8 minutos (Gemini + Groq), 15-20 min (pior caso NVIDIA)

---

## Agente 4 — Infraestrutura (texto)

### Modelo: openai/gpt-oss-20b (Groq)
- Tarefa leve: apenas interpreta scores já calculados pelo Python
- Não altera valores — gera texto descritivo (perfil, pontos fortes, atenção)
- 1 chamada por execução (~500 tokens)

---

## Limites e Quotas (Free Tier - Agosto 2026)

| Provider | Modelo | Limite |
|----------|--------|--------|
| Groq | openai/gpt-oss-120b | 200k tokens/dia |
| Groq | openai/gpt-oss-20b | 200k tokens/dia |
| Groq | qwen/qwen3.6-27b | 200k tokens/dia, 8k TPM |
| Google | Gemini 2.5 Flash | 20 requests/minuto |
| NVIDIA | llama-3.2-11b-vision | Sem limite documentado |

### Chaves necessárias no .env:
```
GROQ_API_KEY=...           # Conta principal
GROQ_API_KEY_2=...         # Conta secundária (opcional, dobra quota)
GOOGLE_API_KEY=...         # Gemini (análise qualitativa + fallback clustering)
NVIDIA_API_KEY=...         # NVIDIA NIM (último fallback visão)
GOOGLE_MAPS_KEY=...        # Google Maps (imagem satélite zona homogênea)
```

---

## Histórico de Migrações

| Data | Mudança | Motivo |
|------|---------|--------|
| 13/08/2026 | Ag.2 zona: NVIDIA NIM → Groq qwen3.6-27b | Melhor modelo (27B vs 11B), mais rápido |
| 13/08/2026 | Ag.3: NVIDIA NIM → Gemini 2.5 Flash | 8 fotos por chamada, muito mais rápido |
| 13/08/2026 | Ag.2 clustering: llama-3.3-70b → gpt-oss-120b | Llama desligado 16/08, GPT-OSS tem 200k/dia |
| 13/08/2026 | Ag.4: llama-3.1-8b → gpt-oss-20b | Llama desligado 16/08 |

---

## Observações

- O qwen3.6-27b usa modo "thinking" (`<think>...</think>`) — o parser remove automaticamente
- O Gemini pode dar 403 quando não consegue acessar URLs de imagem do VivaReal
- O Groq free tier reseta quotas diariamente (meia-noite UTC)
- O Gemini reseta a cada minuto (rolling window de 20 requests)
