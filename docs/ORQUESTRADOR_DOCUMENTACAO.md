# Orquestrador — Documentação

## O que é

O orquestrador é o componente que **conecta e coordena os 5 agentes** do sistema. Ele decide a ordem de execução, passa dados entre os agentes, e trata falhas.

Arquivo: `app/graph.py`

---

## Fluxo de Execução

```
Imóvel Alvo (dados inseridos pelo usuário)
    │
    ▼
┌─────────────────────────────────┐
│  Agente 1 — Coletor de Dados   │  SEQUENCIAL (~2 min)
│  Coleta imóveis dos portais     │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  Agente 2 — Identificador      │  SEQUENCIAL (~1 min)
│  Filtra comparáveis + zona      │
└─────────────────────────────────┘
    │
    ├───────────────────┐
    ▼                   ▼
┌───────────────┐  ┌───────────────┐
│  Agente 3     │  │  Agente 4     │  PARALELO (~3 min)
│  Analisador   │  │  Infraestr.   │
└───────────────┘  └───────────────┘
    │                   │
    └─────────┬─────────┘
              ▼
┌─────────────────────────────────┐
│  Agente 5 — Estimador de Preço │  SEQUENCIAL (instantâneo)
│  Calcula valor + liquidez       │
└─────────────────────────────────┘
    │
    ▼
  Resultado Final
```

---

## Regras de Execução

1. **Agentes 1 e 2 são sequenciais** — o Ag. 2 precisa dos imóveis do Ag. 1
2. **Agentes 3 e 4 rodam em paralelo** — são independentes entre si (ambos leem do Ag. 2)
3. **Agente 5 é sequencial** — precisa dos resultados dos Ag. 3 e 4

Isso é implementado com `ThreadPoolExecutor(max_workers=2)` para o paralelismo.

---

## Tratamento de Falhas

### Falhas que PARAM o pipeline

| Situação | Motivo | Mensagem |
|----------|--------|----------|
| Ag. 1 sem imóveis | Sem dados não há o que comparar | "Nenhum imóvel encontrado na região" |
| Ag. 2 dá exceção | Sem comparáveis não há base de preço | "Erro no Agente 2" |
| Ag. 2 sem comparáveis | Nenhum imóvel similar encontrado | "Nenhum comparável encontrado" |

### Falhas que NÃO param (continua com dados parciais)

| Situação | O que faz | Impacto |
|----------|-----------|---------|
| Zona homogênea falha | Continua sem validação geográfica | Usa todos os comparáveis |
| Ag. 3 falha | Score = 0.50 (neutro) | Tempo de liquidez menos preciso |
| Ag. 4 falha | Score = 0.50 (neutro) | Tempo de liquidez menos preciso |
| Ag. 5 falha | Sem preço estimado | Mostra apenas comparáveis |

### Status do resultado

- `"completo"` — todos os 5 agentes rodaram sem erro
- `"parcial — X falha(s)"` — pipeline continuou mas com dados incompletos
- `"erro — ..."` — pipeline parou por falta de dados essenciais

---

## Passagem de Dados entre Agentes

| De → Para | O que passa | Como |
|-----------|-------------|------|
| Ag. 1 → Ag. 2 | Lista de imóveis coletados | Variável em memória |
| Ag. 2 → Ag. 3 | Comparáveis com cluster e zona | Arquivo `zona_homogenea_ag2.json` |
| Ag. 2 → Ag. 4 | Imóvel alvo (para geocodificar) | Arquivo `imoveis_comparaveis_ag2.json` |
| Ag. 3 → Ag. 5 | Score qualitativo + padrão construtivo | Arquivo `imoveis_analisados_ag3.json` |
| Ag. 4 → Ag. 5 | Score infraestrutura + tempo liquidez | Arquivo `infra_avaliada_ag4.json` |
| Ag. 2 → Ag. 5 | Terrenos e comparáveis da zona | Arquivo `zona_homogenea_ag2.json` |

---

## Interface Web

Arquivo: `app/interface.py`

A interface Streamlit executa o mesmo fluxo do orquestrador, mas com:
- Formulário para o usuário inserir os dados do imóvel
- Barra de progresso em tempo real
- Mensagens descritivas de cada etapa
- Contador regressivo (faltam ~X segundos)
- Resultado visual com cards e seções expansíveis

---

## Como Rodar

```bash
# Via terminal (sem interface)
.venv/Scripts/python.exe -m app.main

# Via interface web
.venv/Scripts/streamlit.exe run app/interface.py
```

---

## Tempo Total de Execução

| Etapa | Tempo médio |
|-------|-------------|
| Ag. 1 — Coleta | ~2 minutos |
| Ag. 2 — Comparáveis + zona | ~1 minuto |
| Ag. 3 + 4 — Paralelo | ~3 minutos |
| Ag. 5 — Preço | instantâneo |
| **Total** | **~6 minutos** |

---

## Dependências Externas

| Agente | API/Serviço | Chave necessária |
|--------|-------------|-----------------|
| Ag. 1 | Apify (scraping) | APIFY_TOKEN_2 |
| Ag. 2 | Groq (LLM clustering) | GROQ_API_KEY |
| Ag. 2 | Google Geocoding | GOOGLE_MAPS_KEY |
| Ag. 3 | NVIDIA NIM (LLM Vision) | NVIDIA_API_KEY |
| Ag. 4 | osmnx/OpenStreetMap | nenhuma |
| Ag. 4 | Groq (LLM análise) | GROQ_API_KEY |
| Ag. 5 | nenhuma (Python puro) | nenhuma |
