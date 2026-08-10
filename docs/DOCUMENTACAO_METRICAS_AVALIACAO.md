# Documentação das Métricas de Avaliação

## Visão Geral

Este documento detalha as métricas utilizadas na avaliação do sistema multiagente de precificação imobiliária. A avaliação foca em dois aspectos:

1. **Acurácia** — quão próximo o preço estimado pelo sistema está do preço real de mercado
2. **Liquidez** — capacidade do sistema de identificar a relação entre preço e tempo de venda

---

## 1. Métricas de Acurácia

### 1.1 Erro Relativo Médio (MAE — Mean Absolute Error Relativo)

**O que mede:** Desvio médio percentual entre o preço estimado pelo sistema e o preço anunciado.

**Fórmula:**

```
MAE = (1/n) × Σ |preço_sistema_i - preço_anunciado_i| / preço_anunciado_i
```

**Exemplo de cálculo:**

| Imóvel | Anunciado | Sistema | Erro Relativo |
|--------|-----------|---------|---------------|
| 1 | R$ 997.000 | R$ 859.988 | |997000-859988|/997000 = 0.1374 |
| 2 | R$ 2.280.000 | R$ 2.225.581 | |2280000-2225581|/2280000 = 0.0239 |

```
MAE = (0.1374 + 0.0239 + ...) / n
```

**Interpretação:**
- < 10% → excelente
- 10-20% → bom
- 20-30% → aceitável
- > 30% → necessita melhoria

**Resultado obtido:** 18.5% (bom)

---

### 1.2 Erro Relativo Mediano

**O que mede:** O valor central dos erros relativos, ordenados do menor ao maior.

**Fórmula:**

```
Mediana dos erros = valor central quando todos os erros são ordenados
```

**Por que usar além do MAE:** A mediana é robusta a outliers. Se um único imóvel tem erro de 100%, o MAE é muito afetado, mas a mediana não.

**Exemplo:**
```
Erros ordenados: [0.003, 0.024, 0.137, 0.146, 0.200, 0.318, 0.326, 0.328]
Mediana (n=8, par): (0.146 + 0.200) / 2 = 0.173
```

**Resultado obtido:** 17.3%

---

### 1.3 Desvio Padrão do Erro

**O que mede:** Quanto os erros variam entre si (consistência do sistema).

**Fórmula:**

```
σ = √[(1/(n-1)) × Σ (erro_i - MAE)²]
```

**Interpretação:**
- Desvio baixo + MAE baixo → sistema preciso e consistente
- Desvio alto + MAE baixo → sistema impreciso mas na média acerta
- Desvio alto + MAE alto → sistema inconsistente

**Resultado obtido:** 13.2% — variabilidade moderada

---

### 1.4 Percentual Dentro de ±10%, ±20%, ±30%

**O que mede:** Proporção de imóveis onde o erro ficou abaixo de cada limiar.

**Fórmula:**

```
% dentro de ±X = (nº imóveis com erro ≤ X) / (total de imóveis válidos) × 100
```

**Exemplo:**
```
Erros: [0.003, 0.024, 0.137, 0.146, 0.200, 0.318, 0.326, 0.328]

Dentro de ±10%: [0.003, 0.024] → 2/8 = 25%
Dentro de ±20%: [0.003, 0.024, 0.137, 0.146, 0.200] → 5/8 = 62.5%
Dentro de ±30%: [0.003, 0.024, 0.137, 0.146, 0.200] → 5/8 = 62.5%
```

**Resultado obtido:** 25% (±10%) | 62.5% (±20%) | 62.5% (±30%)

---

## 2. Métricas de Liquidez

### 2.1 Days on Market (DoM)

**O que mede:** Tempo em dias desde a publicação do anúncio até a data da avaliação.

**Fórmula:**

```
DoM = data_avaliação - data_publicação (em dias)
```

**Exemplo:**
```
Publicado em: 2022-01-13
Avaliação em: 2026-06-09
DoM = 1608 dias
```

