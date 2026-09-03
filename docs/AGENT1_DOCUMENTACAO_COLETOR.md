# Agente 1 — Coletor de Dados Imobiliários

## Objetivo

Coletar imóveis comparáveis ao imóvel alvo. Usa Amazon Athena como fonte principal e Apify como fallback. Normaliza campos, filtra leilões/duplicatas e ordena por proximidade.

---

## Fontes de Dados

| Fonte | Papel | Quando roda |
|-------|-------|-------------|
| **Amazon Athena** | Fonte principal — banco S3 com milhares de anúncios | Sempre (se AWS configurado) |
| **Apify (ocrad)** | Fallback — scraping em tempo real | Só se Athena retornar < 10 imóveis |

---

## Fluxo Completo (8 etapas)

```
ETAPA 1 — ATHENA (fonte principal)
ETAPA 2 — APIFY (fallback se Athena < 10)
ETAPA 3 — NORMALIZAÇÃO DE CAMPOS
ETAPA 4 — COMBINAÇÃO (athena + apify)
ETAPA 5 — FILTROS + DEDUP COM MERGE (leilão, campos, duplicatas)
ETAPA 6 — ESCOPO (mantém só rua/bairro)
ETAPA 7 — ENRIQUECIMENTO (fotos)
ETAPA 8 — ORDENAÇÃO (rua > bairro > cidade)
```

---

## ETAPA 1 — Amazon Athena

Queries SQL na tabela `vivareal` (S3/Parquet).

### Limites por tipo (rua + bairro somados)

**Para `house`:**

| Tipo SQL | Limite total |
|----------|-------------|
| casa | 200 |
| two_story_house | 50 |
| village_house | 50 |
| residential_allotment_land | 60 |
| allotment_land | 60 |

**Para `apartment`:**

| Tipo SQL | Limite total |
|----------|-------------|
| apartamento | 200 |
| flat | 50 |
| cobertura | 50 |

### Lógica de busca — UMA query unificada por tipo

Para cada tipo, é feita **uma única query** que busca RUA **OU** BAIRRO ao mesmo
tempo. A mesma rua recebe prioridade 0, o restante do bairro recebe prioridade 1.
Isso substitui o modelo antigo de duas queries separadas (rua + bairro), reduzindo
consultas sobrepostas.

```sql
WITH candidatos AS (
    SELECT *,
           CASE WHEN <cond_rua> THEN 0
                WHEN <cond_bairro> THEN 1
                ELSE 2 END AS prioridade
    FROM vivareal
    WHERE cidade = 'Campinas'          -- comparado sem acento (translate)
      AND finalidade = 'venda'
      AND (<cond_rua> OR <cond_bairro>)
      AND estado = 'SP'
      AND tipo = 'casa'
), dedup AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY <chave_dedup>
               ORDER BY prioridade ASC, data_publicacao DESC NULLS LAST
           ) AS rn
    FROM candidatos
)
SELECT *
FROM dedup
WHERE rn = 1
ORDER BY prioridade ASC, data_publicacao DESC NULLS LAST
LIMIT 200
```

Pontos-chave:
- **`ROW_NUMBER() PARTITION BY <chave_dedup>`** deduplica já no SQL. A `<chave_dedup>`
  é: `url` → senão `__listing__<listing_id>` → senão um fingerprint amplo
  (cidade+bairro+rua+tipo+preço+área+quartos+título+data+fotos). Isso evita que
  URLs NULL caiam todas na mesma partição.
- **`ROW_NUMBER` também é aplicado em `buscar_cidade`** (fallback por cidade),
  então nenhuma consulta retorna URLs duplicadas.
- Quando não há rua, a prioridade é fixada em 1 (só bairro).

### Comparação tolerante a acento/caixa/prefixo (no próprio SQL)

A normalização acontece **dentro da query**, não em tentativas sequenciais. Cada
campo comparado passa por `lower()` + `translate()` (remove os acentos mais comuns)
+ `regexp_replace` (normaliza pontuação/espaços). As condições usam variantes com
`=` e `LIKE` combinadas por `OR`:

- **Bairro**: compara a forma canônica (ex.: "jardim guanabara"), a forma abreviada
  do prefixo ("jd guanabara") e a forma sem prefixo ("guanabara", só como igualdade
  para não confundir "Jardim Guanabara" com "Vila Guanabara").
- **Rua**: compara o nome completo, a chave sem prefixo (sem "rua"/"av"/etc.) e a
  última palavra (≥4 chars) como `LIKE`, cobrindo abreviações
  ("R. Dr. Liraucio Gomes" ≈ "Rua Doutor Liraucio Gomes").

Como o `translate()` remove acentos dos dois lados da comparação, o problema antigo
de "Cambui" ≠ "Cambuí" **deixou de existir**: a busca funciona com ou sem acento no
input e no banco.

