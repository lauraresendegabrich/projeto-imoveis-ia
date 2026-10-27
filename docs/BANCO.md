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

Cada alerta registra o motivo exato: `mensagem` (frase com os números reais e o
limite), `valor` e `limite` (os números comparados) e `detalhe` (o que causou: os
anúncios com endereço e link, os R$/m² extremos, o erro do agente...).

| Código | Quando aparece |
|---|---|
| `poucos_comparaveis` | 5 a 6 comparáveis de construção no cálculo (mínimo exigido: 5) |
| `poucos_terrenos` | 5 a 6 terrenos, quando a casa separa terreno e construção |
| `fora_da_zona` | algum comparável do cálculo está com a distância não verificada (fallback "zona não verificada" ou socorro sem validação); não estão comprovadamente longe, e contam para o mínimo de 5 |
| `precos_espalhados` | coeficiente de variação do R$/m² usado acima de 40% |
| `diferente_avaliacao_caixa` | valor de mercado mais de 40% acima ou abaixo do valor de avaliação CAIXA |
| `decisao_apertada` | sobra ou falta menor que 5% do valor mínimo |
| `possivel_alvo_no_calculo` | anúncio com perfil do próprio imóvel entrou na média |
| `falha_de_agente` | algum agente falhou na avaliação |
| `amostra_concentrada` | 30% ou mais das casas (com 6 ou mais) têm exatamente a mesma área ou o mesmo preço: provável empreendimento dominando a amostra |
| `terreno_fora_do_padrao` | terreno com R$/m² abaixo de 1/4 ou acima de 4x a mediana, ou área acima de 10x a mediana (preço digitado errado, gleba); avisa quando o cenário conservador vem dele |
| `area_diferente_entre_portais` | mesmo imóvel com áreas mais de 5% diferentes entre portais; casa/apto usa a menor área (lista as áreas de cada portal) |
| `possivel_repetido_no_calculo` | anúncios com mesmo preço, mesma área e mesmo número de endereço continuam no cálculo (sem prova para juntar) |

```sql
-- Motivo de cada alerta, um por linha
SELECT e.data_hora, e.cidade, e.bairro, e.decisao,
       a->>'codigo' AS alerta, a->>'mensagem' AS motivo, a->'detalhe' AS detalhe
FROM execucoes e, jsonb_array_elements(e.alertas) AS a
ORDER BY e.data_hora DESC;

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

## Entrada do usuário e checagem do próprio anúncio (migração 003)

`entrada_usuario` guarda tudo o que o formulário mandou, como foi digitado e como foi
lido (endereço, área, quartos, banheiros, vagas, preço, descrição completa, fotos e os
dados do leilão). `checagem_anuncio_alvo` guarda a checagem "é o anúncio do próprio
imóvel?" do Agente 2: quantos anúncios foram testados, confirmados (saem do cálculo) e
suspeitos (ficam, com alerta), e os 10 com mais sinais.

```sql
-- O que foi digitado e o que a checagem do próprio anúncio encontrou
SELECT data_hora, cidade, bairro,
       entrada_usuario->>'preco_digitado'        AS preco_digitado,
       entrada_usuario->>'preco_lido'            AS preco_lido,
       entrada_usuario->>'descricao_caracteres'  AS caracteres_descricao,
       checagem_anuncio_alvo->>'confirmados'     AS confirmados,
       checagem_anuncio_alvo->>'suspeitos'       AS suspeitos,
       checagem_anuncio_alvo->'maiores_pontuacoes'->0 AS mais_parecido
FROM execucoes
ORDER BY data_hora DESC
LIMIT 20;
```


## Verificações automáticas (migração 004)

Rodar `db/migracoes/004_verificacoes.sql` no SQL Editor do Neon **antes** de colocar
no ar o código que grava a coluna (sem ela, a gravação falha e as avaliações deixam de
ser registradas; o app continua funcionando). **Rodada no Neon em 21/10/2026.**

`verificacoes` guarda a lista das verificações feitas ao final de cada execução
(`services/verificacoes.py`), uma por regra: `{agente, verificacao, esperado,
encontrado, ok}`. `ok` é `true` (passou), `false` (falhou), `"alerta"` (pede
conferência, mas pode não ser erro; ex.: repetidos prováveis entre os usados) ou `null`
(não verificável: o agente não grava o dado). Não mudam nenhum cálculo.

```sql
-- Execuções com alguma verificação que falhou, e quais
SELECT e.data_hora, e.cidade, e.bairro,
       v->>'agente'      AS agente,
       v->>'verificacao' AS verificacao,
       v->>'esperado'    AS esperado,
       v->>'encontrado'  AS encontrado
