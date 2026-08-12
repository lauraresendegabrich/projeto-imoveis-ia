# Planilha do Professor — Lógica de Precificação

## Visão Geral

A planilha calcula o valor de um imóvel separando terreno e construção:

```
Valor do Imóvel = Valor do Terreno + Valor da Construção
Valor de Liquidez = Valor Médio × 0.90
```

## Células e Fórmulas

### C62 — Valor de Mercado do Terreno (MÍN)
```
= MIN(m²_terreno) × área_terreno
```
Pega o menor valor por m² entre os terrenos comparáveis e multiplica pela área do terreno do imóvel alvo.
- Se condominial (apartamento/sala): terreno = 0

### C63 — Valor de Mercado do Terreno (MÉD)
```
= IF(excluir_extremos="Sim", TRIMMEAN(m²_terreno, 0.5), AVERAGE(m²_terreno)) × área_terreno
```
Calcula a média dos terrenos (removendo extremos se escolhido) e multiplica pela área.
- TRIMMEAN(0.5): remove 25% menores + 25% maiores, calcula média do que sobra

### C64 — Valor de Mercado da Construção (MÍN)
```
= MIN(m²_construção) × área_construída
```
Menor valor por m² da construção × área construída.
- Se terreno puro: construção = 0

### C65 — Valor de Mercado da Construção (MÉD)
```
= IF(excluir_extremos="Sim", TRIMMEAN(m²_construção, 0.5), AVERAGE(m²_construção)) × área_construída
```
Média da construção (com ou sem extremos) × área construída.

### C68 — Valor Mínimo do Imóvel
```
= IF(condominial, C64, C62 + C64)
```
Se condominial: só construção. Senão: terreno + construção.

### C69 — Valor Médio
```
= IF(condominial, C65, C63 + C65)
```
Mesmo conceito com médias.

### C70 — Valor de Liquidez
```
= C69 × 0.90
```
Desconto de 10% sobre o valor médio para venda rápida.

## Dados de Entrada

### Ficha do Terreno
| Campo | Descrição |
|-------|-----------|
| Valor de Oferta | Preço pedido pelo terreno |
| Área de Terreno | m² do terreno |
| Topografia | Plano/Aclive/Declive |
| Valor M² | Calculado: oferta / área |

### Ficha da Construção
| Campo | Descrição |
|-------|-----------|
| Valor Oferta | Preço pedido pelo imóvel construído |
| Área Construída | m² da construção |
| Área de Terreno | m² do terreno (pra calcular m² construção descontando terreno) |
| M² Construção (MÍN/TERRENO) | (Oferta - terreno_estimado) / área_construída |
| M² Construção (MÉD/TERRENO) | Usando média do terreno |

### Regras
1. Exclusão de 10% do valor final (liquidez)
2. Exclusão dos extremos (TRIMMEAN 0.5) se escolhido
3. Valor de Liquidez de 10% sobre o valor médio
4. Não preencher Área de Terreno em Apartamentos e Salas
5. Se condominial, desprezo valor de terreno
6. Se não condominial, acho o valor de terreno e o remanescente é o valor da construção

## Tipos de Imóvel (Tabela)
- Casa
- Apartamento
- Terreno
- Sala
- Loja
- Galpão

## Exemplo Real (da planilha)
- Tipo: Casa
- Excluir extremos: Sim
- Área terreno: 300 m²
- Área construída: 250 m²
- Resultado:
  - Terreno (MÍN): R$ 161.157
  - Terreno (MÉD): R$ 228.785
  - Construção (MÍN): R$ 102.642
  - Construção (MÉD): R$ 346.265
  - Valor Mínimo: R$ 263.799
  - Valor Médio: R$ 575.050
  - Valor Liquidez: R$ 517.545
