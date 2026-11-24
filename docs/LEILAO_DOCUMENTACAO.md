# Leilão CAIXA — ROI, decisão, telas e calculadora

## Objetivo

Para um imóvel à venda pela CAIXA, responder: **vale a pena arrematar pelo valor mínimo?**
E **até quanto posso dar de lance** para o negócio continuar bom?

A resposta usa o valor de liquidez do Agente 5 como preço de venda e a conta da planilha
do professor ("Cálculo Preço.xlsx").

| Arquivo | O que faz |
|---|---|
| `services/leilao.py` | Conta do ROI, decisão, etapa do leilão, textos da tela e do laudo |
| `services/caixa_pagina.py` | Lê a página do imóvel no site da CAIXA (texto colado ou .html) |
| `services/leiloes_ativos.py` | Lista os imóveis de leilão do banco e grava a situação |
| `services/detalhe_leilao.py` | Grava e lê a tela completa de uma avaliação |
| `app/paginas/avaliacao.py` | Tela "Avaliação de imóvel" (formulário e resultado) |
| `app/paginas/leiloes_ativos.py` | Tela "Leilões ativos" (cards) |
| `app/calculadora.py` | Calculadora de simulação do menu lateral |
| `app/cronometro.py` | Contagem regressiva até o encerramento |
| `app/blocos_leilao.py` | Bloco "E no 2º leilão?" |

---

## A conta do investimento

Todos os percentuais estão no topo de `services/leilao.py`, e esse é o único lugar deles.

```
custos antes da venda = arrematação × (1 + 33%)
corretagem            = venda × 5%
IR                    = (venda − custos antes da venda) × 15%     (0 se negativo)
resultado             = venda − custos antes da venda − corretagem − IR
ROI                   = resultado ÷ custos antes da venda
```

- **Venda** = valor de liquidez do Agente 5 (90% do valor médio de mercado).
- **33%** (`CUSTOS_ANTES_DA_VENDA`) cobre tudo o que se paga antes de vender: comissão do
  leiloeiro, ITBI, registro, dívidas e reforma. A comissão do leiloeiro (5% no Leilão SFI e na
  Licitação Aberta) **já está dentro dos 33%**. Não é somada à parte.
- **Exemplo** (Campina da Barra, 2º leilão): arrematação R$ 207.000, venda R$ 444.783.
  Custos de R$ 275.310, corretagem de R$ 22.239, IR de R$ 25.421 e resultado de R$ 121.813.
  ROI de **44,25%**.

Funções:
- `conta_investimento(arrematacao, venda, ...)`: a conta acima. Os parâmetros opcionais
  (`custos_pct`, `corretagem_pct`, `ir_pct`, `custos_fixos` em R$) só são usados pela
  calculadora. Com os padrões, o resultado é igual ao da avaliação.
- `lance_para_roi(venda, roi)`: o maior lance que ainda dá aquele ROI (a conta ao contrário).
- `venda_para_empatar(arrematacao)`: a venda que dá ROI zero.

---

## A decisão

`avaliar_leilao` segue esta ordem:

1. **A estimativa é confiável?** Só segue se o Agente 5 terminou com status `ok` e
   `avaliacao_confiavel` (no mínimo 5 comparáveis, `MIN_AMOSTRAS_CONFIAVEL`). Se não, a resposta é
   **Sem estimativa**, sem ROI e sem lance.
2. **ROI pagando o valor mínimo da etapa atual:**

   | ROI | Decisão |
   |---|---|
   | 30% ou mais (`ROI_OPORTUNIDADE`) | Oportunidade |
   | 15% a 30% (`ROI_MARGEM_APERTADA`) | Margem apertada |
   | menos de 15% | Descartar |

   O valor exato do limite entra na faixa de cima.
3. **Lances:** `lance_maximo` é o lance que ainda dá 30%, e `lance_limite_descarte` o que
   ainda dá 15%. A tela mostra o lance que faz sentido para cada resposta
   (`lance_em_destaque`) e a tabela "Quanto dar de lance", com as 3 faixas
   (`faixas_de_lance`). Um lance nunca pode ser menor que o mínimo.