### Quando o fallback cidade ativa

Só quando **nenhum tipo** encontrou nada localmente (rua + bairro = 0 para TODOS os
subtipos). Nesse caso, todos os subtipos são reconsultados por cidade inteira
(também com `ROW_NUMBER` para não duplicar). Se pelo menos 1 subtipo trouxe
resultado local, o fallback cidade NÃO ativa.

---

## ETAPA 2 — Apify (fallback)

Só roda se o total do Athena ficou **< 10 imóveis**.

| Portal | URL |
|--------|-----|
| VivaReal | `/venda/{estado}/{cidade}/bairros/{bairro}/{tipo}/` |
| LugarCerto | `/busca/compra-e-venda/{estado}/{cidade}/{bairro}/{tipo}` |

**Máximo de itens por URL (por tipo):** casa = 20 · terreno = 10 · apartamento = 30.

Usa o actor `ocrad/brazil-real-estate-scraper` no Apify:
- Envia URLs de listagem
- Actor abre com navegador headless, executa JavaScript
- Retorna anúncios

Depois acessa cada URL individual com `requests.get` para extrair:
- `publishedAt` (data publicação) do JSON embutido no HTML do VivaReal
- `description`, `bathrooms`, `parkingSpaces`, `street`/`streetNumber`
- `images` (hashes das fotos do VivaReal → URLs canônicas 870x653)

Cada imóvel do Apify é registrado individualmente no log, com resumo ao final:

```
[Ag1][Apify][Fotos] id=... | portal=VivaReal | fotos_retornadas=X | fotos_validas=X
[Ag1][Apify][Resumo Fotos] imoveis=X | com_fotos=X | sem_fotos=X | total_fotos=X
```

**Portais desativados:** OLX (Cloudflare), ImovelWeb (não retorna), MercadoLivre (não retorna), ZAP (95% duplicata do VivaReal). Só VivaReal e LugarCerto estão ativos.

---

## ETAPA 3 — Normalização de Campos

O Athena retorna strings. O código converte para tipos corretos:

| Campo Athena | Campo normalizado | Tipo |
|---|---|---|
| preco | price | float |
| area_construida | area | float |
| quartos | bedrooms | int |
| banheiros | bathrooms | int |
| vagas | parkingSpaces | int |
| bairro | neighborhood | str |
| cidade | city | str |
| estado | state | str |
| rua | street | str |
| data_publicacao | publishedAt | str |
| descricao | description | str |
| titulo | title | str |
| latitude / longitude | lat / lon | float |
| fotos_urls | images | list (split por `\|`) |
| tipo | propertyType | "Casas" / "Apartamentos" / "Terrenos" |

Templates das fotos resolvidos:
- `{description}` → "imovel"
- `{action}` → "fit-in"
- `{width}x{height}` → "870x653"

Os campos originais do Athena são **preservados** (strings). Os normalizados são **adicionados**. Ambos coexistem no JSON.

---

## ETAPA 4 — Combinação

```python
todos = athena_imoveis + apify_imoveis
```

Athena primeiro na lista.

---

## ETAPA 5 — Filtros e Deduplicação com Merge

| Filtro | O que remove |
|--------|-------------|
| **Leilão** | Título, tipo **ou descrição** contêm: "leilão", "hasta publica", "judicial", "arrematação", "caixa economica", "lance inicial", etc. (muitos leilões só se revelam na descrição) |
| **Campos obrigatórios** | Não tem `price` (> 0) OU não tem `city`/`neighborhood` |

### Deduplicação com merge (não descarta — combina)

Quando dois registros são o mesmo imóvel, eles são **fundidos** em vez de descartados.
O merge preserva o registro mais completo: une as fotos (até 30, sem repetir), mantém
a descrição/título mais longos e preenche campos vazios (lat/lon, publishedAt,
banheiros, vagas etc.). São 3 passos, nesta ordem:

1. **ID com namespace da fonte** — `<fonte>::<listing_id>`. O namespace evita colisão
   de IDs entre portais; Athena/S3 e VivaReal compartilham o namespace `vivareal`,
   permitindo casar os dois. IDs que na verdade são URLs ficam para o passo 2.
2. **URL normalizada** — remove parâmetros de tracking (`utm_*`, `gclid`, `fbclid`,
   `ref` etc.), barra final e normaliza domínio/protocolo antes de comparar.
3. **Fingerprint conservadora** — só para registros sem ID e sem URL. Exige
   título + fonte + localização + preço + área para não gerar falso positivo.

Essa deduplicação roda logo após combinar rua + bairro no Athena, novamente após
combinar Athena + Apify, e um diagnóstico é emitido antes do merge com o Apify:

