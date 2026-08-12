# Agente 3 — Analisador Qualitativo

## Objetivo

Analisa fotos e descrição dos imóveis comparáveis para determinar estado de conservação, padrão de acabamento e score qualitativo. Usa modelos de visão multimodal (texto + imagens numa única chamada).

---

## Entrada

- `data/zona_homogenea_ag2.json` — pega imóveis com `cluster="A"` E `classificacao_zona="na_zona"`
- Fallback: `data/imoveis_comparaveis_ag2.json` — pega Cluster A sem filtro de zona

---

## Fluxo

```
1. Carrega zona_homogenea_ag2.json
2. Filtra: cluster="A" E classificacao_zona="na_zona"
3. Para cada imóvel:
     a. Seleciona até 8 fotos espaçadas uniformemente
     b. Monta prompt (título + descrição + campos + fotos)
     c. LLM multimodal analisa → retorna JSON
     d. Python normaliza + calcula score determinístico
4. Imóvel alvo: analisado separadamente
5. Salva em data/imoveis_analisados_ag3.json
```

---

## Cadeia de Fallback (LLMs)

| Prioridade | Modelo | Provider | Fotos por chamada |
|---|---|---|---|
| 1ª | gemini-2.5-flash | Google (GOOGLE_API_KEY) | até 8 |
| 2ª | qwen3.6-27b | Groq (GROQ_API_KEY) | até 5 |
| 3ª | llama-3.2-11b-vision | NVIDIA NIM (NVIDIA_API_KEY) | 1 por vez |

Se Gemini falhar (500, timeout, etc.) → tenta Groq → tenta NVIDIA → se tudo falhar → retorna score neutro 0.50.

---

## O que a LLM analisa

A LLM recebe título, descrição, dados estruturados e fotos e retorna:

| Campo | Valores possíveis |
|-------|-------------------|
| estado_conservacao | novo, reformado, bom, regular, precisa_reforma, desconhecido |
| padrao_acabamento | alto_padrao, medio, simples, desconhecido |
| pontos_positivos | lista de strings |
| pontos_negativos | lista de strings |
| qualidade_imagens | boa, razoavel, ruim |
| confianca_extracao | alta, media, baixa |
| evidencias | {conservacao: [...], acabamento: [...]} |

### Regras do prompt

- Usa SOMENTE informações visíveis nas fotos ou explícitas na descrição
- NÃO inventa informações
- Preço NÃO influencia a classificação
- Ausência de característica NÃO é ponto negativo
- Analisa TODAS as imagens em conjunto (não julga por 1 foto isolada)
- Conflitos entre ambientes → reduz confiança

---

## Cálculo do Score (determinístico, Python)

A LLM não calcula score. Ela retorna conservação + acabamento + positivos/negativos, e o Python calcula o score com pesos fixos.

### Fórmula

```
score = 0.50 (base)
      + ajuste_conservacao
      + ajuste_padrao
      + bonus_positivos (max +0.15)
      + penalizacoes (max -0.30)

score = clamp(score, 0.0, 1.0)
```

### Pesos de conservação

| Estado | Ajuste |
|--------|--------|
| novo | +0.20 |
| reformado | +0.15 |
| bom | +0.10 |
| regular | -0.05 |
| precisa_reforma | -0.25 |
| desconhecido | 0.00 |

### Pesos de acabamento

| Padrão | Ajuste |
|--------|--------|
| alto_padrao | +0.15 |
| medio | +0.07 |
| simples | -0.03 |
| desconhecido | 0.00 |

### Bônus positivos (exemplos)

| Diferencial | Bônus |
|-------------|-------|
| acabamento diferenciado | +0.05 |
| varanda gourmet | +0.04 |
| area externa privativa | +0.04 |
| piscina privativa | +0.04 |
| cozinha planejada | +0.03 |
| armarios planejados | +0.03 |
| vista livre | +0.03 |
| churrasqueira | +0.02 |
| boa iluminacao natural | +0.02 |

**Máximo total de bônus: +0.15**

Vagas de garagem e suítes ficam na lista mas NÃO geram bônus no score (já são dados estruturados).

### Penalizações (exemplos)

| Problema | Penalidade |
|----------|-----------|
| precisa_reforma | -0.25 |
| documentacao_irregular | -0.20 |
| infiltracao_umidade | -0.15 |
| danos_visiveis | -0.10 |
| pintura_deteriorada | -0.06 |
| acabamento_desgastado | -0.06 |
| problema não previsto | -0.05 |

**Máximo total de penalização: -0.30**

Anti-dupla penalização: se estado = "precisa_reforma", não desconta de novo pelo mesmo problema nos negativos.

### Regra neutra

Se `estado=desconhecido` E `padrao=desconhecido` E `sem negativos` E `confianca=baixa`:
→ score fixo = **0.50** (neutro, não prejudica nem beneficia)

---

## Classificação

| Score | Classificação |
|-------|---------------|
| < 0.40 | desfavoravel |
| 0.40 – 0.60 | neutro |
| 0.60 – 0.80 | favoravel |
| ≥ 0.80 | muito_favoravel |

---

## Saída

### `data/imoveis_analisados_ag3.json`

```json
{
  "imovel_alvo": {
    "analise_qualitativa": {
      "estado_conservacao": "bom",
      "padrao_acabamento": "medio",
      "pontos_positivos": ["varanda gourmet", "armarios planejados"],
      "pontos_negativos": [],
      "qualidade_imagens": "boa",
      "confianca_extracao": "alta",
      "evidencias": {"conservacao": [...], "acabamento": [...]},
      "scores": {"score_qualitativo": 0.67},
      "classificacao_qualitativa": "favoravel"
    }
  },
  "comparaveis": [
    {
      "id": "2752976859",
      "analise_qualitativa": {
        "estado_conservacao": "reformado",
        "padrao_acabamento": "alto_padrao",
        "scores": {"score_qualitativo": 0.85},
        "classificacao_qualitativa": "muito_favoravel"
      }
    }
  ],
  "resumo": {
    "total_analisados": 23,
    "score_qualitativo_medio": 0.67
  }
}
```

---

## Quem usa a saída

| Agente | O que pega | Pra que |
|--------|-----------|---------|
| **Agente 5** | `padrao_acabamento` do alvo | Identifica padrão construtivo (não usado no preço nesta versão) |
| **Agente 5** | `score_qualitativo` do alvo | Liquidez experimental (peso 35%) |
| **Interface** | estado, padrão, score, classificação | Exibe pro usuário |

---

## Dependências

| Serviço | Modelo | Uso |
|---------|--------|-----|
| Google Gemini | gemini-2.5-flash | Análise multimodal (principal) |
| Groq | qwen3.6-27b | Fallback multimodal |
| NVIDIA NIM | llama-3.2-11b-vision | Fallback final |

---

## Limitação

- A análise depende da qualidade e completude da descrição e das fotos do anúncio
- Imóveis sem fotos ou com fotos ruins → score neutro 0.50
- Máximo 20 comparáveis analisados por execução (limite de chamadas)