O **valor mínimo não entra em nenhum agente**. O preço de leilão fica bem abaixo do mercado
e distorceria a escolha dos comparáveis. O **valor de avaliação da CAIXA** é só
informativo. Quando o valor de mercado fica mais de 40% acima ou abaixo dele, aparece o
alerta `diferente_avaliacao_caixa` (ver `BANCO.md`).

`comparaveis_fora_da_regiao` conta os comparáveis usados que não foram confirmados
dentro da zona homogênea (status `fallback`, `sem_validacao` ou `mesmo_bairro`). Hoje ele
só é calculado e devolvido; a tela avisa sobre a zona por `texto_aviso_zona` e
`texto_aviso_raio`.

---

## Modalidades e etapa

Os nomes das modalidades são os do site da CAIXA (`MODALIDADES_CAIXA`). `etapa_atual`
escolhe o valor mínimo que vale agora, usando a hora de Brasília (`agora_brasilia`). O
Streamlit Cloud roda em UTC, e a hora do servidor erraria a etapa em 3 horas.

| Modalidade | Datas e valores | Comissão do leiloeiro |
|---|---|---|
| Leilão SFI | 1º e 2º leilão, cada um com data/hora e valor mínimo | 5%, paga pelo comprador |
| Licitação Aberta | data/hora de encerramento e valor mínimo | 5%, paga pelo comprador |
| Venda Online | data/hora de encerramento (cronômetro do site) e valor mínimo | não tem (corretagem da CAIXA) |
| Compra Direta | só valor mínimo; sem encerramento (vence a primeira proposta) | não tem (corretagem da CAIXA) |

**Leilão SFI:**
- Até a data do 1º leilão vale o 1º. Depois, até a data do 2º, vale o 2º. Depois disso,
  o leilão está encerrado.
- O 2º leilão **pode ser mais caro** que o 1º, porque no 2º o mínimo é a dívida. O código
  não supõe que o 2º é mais barato.
- No 1º leilão, a tela mostra o bloco **"E no 2º leilão?"** (`estimativa_na_etapa`) com
  a resposta, o ROI e os lances do 2º, usando a mesma liquidez. Fora isso,
  `texto_roi_outra_etapa` diz o ROI da outra etapa.
- Aviso fixo: "O antigo dono pode recomprar até a data do leilão" (direito de preferência).

**Situação manual** (`SITUACOES_LEILAO`): ativo, vendido, retirado ou suspenso. Um imóvel
está "ativo" quando a situação é ativa e o prazo não encerrou (`esta_ativo`).

---

## Leitura da página da CAIXA (`services/caixa_pagina.py`)

O site da CAIXA bloqueia acesso automático (CAPTCHA), então **o app não abre o link**. A
pessoa abre a página no navegador e traz o conteúdo de um destes jeitos:
- a página salva (Ctrl+S, arquivo .html);
- o texto copiado (Ctrl+A, Ctrl+C) e colado no formulário.

`ler_pagina_caixa` lê os campos pelos rótulos da página ("Valor mínimo de venda:",
"Matrícula(s):", "Data do 1º Leilão - ..."). **Nunca inventa valor.** O campo que não é
achado fica vazio e entra em `nao_encontrados`, para a pessoa preencher. Regras que valem
a pena conhecer:

- **Endereço** (`_endereco`): separa rua, número, complemento, bairro, CEP, cidade e UF.
  - O nome antigo da rua ("/ ANTIGA UA 16", "(ANTIGA RUA A)") sai da rua, porque a rua vai
    para o mapa e para a busca de anúncios.
  - "N. CS 16 CASA" não vira número. "CS 16" é a casa 16, e o texto vai para o complemento.
- **Casa em condomínio fechado:** o campo do formulário é marcado quando o endereço tem
  uma unidade ("CS 16", "CASA 03"), inclusive no formato "N. 151 CS 110", ou quando o
  endereço ou o título da página têm "COND" ou "CONDOMÍNIO". A pessoa pode desmarcar.
- **Banheiros:** a página não tem esse campo. São contados na descrição ("2 Wc",
  "wc Emp"). Lavabo e suíte não contam.
- **Área:** área menor que 10 m² é erro de cadastro e é ignorada.
- **Venda Online:** quando a data não aparece, o encerramento é calculado pelo tempo
  restante do texto colado e arredondado para 5 minutos.