**Interpretação:**
- DoM ≤ 90 dias → liquidez alta (vende rápido)
- 90 < DoM ≤ 180 dias → liquidez média
- DoM > 180 dias → liquidez baixa (possível sobrepreço)

**Resultado obtido:** média 340 dias | mediana 119 dias

---

### 2.2 Sobrepreço Percentual

**O que mede:** Quanto o preço anunciado está acima (ou abaixo) do que o sistema estima como valor justo.

**Fórmula:**

```
Sobrepreço(%) = (preço_anunciado - preço_sistema) / preço_sistema × 100
```

**Exemplos:**
```
Imóvel 8: (765000 - 515494) / 515494 × 100 = +48.4% (anunciado ACIMA do estimado)
Imóvel 5: (420000 - 481463) / 481463 × 100 = -12.8% (anunciado ABAIXO do estimado)
```

**Interpretação:**
- Sobrepreço > 0% → imóvel possivelmente caro demais → menor liquidez esperada
- Sobrepreço < 0% → imóvel possivelmente barato → maior liquidez esperada
- Sobrepreço ≈ 0% → preço alinhado ao mercado

**Resultado obtido:** médio 3.72% | mediano 1.06%

---

### 2.3 Taxa de Concordância (DoM > 6 meses)

**O que mede:** Para imóveis que estão há mais de 6 meses no mercado (baixa liquidez), verifica se o sistema detectou sobrepreço (sugeriu preço menor que o anunciado).

**Fórmula:**

```
Taxa = nº imóveis com (DoM > 180 E sobrepreço > 0) / nº imóveis com DoM > 180 × 100
```

**Lógica:** Se um imóvel está há muito tempo sem vender E o sistema diz que está caro demais, isso "concorda" com a realidade de mercado — o imóvel não vende porque o preço está acima do valor justo.

**Exemplo com dados reais:**
```
Imóveis com DoM > 180 dias:
  - Imóvel 1: DoM=1608, sobrepreço=+15.9% ✓ (concordou)
  - Imóvel 5: DoM=434, sobrepreço=-12.8% ✗ (não concordou — está abaixo)
  - Imóvel 8: DoM=652, sobrepreço=+48.4% ✓ (concordou)
  - Imóvel 13: DoM=390, sobrepreço=null ✗
  - Imóvel 14: DoM=321, sobrepreço=-24.1% ✗ (não concordou)

Taxa = 2/5 = 40%
```

**Interpretação:**
- 100% → sistema sempre detecta sobrepreço em imóveis encalhados
- 0% → sistema não consegue explicar por que imóveis não vendem
- 40% → o preço explica parte dos casos, mas existem outros fatores (localização, estado de conservação, etc.)

**Resultado obtido:** 40%

---

### 2.4 Correlação DoM × Sobrepreço (Pearson)

**O que mede:** A intensidade e direção da relação linear entre o tempo de exposição no mercado e o sobrepreço detectado pelo sistema.

**Fórmula completa:**

```
r = Σ[(DoM_i - média_DoM) × (sobrepreço_i - média_sobrepreço)] / 
    √[Σ(DoM_i - média_DoM)²] × √[Σ(sobrepreço_i - média_sobrepreço)²]
```

Equivalente a:

```
r = covariância(DoM, sobrepreço) / (desvio_padrão_DoM × desvio_padrão_sobrepreço)
```

**Passo a passo do cálculo:**

1. Para cada imóvel, extrai o par (DoM, sobrepreço%):
```
Pares: [(1608, 15.9), (434, -12.8), (652, 48.4), (119, -0.3), (4, 24.9), ...]
```

2. Calcula as médias:
```
média_DoM = (1608 + 434 + 652 + 119 + 4 + ...) / n
média_sobrepreço = (15.9 + (-12.8) + 48.4 + (-0.3) + 24.9 + ...) / n
```

3. Calcula a covariância:
```
cov = (1/n) × Σ (DoM_i - média_DoM) × (sobrepreço_i - média_sobrepreço)
```

