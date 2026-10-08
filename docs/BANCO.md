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

## Conferência manual

As colunas `faz_sentido` e `observacao` ficam vazias até alguém conferir a
avaliação.

```sql
-- Avaliações ainda não conferidas
SELECT id_execucao, data_hora, cidade, bairro, decisao, lance_maximo, valor_minimo
FROM execucoes
WHERE faz_sentido IS NULL
ORDER BY data_hora DESC;

-- Registrar a conferência
UPDATE execucoes
SET faz_sentido = true,
    observacao  = 'Comparáveis coerentes com o bairro.'
WHERE id_execucao = 'COLE_O_ID_AQUI';
```

## Apagar uma avaliação de teste

Apagar a execução apaga os comparáveis dela junto.

```sql
DELETE FROM execucoes WHERE id_execucao = 'COLE_O_ID_AQUI';
```