FROM execucoes e, jsonb_array_elements(e.verificacoes) AS v
WHERE v->>'ok' = 'false'
ORDER BY e.data_hora DESC
LIMIT 50;

-- Quantas vezes cada verificação falhou
SELECT v->>'agente' AS agente, v->>'verificacao' AS verificacao, COUNT(*) AS falhas
FROM execucoes e, jsonb_array_elements(e.verificacoes) AS v
WHERE v->>'ok' = 'false'
GROUP BY 1, 2
ORDER BY falhas DESC;
```

## Imóveis de leilão e leilões ativos (migração 005)

Rodar `db/migracoes/005_imoveis_leilao.sql` no SQL Editor do Neon **antes** de colocar
no ar o código que grava a tabela e as colunas novas (sem elas, a gravação falha e as
avaliações deixam de ser registradas; o app continua funcionando). **Rodada no Neon** (conferido em 26/10/2026).

- **`imoveis_leilao`**: uma linha por imóvel (banco + código). O código é o número do
  imóvel só com os dígitos e sem zeros à esquerda (`855552271653-1` e o link
  `...hdnimovel=8555522716531` dão o mesmo imóvel). Avaliar de novo atualiza a linha
  sem apagar o que a nova avaliação não trouxe e sem mexer na `situacao`
  (`ativo` / `vendido` / `retirado` / `suspenso`, só manual). O imóvel só é gravado com
  o código e uma das 4 modalidades do site; sem isso, a execução é gravada sem ele.
- **`execucoes`**: ganha `id_imovel_leilao`, `etapa_avaliada` (1 ou 2 no Leilão SFI),
  `roi` (pagando o valor mínimo da etapa) e `lance_limite_descarte` (acima dele, ROI
  abaixo de 15%). `decisao` passa a ser Oportunidade / Margem apertada / Descartar /
  Sem estimativa; avaliações antigas continuam com "Não descartar".
- **`vw_leiloes`**: cada imóvel com a etapa atual, o próximo encerramento, se está
  ativo e a última avaliação. "Ativo" é calculado (situação `ativo` e prazo não
  encerrado), com a mesma regra de `services/leilao.py`. Datas no horário de Brasília.
  `etapa_mudou = true` quando a última avaliação foi feita em outra etapa (ex.: no 1º
  leilão, que já passou): o ROI gravado não vale para o valor mínimo atual.
- **`vw_leiloes_ativos`**: só os ativos, do encerramento mais próximo ao mais distante
  (Compra Direta, sem data, no fim).
- **Na interface**: página "Leilões ativos" (`app/pages/1_Leilões_ativos.py`), com
  cronômetro, filtros (resposta, modalidade, UF) e a mudança da situação. Quando a etapa
  mudou desde a avaliação, a resposta é refeita com o valor mínimo da etapa atual e a
  mesma liquidez (`services/leiloes_ativos.py`).

```sql
-- Leilões ativos com a última avaliação
SELECT numero_imovel, modalidade, etapa_atual, encerramento, cidade, bairro,
       valor_minimo_atual, decisao, roi, lance_maximo, etapa_mudou
FROM vw_leiloes_ativos;

-- Marcar um imóvel como vendido (sai dos ativos)
UPDATE imoveis_leilao SET situacao = 'vendido', atualizado_em = now()
WHERE banco = 'CAIXA' AND codigo = '8555522716531';

-- Histórico de avaliações de um imóvel
SELECT e.data_hora, e.etapa_avaliada, e.valor_minimo, e.liquidez, e.roi, e.decisao
FROM execucoes e JOIN imoveis_leilao i ON i.id = e.id_imovel_leilao
WHERE i.codigo = '8555522716531'
ORDER BY e.data_hora DESC;
```
