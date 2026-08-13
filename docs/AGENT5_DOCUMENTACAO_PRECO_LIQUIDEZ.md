# Agente 5 — Estimador de Preço e Liquidez

## Objetivo

Calcula o valor estimado do imóvel alvo reproduzindo a metodologia da planilha do professor. Separa terreno e construção, usa TRIMMEAN(0.5). Adicionalmente gera estimativa experimental de liquidez (separada, não altera preços).

---

## Entrada

- `data/zona_homogenea_ag2.json` — comparáveis confirmados + terrenos na zona
- `data/imoveis_analisados_ag3.json` — score qualitativo + padrão acabamento
- `data/infra_avaliada_ag4.json` — score infraestrutura
- Imóvel alvo (área, área_terreno, tipo)

---

## Fluxo (Cálculo Oficial — Planilha)

```
ETAPA 1 — Valor m²/terreno (MIN + TRIMMEAN)
ETAPA 2 — Decisão: separar terreno ou não
ETAPA 3 — Duas séries de m²/construção (MÍN/TERRENO + MÉD/TERRENO)
ETAPA 4 — Valor do terreno do alvo
ETAPA 5 — Valor da construção do alvo
ETAPA 6 — Valor do imóvel (terreno + construção)
ETAPA 7 — Valor de liquidez (× 0.90)
```

---

## ETAPA 1 — Valor m²/terreno

Para cada terreno da zona homogênea:
```
valor_m2 = preço / área
Se topografia "acentuado": valor_m2 *= 0.80
```

Resultado:
- `menor_m2_terreno` = MIN de todos
- `medio_m2_terreno` = TRIMMEAN(0.5) de todos

---

## ETAPA 2 — Separar terreno ou não

| Tipo do alvo | Terreno no cálculo? |
|---|---|
| Apartamento / Sala | Não (terreno = 0) |
| Terreno puro | Só terreno, construção = 0 |
| Casa com área_terreno | Sim, separa |
| Casa sem área_terreno | Não (preço/m² total) |

---

## ETAPA 3 — Duas séries de m²/construção

Para cada comparável construído:

**Condominial (apto/sala):**
```
m2 = preço / área_construída (mesmo valor nas 2 séries)
```

**Casa/Loja/Galpão (separando terreno):**
```
Série MÍN/TERRENO: m2 = (preço - menor_m2_terreno × área_terreno_comp) / área_construída
Série MÉD/TERRENO: m2 = (preço - medio_m2_terreno × área_terreno_comp) / área_construída
```

Valores ≤ 0: descartados (terreno vale mais que o imóvel — inconsistente).

Combina as duas séries:
- `menor_m2_construcao` = MIN da lista combinada
- `medio_m2_construcao` = TRIMMEAN(0.5) da lista combinada

---

## ETAPA 4 — Valor do terreno

```
Se separa: valor_terreno_mínimo = menor_m2_terreno × área_terreno_alvo
           valor_terreno_médio  = medio_m2_terreno × área_terreno_alvo
Se condominial: = 0
```

---

## ETAPA 5 — Valor da construção

```
valor_construção_mínimo = menor_m2_construcao × área_construída_alvo
valor_construção_médio  = medio_m2_construcao × área_construída_alvo
```

---

## ETAPA 6 — Valor do imóvel

| Tipo | Fórmula |
|------|---------|
| Casa / Loja / Galpão | terreno + construção |
| Apartamento / Sala | apenas construção |
| Terreno | apenas terreno |

---

## ETAPA 7 — Valor de liquidez

```
valor_liquidez = valor_médio × 0.90
```

Desconto fixo de 10%. Agentes 3 e 4 NÃO alteram este valor.

---

## TRIMMEAN(0.5) — Reproduz Excel exato

1. Remove valores inválidos (nulos, ≤ 0)
2. Ordena
3. `n × 0.5` = quantidade candidata à exclusão
4. Floor par (arredonda para baixo até múltiplo de 2)
5. Remove metade do início, metade do final
6. Média aritmética dos restantes
7. Se quantidade = 0 → média de todos

**Nunca usa mediana como fallback.**

| n valores | Remove cada lado | Resultado |
|---|---|---|
| 1 | 0 | média de 1 |
| 2 | 0 | média de 2 |
| 3 | 0 | média de 3 |
| 4 | 1 | média dos 2 centrais |
| 10 | 2 | média dos 6 centrais |

---

## Liquidez Experimental (separada)

```
score = 0.35 × score_ag3 + 0.40 × score_ag4 + 0.25 × (1 - desconto)
```

| Score | Classificação | Tempo |
|---|---|---|
| ≥ 0.80 | alta | 30 a 60 dias |
| ≥ 0.65 | media_alta | 60 a 90 dias |
| ≥ 0.50 | media | 90 a 150 dias |
| < 0.50 | baixa | acima de 150 dias |

**NÃO modifica** valor_mínimo, valor_médio nem valor_liquidez.

---

## Saída

### `data/preco_liquidez_ag5.json`

```json
{
  "avaliacao_planilha": {
    "valor_minimo_imovel": 1690000.00,
    "valor_medio_imovel": 1690000.00,
    "desconto_liquidez_percentual": 10.0,
    "valor_liquidez": 1521000.00,
    "valor_liquidez_arredondado": 1521000
  },
  "liquidez_experimental": {
    "score_liquidez": 0.887,
    "classificacao": "alta",
    "tempo_estimado": "30 a 60 dias",
    "metodo": "heuristica_experimental",
    "pesos": "qualidade 35% + infraestrutura 40% + fator_preco 25%",
    "score_agente3_usado": 0.75,
    "score_agente4_usado": 1.0,
    "aviso": "Resultado experimental ainda nao validado com Days on Market dos comparaveis."
  },
  "auditoria": {
    "valores_m2_terreno": [],
    "m2_construcao_min_terreno": [...],
    "m2_construcao_med_terreno": [...],
    "valores_m2_construcao_combinados": [...]
  }
}
```

---

## O que NÃO faz nesta versão

- Score de liquidez não altera preço
- Padrão do Ag.3 não altera preço
- Infraestrutura do Ag.4 não altera preço
- Sem Days on Market
- Sem desconto variável
- Sem fator_preco entre agentes

---

## Dependências

Nenhuma LLM. Apenas Python puro (`statistics`, `json`, `math`).

---

## Resultado do Teste (Cambuí, Campinas — Apto 89m²)

```
Valor mínimo:  R$ 1.690.000
Valor médio:   R$ 1.690.000
Valor liquidez: R$ 1.521.000
Score liquidez (exp): 0.887 (alta)
Tempo estimado (exp): 30 a 60 dias
```
