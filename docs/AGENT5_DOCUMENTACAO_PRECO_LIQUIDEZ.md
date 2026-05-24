# Agente 5 — Estimador de Preço e Liquidez

## Objetivo

Calcular o valor estimado do imóvel alvo a partir do valor do metro quadrado da zona homogênea, separando **terreno** e **construção** por padrão construtivo. Também estima o **tempo de liquidez** (tempo provável de venda) usando os scores dos agentes 3 e 4.

---

## Resumo da Lógica (baseada na planilha do professor)

```
Valor do Imóvel = Valor do Terreno + Valor da Construção

Onde:
  Valor do Terreno    = m²_terreno_zona × área_terreno_alvo
  Valor da Construção = m²_construção_padrão × área_construída_alvo

Valor de Liquidez = Valor Médio × 0.90 (desconto de 10%)
```

---

## Fluxo Completo (8 passos)

### Passo 1 — Calcula valor m² do terreno na zona homogênea

- Pega todos os **terrenos** do `zona_homogenea_ag2.json` (propertyType = "Terrenos")
- Para cada terreno: `m² = preço / área`
- Calcula a **mediana** (equivalente ao TRIMMEAN da planilha)
- Calcula o **mínimo**

**Exemplo real:** 12 terrenos → mediana R$ 6.001/m², mínimo R$ 3.077/m²

### Passo 2 — Decide se separa terreno ou não

- **Se condominial** (apartamento, sala, loja): terreno = 0 (regra da planilha)
- **Se casa/sobrado com área_terreno informada**: separa terreno + construção
- **Se casa sem área_terreno**: usa m² total (preço/área dos comparáveis direto)

### Passo 3 — Calcula valor m² da construção por padrão

- Pega os **imóveis construídos** da zona homogênea (casas, sobrados, aptos)
- Para cada um, busca o **padrão construtivo** no resultado do Agente 3 (alto, médio, baixo)
- Calcula o m² de construção:
  - **Se separando terreno**: `m²_construção = (preço - terreno_estimado) / área_construída`
  - **Se não separando**: `m²_construção = preço / área_construída`
- Agrupa por padrão e calcula mediana de cada grupo

**Exemplo real (padrão médio):** 35 amostras → mediana R$ 9.375/m²

### Passo 4 — Calcula valor do terreno do imóvel alvo

```
Valor Terreno Mínimo = menor_m²_terreno × área_terreno_alvo
Valor Terreno Médio  = mediana_m²_terreno × área_terreno_alvo
```

Equivalente às células **C62** e **C63** da planilha.

### Passo 5 — Calcula valor da construção do imóvel alvo

```
Valor Construção Mínimo = menor_m²_construção_padrão × área_construída_alvo
Valor Construção Médio  = mediana_m²_construção_padrão × área_construída_alvo
```

Equivalente às células **C64** e **C65** da planilha.

### Passo 6 — Soma terreno + construção

```
Valor Mínimo = Terreno Mínimo + Construção Mínimo
Valor Médio  = Terreno Médio + Construção Médio
```

Se condominial, usa apenas construção. Equivalente às células **C68** e **C69**.

### Passo 7 — Calcula valor de liquidez

```
Valor de Liquidez = Valor Médio × 0.90
```

Desconto de 10% para venda rápida. Equivalente à célula **C70**.

### Passo 8 — Estima tempo de liquidez

Combina os scores dos agentes anteriores com pesos:

```
Score Liquidez = 0.35 × score_qualitativo_ag3
               + 0.40 × score_infraestrutura_ag4
               + 0.25 × (1 - desconto)
```

Classificação:
| Score | Classificação | Tempo Estimado |
|-------|---------------|----------------|
| ≥ 0.80 | alta | 30 a 60 dias |
| ≥ 0.65 | média_alta | 60 a 90 dias |
| ≥ 0.50 | média | 90 a 150 dias |
| < 0.50 | baixa | acima de 150 dias |

Também inclui a **sugestão da LLM do Agente 4** (`tempo_liquidez_regional`) como referência complementar.

---

## Entrada

| Arquivo | O que usa |
|---------|-----------|
| `data/zona_homogenea_ag2.json` | Terrenos e comparáveis confirmados na zona |
| `data/imoveis_analisados_ag3.json` | Score qualitativo + padrão construtivo de cada imóvel |
| `data/infra_avaliada_ag4.json` | Score de infraestrutura + tempo de liquidez regional |
| `app/main.py` (via pipeline) | Dados extras do imóvel alvo (area_terreno) |

---

## Saída

Arquivo: `data/preco_liquidez_ag5.json`