4. Calcula os desvios padrão:
```
σ_DoM = √[(1/n) × Σ (DoM_i - média_DoM)²]
σ_sobrepreço = √[(1/n) × Σ (sobrepreço_i - média_sobrepreço)²]
```

5. Divide:
```
r = cov / (σ_DoM × σ_sobrepreço)
```

**Escala de interpretação:**
- r = +1.0 → correlação positiva perfeita
- r = +0.7 a +1.0 → forte
- r = +0.3 a +0.7 → moderada
- r = 0.0 a +0.3 → fraca
- r = 0.0 → sem correlação
- r < 0 → correlação negativa (inversa)

**Resultado obtido:** 0.33 (correlação positiva moderada)

**O que significa:** Existe uma tendência real (não perfeita) de que imóveis com mais tempo no mercado têm maior sobrepreço detectado pelo sistema. Isso valida a hipótese central do trabalho: preço acima do valor justo de mercado está associado a menor liquidez.

---

## 3. Métricas Individuais por Imóvel

### 3.1 Preço Sistema (valor_medio_imovel)

Valor estimado pelo Agente 5, calculado a partir do m²/zona homogênea usando TRIMMEAN (média aparada que exclui 25% dos extremos).

### 3.2 Preço Liquidez (valor_liquidez)

Preço sugerido para venda rápida: `preço_sistema × (1 - desconto_liquidez)`, onde desconto padrão = 10%.

### 3.3 Score de Liquidez

Composição ponderada dos scores dos Agentes 3 e 4:
```
score = (score_qualitativo × 0.35) + (score_infraestrutura × 0.40) + (fator_preço × 0.25)
```

### 3.4 Classificação de Liquidez / Tempo Estimado de Venda

Baseada no score de liquidez:
- Score > 0.8 → alta → 30 a 60 dias
- Score 0.6-0.8 → média_alta → 60 a 90 dias  
- Score 0.4-0.6 → média → 90 a 150 dias
- Score < 0.4 → baixa → acima de 150 dias

---

## 4. Resumo dos Resultados

| Métrica | Resultado | Interpretação |
|---------|-----------|---------------|
| MAE | 18.5% | Erro médio aceitável |
| Mediana do erro | 17.3% | Metade dos imóveis tem erro < 17% |
| % dentro de ±20% | 62.5% | 5 de 8 imóveis com erro baixo |
| Correlação DoM×Sobrepreço | 0.33 | Positiva moderada — valida hipótese |
| Taxa concordância DoM>6m | 40% | 2 de 5 imóveis encalhados explicados pelo preço |
| Sobrepreço médio | 3.72% | Em geral, anúncios levemente acima do mercado |

---

## 5. Limitações

1. **Cobertura geográfica**: 4 de 15 imóveis não retornaram resultado por falta de dados nos portais (VivaReal/LugarCerto) para bairros específicos.
2. **Tamanho amostral**: 15 imóveis (11 válidos) permite validação exploratória mas não conclusões estatisticamente robustas (p-value não calculado).
3. **Viés de seleção**: Não há como confirmar se imóveis removidos dos portais foram efetivamente vendidos ou apenas retirados.
4. **DoM aproximado**: A data de publicação no portal pode não corresponder ao início real da oferta (imóvel pode ter sido anunciado antes em outro canal).
5. **Infraestrutura parcial**: Módulo osmnx não estava disponível em parte da execução, gerando scores de infraestrutura incompletos para alguns imóveis.
6. **Histórico de preços indisponível**: O preço anunciado capturado reflete o valor no momento da avaliação, sem considerar possíveis reduções anteriores realizadas pelo proprietário. Imóveis com alto DoM e sobrepreço negativo (ex: imóvel 5 com DoM=434 dias e sobrepreço=-12.8%) podem refletir ajustes de preço já realizados — o proprietário pode ter começado com preço mais alto e reduzido ao longo do tempo sem conseguir vender. Como os portais não expõem histórico de preços publicamente, não é possível verificar essa hipótese. Consequência: a correlação DoM×Sobrepreço obtida (0.33) pode estar **subestimada** — a correlação real considerando o preço original de anúncio (antes de reduções) provavelmente seria maior. Para trabalhos futuros, recomenda-se a coleta periódica de dados (scraping semanal) para construir séries temporais de preço e capturar essas variações.

