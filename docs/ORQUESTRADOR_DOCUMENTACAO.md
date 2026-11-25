# Orquestrador — Documentação

## O que é

O orquestrador é o componente que **conecta e coordena os 5 agentes** do sistema. Ele decide a ordem de execução, passa dados entre os agentes, e trata falhas.

Arquivo: **`services/pipeline.py`** (`executar_avaliacao`). É o **mesmo** para a tela e para o terminal:

| Quem chama | Como |
|---|---|
| Página "Avaliação de imóvel" (`app/paginas/avaliacao.py`) | `executar_avaliacao(..., obs=ObservadorTela())`: a tela só mostra as mensagens e a barra de cada etapa |
| Terminal (`app/main.py`, `app/graph.executar_pipeline`) | `executar_avaliacao(..., obs=ObservadorLog(), gravar=False)`: cada etapa vira uma linha no log |

**Por que um arquivo só:** até 24/11/2026, a tela e o `app/graph.py` tinham cada um o
seu fluxo, e o do terminal ficou para trás. Ele não localizava o alvo antes da coleta,
mandava os terrenos para a zona por outro caminho, não passava o imóvel ao Agente 3 e
não avaliava o leilão. No mesmo imóvel (Arapongas), deu R$ 338 mil, contra R$ 299–314
mil pela tela. **Mudança no fluxo entra só em `services/pipeline.py`.** O teste
`tests/test_pipeline_unico.py` falha se a tela ou o terminal voltarem a chamar os agentes
direto.

**Etapas** (o observador recebe cada uma, na ordem): localizar o alvo (geocodificação
única, sem aceitar só a cidade) → Agente 1 (com a coordenada, para a busca por
proximidade) → Agente 2 → zona homogênea (Cluster A + terrenos) → Agentes 3 e 4 juntos →
Agente 5 → fim (`montar_resultado_final`: leilão, verificações e banco).

**Terminal:**
```
.venv\Scripts\python.exe -m app.main            # não grava no banco
.venv\Scripts\python.exe -m app.main --gravar   # grava, como a tela
```
Os campos do imóvel e do leilão ficam no topo de `app/main.py`, com os mesmos nomes do formulário.

> O diagrama e as seções abaixo descrevem os agentes. Tempos e fontes podem estar
> desatualizados; o fluxo em si está em `services/pipeline.py`.

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
| Ag. 1 sem imóveis | Sem dados não há o que comparar | "Não há casas nem terrenos à venda em <cidade>/<UF> na base de anúncios; não é possível estimar o valor de mercado." Com dados de leilão, o cartão do leilão aparece com "Sem estimativa" |
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

Arquivo: `app/interface.py` (declara as páginas) e `app/paginas/avaliacao.py` (avaliação)

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