```json
{
  "agente": "Agente 5 - Estimador de Preco e Liquidez",
  "imovel_alvo": {
    "tipo": "casa",
    "area_terreno_m2": 200.0,
    "area_construida_m2": 170.0,
    "padrao_construtivo": "medio"
  },
  "valor_m2_zona_homogenea": {
    "terreno": {
      "quantidade_amostras": 12,
      "menor_valor_m2": 3076.92,
      "valor_m2_referencia": 6001.36
    },
    "construcao_por_padrao": {
      "padrao_usado": "medio",
      "menor_valor_m2_usado": 478.75,
      "valor_m2_referencia_usado": 9375.00
    }
  },
  "avaliacao": {
    "valor_minimo_imovel": 81387.30,
    "valor_medio_imovel": 1593750.00,
    "desconto_liquidez_percentual": 10.0,
    "valor_liquidez": 1434375.00,
    "valor_liquidez_arredondado": 1434000
  },
  "liquidez": {
    "score_liquidez": 0.735,
    "classificacao": "media_alta",
    "tempo_estimado": "60 a 90 dias",
    "tempo_liquidez_regional_ag4": "30 a 60 dias"
  }
}
```

---

## Correspondência com a Planilha do Professor

| Célula | Fórmula na Planilha | Nosso Código |
|--------|---------------------|--------------|
| C62 | MIN(m²_terreno) × area_terreno | `menor_m2_terreno * area_terreno_alvo` |
| C63 | TRIMMEAN(m²_terreno, 0.5) × area_terreno | `mediana(m2_terreno) * area_terreno_alvo` |
| C64 | MIN(m²_construção) × area_construída | `menor_m2_construcao * area_construida_alvo` |
| C65 | TRIMMEAN(m²_construção, 0.5) × area_construída | `mediana(m2_construcao) * area_construida_alvo` |
| C68 | Se condominial: C64, senão: C62+C64 | `valor_terreno_min + valor_construcao_min` |
| C69 | Se condominial: C65, senão: C63+C65 | `valor_terreno_med + valor_construcao_med` |
| C70 | C69 × 0.90 | `valor_medio * 0.90` |

**Sobre o TRIMMEAN(0.5):** A planilha remove 50% dos extremos (25% menores + 25% maiores). Nós usamos **mediana**, que é equivalente quando se tem poucos dados — ambos pegam o valor central ignorando extremos.

---

## Regras de Negócio

1. **Apartamento/Sala/Loja** → terreno = 0 (condominial, terreno não se avalia separado)
2. **Terreno puro** → construção = 0 (só avalia o terreno)
3. **Casa/Sobrado** → terreno + construção (se tiver area_terreno)
4. **Sem area_terreno** → usa m² total (preço/área dos comparáveis, que já embute terreno)
5. **Padrão construtivo** → vem do Agente 3 (alto_padrao, medio, baixo)
6. **Fallback de padrão** → se não encontrar amostras do padrão, usa base geral
7. **Desconto de liquidez** → 10% fixo (configurável)
8. **Deduplicação** → terrenos com mesmo ID não são contados duas vezes

---

## Dependências

- Python puro (sem APIs externas)
- Lê JSONs dos agentes 2, 3 e 4
- Bibliotecas: `json`, `re`, `statistics`, `pathlib`

---

## Como Rodar

```bash
# Direto (lê os JSONs e salva resultado)
.venv/Scripts/python.exe -m agents.price_liquidity

# Via pipeline completo
.venv/Scripts/python.exe app/main.py
```

---

## Limitações

1. **Área do terreno** — a maioria dos anúncios não informa a área do terreno separadamente. Quando não tem, o cálculo usa m² total (sem separar terreno/construção).
2. **Padrão construtivo** — depende do Agente 3 ter classificado corretamente. Se o Ag. 3 retornou "desconhecido", o fallback é "medio".
3. **Poucos comparáveis por padrão** — se houver poucas amostras de um padrão específico, usa a base geral (todos os padrões juntos).
4. **Valores de anúncio** — os preços são de oferta (não de venda efetiva). Imóveis podem ser vendidos por valores diferentes.
5. **Tempo de liquidez** — é uma estimativa baseada em scores, não em dados reais de tempo de venda da região.

---

## Histórico de Desenvolvimento

| Tentativa | O que foi feito | Resultado |
|-----------|-----------------|-----------|
| Versão 1 | Código genérico com `executar_por_arquivo()` esperando JSON de entrada manual | Não integrava com os agentes anteriores |
| Versão 2 | Adicionada `estimar_preco()` que lê JSONs reais dos agentes | Funcionou, mas duplicava terrenos |
| Versão 3 | Deduplicação por ID + lógica de separar terreno condicionalmente | Valor ficava inflado (somava terreno + m² que já embutia terreno) |
| Versão 4 (final) | Segue planilha do professor: sempre separa se tem area_terreno, só usa comparáveis com area_terreno para calcular m² construção quando separando | Valores coerentes com mercado |
