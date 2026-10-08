# Banco de avaliações (Neon / PostgreSQL)

Cada avaliação feita pela interface é gravada em duas tabelas (estrutura em
[`db/schema.sql`](../db/schema.sql)):

- **`execucoes`**: uma linha por avaliação (entrada, funil, cálculo, decisão).
- **`comparaveis`**: uma linha por anúncio da zona considerado pelo Agente 5,
  ligada pelo `id_execucao`. `tipo` segue a planilha: `construcao` (entra no m² da
  construção) ou `terreno` (entra no m² do terreno). `entrou_no_calculo = false`
  são anúncios da zona descartados (área < 10 m², sem preço/área ou R$/m² fora da
  faixa plausível).

Só a interface grava; scripts e testes (`app/graph.py`, `tests/`) não. A gravação
roda em segundo plano: se o banco falhar, a avaliação aparece normalmente e só fica
um aviso `[Banco]` no log.

## Configuração

- Localmente: `DATABASE_URL` no `.env`.
- Streamlit Cloud: `DATABASE_URL` em Settings → Secrets.
- As tabelas são criadas **manualmente** rodando `db/schema.sql` no SQL Editor do
  Neon (o app nunca cria tabelas). Rodar de novo é seguro.
- Mudanças num banco que já existe ficam em `db/migracoes/`, numeradas; rodar na
  ordem, antes de colocar no ar o código que depende delas.

## Consultas úteis (SQL Editor do Neon)

### Últimas avaliações

```sql
SELECT data_hora, cidade, uf, bairro, tipo, area_privativa,
       valor_minimo, lance_maximo, sobra, decisao, status_agente5
FROM execucoes
ORDER BY data_hora DESC
LIMIT 20;
```

### Funil de uma avaliação

```sql
SELECT anuncios_encontrados, repetidos, parecidos, confirmados_na_zona,
       usados_por_fallback, qtd_comparaveis_construcao, qtd_terrenos, raio_zona_m,
       valor_m2_construcao, valor_m2_terreno, valor_mercado, liquidez
FROM execucoes
WHERE id_execucao = 'COLE_O_ID_AQUI';
```

### Comparáveis de uma avaliação

```sql
SELECT tipo, entrou_no_calculo, status_zona, preco, area, valor_m2,
       endereco, bairro, portal, link
FROM comparaveis
WHERE id_execucao = 'COLE_O_ID_AQUI'
ORDER BY tipo, entrou_no_calculo DESC, valor_m2;
```

### Decisões por cidade

```sql
SELECT uf, cidade, decisao, count(*) AS avaliacoes,
       round(avg(sobra)) AS sobra_media
FROM execucoes
WHERE decisao IS NOT NULL
GROUP BY uf, cidade, decisao
ORDER BY uf, cidade, decisao;
```

### Avaliações com comparáveis fora da zona confirmada

Casos em que o valor usou anúncios por fallback ou sem validação de distância.

```sql
SELECT data_hora, cidade, bairro, usados_por_fallback,
       qtd_comparaveis_construcao, decisao
FROM execucoes
WHERE usados_por_fallback > 0
ORDER BY data_hora DESC;
```

### Por que saiu "Sem estimativa"

```sql
SELECT data_hora, cidade, bairro, status_agente5,
       qtd_comparaveis_construcao, qtd_terrenos,
       fontes->>'zona_calculada' AS zona_calculada,
       falhas->'avisos_agente5' AS avisos
FROM execucoes
WHERE decisao = 'Sem estimativa'
ORDER BY data_hora DESC;
```

### Tempo e IA usada em cada agente

```sql
SELECT data_hora, tempo_s,
       falhas->'tempos' AS tempos_por_agente,
       modelos_ia,
       falhas->'falhas' AS falhas
FROM execucoes
ORDER BY data_hora DESC
LIMIT 10;
```

## Alertas automáticos

Cada avaliação grava em `alertas` uma lista de sinais de atenção, calculados por
regras simples, sem IA e sem mudar nenhum cálculo (`services/alertas.py`). Lista
vazia = nada chamou atenção. Os limites ficam no início do arquivo.

| Código | Quando aparece |
|---|---|
| `poucos_comparaveis` | 3 a 4 comparáveis de construção no cálculo |
| `poucos_terrenos` | 3 a 4 terrenos, quando a casa separa terreno e construção |
| `fora_da_zona` | algum comparável do cálculo veio por fallback ou sem validação de distância |
| `precos_espalhados` | coeficiente de variação do R$/m² usado acima de 40% |
| `diferente_avaliacao_caixa` | valor de mercado mais de 40% acima ou abaixo do valor de avaliação CAIXA |
| `decisao_apertada` | sobra ou falta menor que 5% do valor mínimo |
| `possivel_alvo_no_calculo` | anúncio com perfil do próprio imóvel entrou na média |
| `falha_de_agente` | algum agente falhou na avaliação |

```sql
-- Avaliações com alertas
SELECT data_hora, cidade, bairro, decisao, alertas
FROM execucoes
WHERE jsonb_array_length(alertas) > 0
ORDER BY data_hora DESC;

-- Quantas vezes cada alerta apareceu
SELECT a->>'codigo' AS alerta, count(*) AS avaliacoes
FROM execucoes, jsonb_array_elements(alertas) AS a
GROUP BY 1
ORDER BY 2 DESC;
```

## Apagar uma avaliação de teste

Apagar a execução apaga os comparáveis dela junto.

```sql
DELETE FROM execucoes WHERE id_execucao = 'COLE_O_ID_AQUI';
```