---

## 6. Avaliação da Qualidade de Filtragem — Agente 2

### 6.1 Metodologia

A qualidade do Agente 2 (Identificador de Comparáveis) foi avaliada como um problema de **classificação binária**:
- **Classe Positiva:** imóvel é comparável/homogêneo ao alvo
- **Classe Negativa:** imóvel não é comparável

Para isso, foi construída uma base rotulada manualmente seguindo o método de **rotulagem cega** — o avaliador humano recebeu as mesmas informações que a LLM (tipo, área, quartos, banheiros, vagas, preço, preço/m², bairro, rua, descrição) **sem saber a classificação do sistema**, em ordem aleatória.

**Imóvel alvo de referência:** Casa, 190m², 3 quartos, 3 banheiros, 2 vagas — Cidade Nova, Manaus/AM — R$ 450.000

**Critérios de rotulagem (mesmos enviados à LLM):**
- Comparável (1): mesmo tipo, área ±50%, quartos ±1, mesmo bairro/região, padrão similar
- Não comparável (0): tipo diferente, área >2× maior/menor, padrão muito diferente, uso diferente

### 6.2 Resultados

**Amostra:** 115 imóveis rotulados (48 do Cluster A + 62 do Cluster B + 5 terrenos)

**Matriz de Confusão:**

|                      | Humano: Comparável | Humano: Não Comparável |
|----------------------|:------------------:|:----------------------:|
| **Sistema: Cluster A** | VP = 18            | FP = 29                |
| **Sistema: Cluster B** | FN = 27            | VN = 41                |

**Métricas:**

| Métrica | Valor | Interpretação |
|---------|-------|---------------|
| Precisão | 38.3% | Dos 47 selecionados pelo sistema, apenas 18 são de fato comparáveis |
| Revocação | 40.0% | Dos 45 comparáveis reais, o sistema identificou 18 |
| F1-score | 39.1% | Equilíbrio baixo entre precisão e revocação |
| Acurácia | 51.3% | Pouco acima do acaso (50%) |

### 6.3 Análise das Divergências

**Falsos Positivos (29 imóveis) — Sistema incluiu, humano excluiu:**
- Todos no mesmo bairro (Cidade Nova) — a LLM priorizou localização
- Áreas de 50m² a 425m² (alvo: 190m²) — variação extrema
- Muitos com apenas 2 quartos e 1 banheiro (alvo: 3q, 3b)
- **Causa:** A LLM foi excessivamente generosa no critério de área e quartos, aceitando imóveis muito menores (60-90m², 2q) como "comparáveis" apenas por estarem no mesmo bairro

**Falsos Negativos (27 imóveis) — Sistema excluiu, humano incluiu:**
- Todos no mesmo bairro (Cidade Nova)
- Áreas de 145m² a 450m² — muitas dentro da faixa aceitável (±50% de 190m²)
- Maioria com 3 quartos, 2-3 banheiros — muito similares ao alvo
- Scores numéricos altos (0.70 a 0.88) — o algoritmo numérico concordava com o humano
- **Causa:** A LLM processou em lotes separados e foi inconsistente — rejeitou imóveis no Cluster B que tinham scores mais altos que alguns aceitos no Cluster A. Isso sugere que o processamento em lotes de 40 sem contexto global prejudica a consistência da classificação.

### 6.4 Diagnóstico

