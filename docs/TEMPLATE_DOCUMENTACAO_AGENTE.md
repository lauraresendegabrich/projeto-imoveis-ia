# Agente N — Nome do Agente

## Objetivo

[Descrever em 2–3 frases o que o agente faz, qual problema resolve e como seu resultado alimenta o próximo agente do pipeline.]

---

## Problema Central

[Descrever o problema técnico ou conceitual que motivou a criação deste agente. Por que ele é necessário? O que aconteceria sem ele?]

---

## Abordagem Final

[Descrever a solução adotada e por que foi escolhida em relação às alternativas.]

---

## Fluxo Completo

```
1. [Primeiro passo]
   → [Detalhe técnico]
   → [Detalhe técnico]

2. [Segundo passo]
   → [Detalhe técnico]
   → [Detalhe técnico]

3. [Terceiro passo]
   → [Detalhe técnico]

...

N. Salva resultado
   → data/arquivo_saida.json
```

---

## Ferramentas / Abordagens Testadas e Descartadas

### 1. [Nome da ferramenta/abordagem]
**O que é:** [Descrição]
**Resultado:** [O que aconteceu quando testamos]
**Decisão:** Descartado. [Motivo objetivo]

### 2. [Nome da ferramenta/abordagem]
**O que é:** [Descrição]
**Resultado:** [O que aconteceu quando testamos]
**Decisão:** Descartado. [Motivo objetivo]

---

## Decisões Técnicas Relevantes

### [Título da decisão]
**Problema identificado:** [O que motivou a decisão]
**Alternativas consideradas:** [O que mais foi avaliado]
**Solução adotada:** [O que foi implementado e por quê]

---

## Arquivos Gerados

| Arquivo | Conteúdo | Usado por |
|---|---|---|
| `data/arquivo.json` | [Descrição] | [Próximo agente ou componente] |

---

## Schema de Saída

```json
{
  "campo": "valor",
  "campo2": 123
}
```

---

## Resultado dos Testes

```
[Dados reais do teste mais recente — cidade, data, números concretos]
```

---

## Entrada

### Parâmetros da função principal

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `param1` | str | [Descrição] |
| `param2` | int | [Descrição] |

### Fonte dos dados de entrada
- [De onde vêm os dados — arquivo gerado por agente anterior, parâmetro direto, etc.]

---

## Dependências Externas

| Serviço | Uso | Custo | Configuração |
|---|---|---|---|
| [Serviço] | [Para quê] | [Gratuito / Pago] | `CHAVE` no `.env` |

---

## Instalação das Dependências

```bash
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/pip install [pacotes adicionais]
```

| Pacote | Uso |
|---|---|
| `pacote` | [Para quê é usado] |

---

## Como Rodar

```bash
.venv/Scripts/python.exe -m tests.test_[agente]
```

**Pré-requisitos:**
- [Arquivo ou configuração necessária]
- [Chave de API necessária]