- **Link:** quando o texto não traz o link, ele é montado pelo número do imóvel (`link_caixa`).
- **Gravame/penhora** na matrícula aparece em destaque no resultado e no card.
- **Formas de pagamento** e regras de despesas são só registradas. Não entram no cálculo.

---

## Telas

### Avaliação de imóvel (`app/paginas/avaliacao.py`)

É o formulário do imóvel. Quando o imóvel é da CAIXA, a pessoa cola a página e os campos
são preenchidos. O resultado mostra o cartão do leilão com:
- a decisão (com a cor);
- o ROI e a conta em uma linha (`texto_conta_linha`);
- o lance em destaque e a tabela de lances;
- o prazo, o cronômetro e os avisos.

O laudo TXT tem a seção "AVALIAÇÃO DE LEILÃO (CAIXA)" (`linhas_laudo`). A avaliação é
gravada no banco Neon. Mesmo sem anúncios, ela é gravada como "Sem estimativa" e aparece
nos leilões ativos.

### Leilões ativos (`app/paginas/leiloes_ativos.py`)

Mostra um card por imóvel de leilão avaliado (view `vw_leiloes_ativos`). Cada card tem:
- decisão, ROI, lance e "E no 2º leilão?";
- cronômetro até o encerramento (Compra Direta não tem);
- **Ver avaliação completa**: abre a tela do resultado como foi gravada (`detalhe_leilao`);
- **🧮 Simular**: preenche a calculadora com o lance mínimo e a liquidez do imóvel;
- **Situação + Salvar**: grava a situação manual (ativo, vendido, retirado, suspenso).
  Fora de "ativo", o imóvel some da lista.

A página tem filtros por decisão, modalidade e UF. A chave "Mostrar também os encerrados,
vendidos, retirados e suspensos" mostra os imóveis que saíram da lista.

---

## Calculadora de simulação (`app/calculadora.py`)

A calculadora fica no **menu lateral** da tela Leilões ativos, que abre expandido, e
continua visível quando a pessoa abre uma avaliação completa. Também aparece embaixo da
tela de Avaliação. **É só simulação: não muda nada gravado.**

- **Preenchimento:** o botão Simular de um card, ou a última avaliação (quando tem lance
  máximo), chama `pedir_simulacao(sugestao)`. Cada sugestão é aplicada **uma vez** (pelo
  `id`, em `calc_aplicadas`), antes de os campos serem criados. Depois disso, o que a pessoa
  mudar não é sobrescrito. Clicar em Simular de novo (`forcar=True`) recarrega os valores.
- **Campos:** arrematação e venda em R$.
- **Modo Simples:** um campo de custos antes da venda, com 33% de padrão.
- **Modo Detalhado:** os 33% abertos em partes.
  - Em % da arrematação: comissão do leiloeiro (5%; 0% na Venda Online e na Compra Direta,
    e nesse caso a reserva sobe 5 pontos), ITBI (3%), escritura e registro (1,5%) e reserva
    para imprevistos (23,5%).
  - Em R$: dívidas, reforma e outros.
  - Os padrões somam os mesmos 33%.
- **Corretagem e IR:** ficam numa parte que abre e fecha. O botão "Voltar aos padrões"
  restaura tudo.
- **Resultado:** decisão, ROI, a conta linha a linha, o lance para 30% e para 15% e a
  venda mínima sem prejuízo.

Os campos usam chaves `calc_*` no `st.session_state`. Os valores iniciais estão em `_INICIAIS`.

---

## Testes

Rodar com `.venv\Scripts\python.exe -m tests.<nome>`:

| Teste | O que cobre |
|---|---|
| `tests.test_leilao` | Conta, decisão, lances, etapas, textos |
| `tests.test_calculadora` | Parâmetros da conta e a calculadora na tela |
| `tests.test_tela_leilao` | Cartão do leilão no resultado |
| `tests.test_leiloes_ativos` | Lista, filtros e situação |
| `tests.test_detalhe_leilao` | Gravar e reabrir a avaliação completa |
| `tests.test_caixa_pagina` | Leitura da página da CAIXA |