O principal problema identificado é a **inconsistência da LLM entre lotes**:
- Lote 1 pode ter critérios mais rígidos que o Lote 2
- Imóveis de 180m², 3 quartos, score 0.88 foram rejeitados (FN)
- Imóveis de 60m², 2 quartos, score 0.51 foram aceitos (FP)
- O score numérico de similaridade (pré-LLM) mostrou-se mais coerente que a classificação final da LLM

### 6.5 Recomendações de Melhoria

1. **Enviar todos os candidatos em um único lote** (se o limite de tokens permitir) para garantir consistência global
2. **Usar o score numérico como filtro primário** — só enviar para a LLM candidatos com score > 0.6, reduzindo ruído
3. **Adicionar critérios rígidos pré-LLM:** excluir automaticamente imóveis com área < 50% ou > 200% do alvo antes de enviar à LLM
4. **Pós-processamento de coerência:** após o clustering da LLM, verificar se há inversões (imóvel do Cluster B com score maior que imóvel do Cluster A) e corrigir
5. **Ajustar o prompt:** enfatizar mais a área e quartos como critérios eliminatórios, não apenas localização

### 6.6 Impacto no Resultado Final

Apesar do F1 baixo na filtragem, o **impacto no preço final é atenuado** porque:
- O Agente 5 usa **TRIMMEAN** (média aparada de 50%) que remove automaticamente os 25% mais altos e 25% mais baixos — eliminando comparáveis inconsistentes
- Imóveis muito pequenos ou muito grandes terão preço/m² discrepante e serão removidos pela média aparada
- A zona homogênea (geocodificação) filtra geograficamente imóveis distantes

Portanto, a baixa precisão do Agente 2 é parcialmente compensada pelo tratamento estatístico dos agentes posteriores, explicando por que o erro de preço final (18.5%) é razoável apesar da filtragem imperfeita.

---

### 6.7 Resultado Final da Avaliação de Filtragem (11 imóveis, 3 avaliadores)

A avaliação foi refeita com escopo ampliado: 11 imóveis de 9 cidades diferentes, com rotulagem cega por 3 avaliadores independentes (Laura, Lívia e Kiro), totalizando ~570 candidatos rotulados por cada avaliador.

**Resultados globais (micro-average):**

| Avaliador | Precisão | Revocação | F1-score | Acurácia |
|-----------|----------|-----------|----------|----------|
| Laura | 54.5% | 65.5% | 59.5% | 76.9% |
| Lívia | 54.2% | 64.4% | 58.9% | 76.4% |
| Kiro | 47.8% | 73.9% | 58.0% | 78.5% |
| **Média** | **52.2%** | **67.9%** | **58.8%** | **77.3%** |

**Concordância entre avaliadores:**

| Par | Concordância |
|-----|-------------|
| Laura vs Lívia | 85.0% |
| Laura vs Kiro | 83.2% |
| Lívia vs Kiro | 84.4% |

**Interpretação:**

- **F1 médio de 58.8%** — melhoria significativa em relação ao teste piloto com 1 imóvel (39.1%), indicando que com mais dados e diversidade geográfica, o sistema performa melhor.
- **Acurácia de 77%** — o sistema classifica corretamente ~3/4 dos imóveis candidatos.
- **Precisão ~54%** — dos imóveis que o sistema seleciona como comparáveis, metade é de fato comparável segundo avaliação humana. O sistema é generoso na inclusão.
- **Revocação ~66%** — dos imóveis realmente comparáveis, o sistema encontra 2/3. Perde 1/3 dos comparáveis válidos.
- **Concordância humana de 85%** — alta concordância entre Laura e Lívia indica que a tarefa tem critérios bem definidos e o resultado é reprodutível.
- **Concordância com Kiro ~83-84%** — a rotulagem automática/por julgamento é coerente com a avaliação humana.

**Perfil do sistema:** Mais generoso que restritivo (revocação > precisão). Prefere incluir imóveis possivelmente irrelevantes do que perder comparáveis válidos. Para avaliação imobiliária, isso é uma estratégia razoável — melhor ter candidatos demais e filtrar depois (TRIMMEAN no Agente 5) do que perder informação.