```
[Ag1][Athena][Dedup-Diag] total=X | ids=Y | ids_duplicados=Z
```

---

## ETAPA 6 — Escopo

Verifica cada imóvel:
- `street` contém o nome da rua do alvo? OU
- `neighborhood` contém o nome do bairro do alvo?

Se sim → mantém. Se nenhum → descarta.

Normaliza acentos antes de comparar.

Se NENHUM imóvel passar → fallback: usa todos (cidade toda).

---

## ETAPA 7 — Enriquecimento

Imóveis sem fotos: `requests.get` na URL do VivaReal para extrair imagens do HTML.

---

## ETAPA 8 — Ordenação Final

| Prioridade | Critério |
|---|---|
| 0 (primeiro) | Mesma rua no campo `street` |
| 1 | Mesmo bairro no campo `neighborhood` |
| 2 (último) | Restante |

---

## Arquivos de Saída

| Arquivo | Conteúdo | Usado por |
|---------|----------|-----------|
| `data/imoveis_coletados_ag1.json` | Todos os imóveis (filtrados + ordenados) | Agente 2 (fallback) |
| `data/imoveis_completos_ag1.json` | Só os que têm `publishedAt` | **Agente 2** (entrada principal) |
| `data/imoveis_brutos_ocrad_ag1.json` | Brutos do Apify (debug) | Ninguém |

**Diferença:** `completos` = tem data de publicação. `coletados` = todos.

---

## Schema de Saída (exemplo real)

```json
{
  "url": "https://www.vivareal.com.br/imovel/2752976859",
  "titulo": "Apartamento 2 quartos à venda, 78 m² - Jardim Guanabara - Campinas/SP",
  "descricao": "Apartamento moderno no Condomínio Vizzi...",
  "tipo": "apartamento",
  "finalidade": "venda",
  "preco": "989990.0",
  "preco_condominio": "800.0",
  "iptu": "280.0",
  "area_construida": "78.0",
  "area_terreno": "88.0",
  "quartos": "2",
  "suites": "1",
  "banheiros": "2",
  "vagas": "2",
  "rua": "Rua Cônego Nery",
  "bairro": "Jardim Guanabara",
  "cidade": "Campinas",
  "estado": "SP",
  "cep": "13073180",
  "latitude": "-22.886324",
  "longitude": "-47.060136",
  "fotos_urls": "https://...{description}.jpg?action={action}...|...",
  "image_count": "31",
  "data_publicacao": "2024-10-30T17:37:51.871Z",
  "data_ultima_atualizacao": "2026-08-09T03:30:54.467Z",
  "amenities": "POOL|GOURMET_BALCONY|AIR_CONDITIONING|...",
  "preco_por_m2": "12692.18",
  "usage_types": "RESIDENTIAL",
  "property_sub_type": "APARTMENT",
  "andar": "0",
  "status_anuncio": "ACTIVE",
  "anunciante_nome": "Mega Imob",
  "listing_id": "2752976859",
  "portal": "vivareal",
  "data_coleta": "2026-08-09T12:35:41.217234",

  "source": "Athena/S3",
  "price": 989990.0,
  "area": 78.0,
  "bedrooms": 2,
  "bathrooms": 2,
  "parkingSpaces": 2,
  "neighborhood": "Jardim Guanabara",
  "city": "Campinas",
  "state": "SP",
  "street": "Rua Cônego Nery",
  "publishedAt": "2024-10-30T17:37:51.871Z",
  "description": "Apartamento moderno no Condomínio Vizzi...",
  "title": "Apartamento 2 quartos à venda, 78 m² - Jardim Guanabara - Campinas/SP",
  "lat": -22.886324,
  "lon": -47.060136,
  "propertyType": "Apartamentos",
  "images": ["https://...870x653...jpg", "..."],
  "imageCount": 30
}
```

---

## Dependências

| Pacote/Serviço | Uso | Configuração |
|---|---|---|
| `boto3` | Consultas Athena | Cadeia padrão de credenciais (env `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, perfil `~/.aws`, SSO ou IAM Role). Região via `AWS_REGION` (default `us-east-2`). Opcionais: `ATHENA_DATABASE`, `ATHENA_OUTPUT_LOCATION`, `ATHENA_WORKGROUP` |
| `requests` | Enriquecimento HTML + API Apify | Nenhuma |
| Apify (ocrad) | Scraping portais (fallback) | `APIFY_TOKEN_2` (ou `APIFY_TOKEN`) no `.env` |

---

## Como Rodar

```bash
# Pipeline completo
.venv/Scripts/python.exe -m app.main

# Teste isolado
.venv/Scripts/python.exe tests/test_ag1_isolado.py

# Teste casa + apartamento
.venv/Scripts/python.exe tests/test_ag1_casa_apto.py
```
