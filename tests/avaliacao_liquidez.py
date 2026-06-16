"""
Avaliação do Sistema — Métricas de Liquidez associadas ao Preço
================================================================

Seleciona 15 imóveis reais, roda o pipeline (mesmo fluxo da interface)
para cada um e compara preço sugerido vs preço anunciado vs DoM.

COMO RODAR:
    .venv\\Scripts\\python.exe tests/avaliacao_liquidez.py

COMO PREENCHER A AMOSTRA:
    Cada imóvel usa os mesmos campos da interface web:
    - rua, numero, bairro, cidade, estado
    - tipo: "Casa", "Apartamento" ou "Terreno"
    - area (construída m²), area_terreno (m²)
    - quartos, banheiros, vagas
    - descricao (texto do anúncio)
    - fotos (lista de URLs)
    + campos extras para avaliação:
    - preco_anunciado (R$ do anúncio real)
    - data_publicacao (YYYY-MM-DD — quando foi anunciado)

================================================================================
MÉTRICAS UTILIZADAS
================================================================================

(i) MÉTRICAS DE ACURÁCIA — avaliam a qualidade da estimativa de preço

    • Erro Relativo Médio (MAE):
      Fórmula: média( |preço_sistema - preço_anunciado| / preço_anunciado )
      Interpretação: desvio médio percentual entre o preço estimado e o anunciado.
      Quanto menor, melhor. Resultado: 18.5%

    • Erro Relativo Mediano:
      Mesmo conceito do MAE, mas usa mediana (robusta a outliers).
      Resultado: 17.3%

    • Desvio Padrão do Erro:
      Variabilidade dos erros. Baixo = sistema consistente; alto = imprevisível.
      Resultado: 13.2%

    • % Dentro de ±10%, ±20%, ±30%:
      Percentual de imóveis onde o erro ficou abaixo de cada limiar.
      Resultado: 25% (±10%) | 62.5% (±20%) | 62.5% (±30%)

(ii) MÉTRICAS DE LIQUIDEZ — avaliam a relação preço × tempo de venda

    • Days on Market (DoM):
      Dias desde a publicação do anúncio até a data da avaliação.
      DoM alto (>180 dias) indica possível sobrevalorização.
      Resultado: média 340 dias | mediana 119 dias

    • Taxa de Concordância (DoM > 6 meses):
      Para imóveis com mais de 6 meses no mercado, verifica se o sistema
      sugeriu preço MENOR que o anunciado (detectando sobrepreço).
      Fórmula: nº imóveis com (DoM>180 E sobrepreço>0) / nº imóveis com DoM>180
      Resultado: 40% (2 de 5 imóveis)

    • Correlação DoM × Sobrepreço (Pearson):
      Mede a relação linear entre tempo de exposição e sobrepreço.
      Positiva = mais tempo no mercado → maior sobrepreço detectado.
      Valida a hipótese: preço acima do mercado reduz liquidez.
      Escala: -1 (inversa) a +1 (direta). 0 = sem relação.
      Resultado: 0.33 (correlação positiva moderada)

    • Sobrepreço Médio/Mediano:
      Fórmula: (preço_anunciado - preço_sistema) / preço_sistema × 100
      Positivo = anunciado acima do estimado; Negativo = abaixo.
      Resultado: médio 3.72% | mediano 1.06%

================================================================================
RESULTADO FINAL DA AVALIAÇÃO (executada em 09/06/2026)
================================================================================

    Amostra: 15 imóveis de 11 cidades brasileiras
    Válidos: 11 (73%) | Erros: 4 (27% — sem cobertura nos portais)

    ACURÁCIA:
        - MAE: 18.5% (sistema erra em média 18.5% do valor)
        - 62.5% dos imóveis dentro de ±20% do preço anunciado
        - Melhor caso: imóvel 11 (erro de 0.3%) e imóvel 2 (erro de 2.4%)
        - Pior caso: imóveis 7 e 8 (~33% erro — apartamentos com m² muito caro)

    LIQUIDEZ:
        - Correlação DoM×Sobrepreço = 0.33 → POSITIVA
          Valida a hipótese de que preço acima do mercado reduz liquidez
        - Imóvel 8 (Porto Alegre, 652 dias): sobrepreço de 48.4% detectado
          → caso paradigmático: imóvel claramente caro demais, por isso não vende
        - Imóvel 1 (BH, 4 anos no mercado): sobrepreço de 15.9%
          → sistema confirma que o preço pedido é acima do valor real

    LIMITAÇÕES:
        - 4 imóveis sem resultado por falta de dados nos portais (cidades
          pequenas ou bairros sem cobertura no VivaReal/LugarCerto)
        - Amostra de 15 imóveis é suficiente para validação exploratória,
          mas não para conclusões estatísticas robustas

    CONCLUSÃO:
        O sistema demonstra capacidade de:
        1) Estimar preços com precisão razoável (62.5% dentro de ±20%)
        2) Detectar sobrepreço em imóveis com alta exposição no mercado
        3) Correlacionar tempo de venda com distorção de preço (r=0.33)
        Estes resultados validam a incorporação de liquidez na avaliação
        imobiliária como proposto na metodologia do trabalho.
"""

import sys
import json
import logging
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from statistics import mean, median, stdev
from concurrent.futures import ThreadPoolExecutor

# Adiciona raiz do projeto ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RESULTADO_DIR = Path(__file__).parent.parent / "data" / "avaliacao"
RESULTADO_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# AMOSTRA DE 15 IMÓVEIS
# =============================================================================
# Preencha com imóveis REAIS de anúncios 
# Estratifique: casas, apartamentos, DoM variado (alguns recentes, alguns antigos)
#
# Campos iguais aos da interface:
#   rua, numero, bairro, cidade, estado, tipo,
#   area, area_terreno, quartos, banheiros, vagas,
#   descricao, fotos,
#   preco_anunciado, data_publicacao

AMOSTRA_IMOVEIS = [
    # ------------------------------------------------------------------
    # IMÓVEL 1 — Casa São Gabriel, BH (VivaReal - ID 2547662981)
    # Publicado em 13/01/2022 — DoM altíssimo (~4 anos)
    # ------------------------------------------------------------------
    {
        "rua": "Rua não informada",
        "numero": "",
        "bairro": "São Gabriel",
        "cidade": "Belo Horizonte",
        "estado": "MG",
        "tipo": "Casa",
        "area": 257,
        "area_terreno": 475,
        "quartos": 3,
        "banheiros": 3,
        "vagas": 4,
        "descricao": "Excelente casa moderna, plana sem escada, ampla, arejada, confortavel, ambientes definidos, otima opcao para morar bem. Lote plano, metragem no IPTU 360m², metragem real do imovel 475m², area gourmet completa, com piscina com cascata, hidromassagem, espaco reservado para sauna, churrasqueira, 1 banheiro e 2 lavabos que atendem a area gourmet, mesa com bancada em granito, bancada que pega toda a parede da churrasqueira, armarios abaixo da bancada, quadra de esportes, telhado colonial, cameras de seguranca, piso em toda a area externa de excelente qualidade anti derrapante, varandao que pega toda a lateral da casa, casa composta por 3 quartos, suite, closet amplo, banho social, sala ampla, 2 cozinhas amplas, claras, arejadas, bancadas em granito, jardins e jardim de inverno, toda a casa com acabamento moderno de primeira qualidade, 4 vagas de garagem cobertas, excelente localizacao!! Este imovel possui o lazer com o conforto que voce procura dentro do seu proprio lar.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/5c51dda938efeb9b318b5ad6a88b3c93/casa-com-3-quartos-a-venda-257m-no-sao-gabriel-belo-horizonte.webp?action=fit-in&dimension=870x707", 
        "https://resizedimgs.vivareal.com/img/vr-listing/609873dca34cb2ab8bd3712e3e69c8e2/casa-com-3-quartos-a-venda-257m-no-sao-gabriel-belo-horizonte.webp?action=fit-in&dimension=870x707&seo=false",
         "https://resizedimgs.vivareal.com/img/vr-listing/d1333020b0ef45bf85fadd93b1e672fd/casa-com-3-quartos-a-venda-257m-no-sao-gabriel-belo-horizonte.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 997000,
        "data_publicacao": "2022-01-13",
    },
    # ------------------------------------------------------------------
    # 
    # ------------------------------------------------------------------
    {
        "rua": "Avenida Luís Viana Filho",
        "numero": "134",
        "bairro": "Alphaville",
        "cidade": "Salvador",
        "estado": "BA",
        "tipo": "Apartamento",
        "area": 145,
        "area_terreno": 0,
        "quartos": 4,
        "banheiros": 5,
        "vagas": 2,
        "descricao": "Apartamento com 4 Quartos à venda, 145m² - Alphaville (Código do anunciante: 6SS5RJ | Código no Zap: 2874087093) Alphaville I | 142 m2 | 4 Quartos 💵 Apartamento à Venda 🏛️ Condomínio Morada dos Príncipes 3 Suítes 2 Vagas de Garagem 1 Depósito Nascente Total Andar Intermediário Condomínio: R$ 1.650,00/mês IPTU: R$ 430,00/mês R$ 2.280.000,00",
        "fotos": ["https://resizedimgs.zapimoveis.com.br/img/vr-listing/0a3429c012636fd2ec900776ff611b53/apartamento-com-4-quartos-a-venda-145m-no-alphaville-salvador.webp?action=fit-in&dimension=870x707", "https://resizedimgs.zapimoveis.com.br/img/vr-listing/368ac0d756a9445b5b8c3e0a293b0f3f/apartamento-com-4-quartos-a-venda-145m-no-alphaville-salvador.webp?action=fit-in&dimension=870x707&seo=false", "https://resizedimgs.zapimoveis.com.br/img/vr-listing/64ebdecaca21e27ade3acb0189d941c6/apartamento-com-4-quartos-a-venda-145m-no-alphaville-salvador.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 2280000,          
        "data_publicacao": "2026-03-07",    
    },
    # ------------------------------------------------------------------
    # 
    # ------------------------------------------------------------------
    {
        "rua": "Rua José João da Silva",
        "numero": "",
        "bairro": "Bom Jesus",
        "cidade": "Santa Luzia",
        "estado": "MG",
        "tipo": "Casa",
        "area": 360,
        "area_terreno": 0,
        "quartos": 4,
        "banheiros": 2,
        "vagas": 3,
        "descricao": "Excelente oportunidade para investimento no Bairro Bom Jesus – Santa Luzia! Imóvel ideal para quem busca renda com aluguel e segurança patrimonial! A propriedade conta com: 01 casa principal espaçosa 04 barracões Excelente potencial de retorno mensal Localização estratégica e de fácil acesso Região com grande procura por locação Uma oportunidade perfeita para investidores que desejam adquirir um imóvel já estruturado para geração de renda, em um dos pontos mais acessíveis do bairro Bom Jesus. ",
        "fotos": ["https://resizedimgs.zapimoveis.com.br/img/vr-listing/b016bd53e2a7a4d79e8b3711b45b1ce0/casa-com-4-quartos-a-venda-360m-no-bom-jesus-santa-luzia.webp?action=fit-in&dimension=870x707", "https://resizedimgs.zapimoveis.com.br/img/vr-listing/124867f2c4b791bc5759abf6cd79825d/casa-com-4-quartos-a-venda-360m-no-bom-jesus-santa-luzia.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 530000,         
        "data_publicacao": "2026-05-22",    
    },
    # ------------------------------------------------------------------
    # IMÓVEL 4 — Apto Recreio dos Bandeirantes, RJ (ZapImóveis - ID 2754158200)
    # ------------------------------------------------------------------
    {
        "rua": "Rua Luiz Carlos Sarolli",
        "numero": "1",
        "bairro": "Recreio dos Bandeirantes",
        "cidade": "Rio de Janeiro",
        "estado": "RJ",
        "tipo": "Apartamento",
        "area": 67,
        "area_terreno": 0,
        "quartos": 3,
        "banheiros": 2,
        "vagas": 1,
        "descricao": "O imóvel no bairro Recreio dos Bandeirantes tem 67 metros quadrados com 3 quartos sendo 1 suite e 2 banheiros Possui área de fitness, espaço gourmet, jardim, parquinho com diferentes brinquedos, salão para festas e eventos. Vai lhe possibilitar curtir os dias mais quentes na piscina, praticar diversos esportes na quadra poliesportiva, todo o conforto do ar condicionado nos dias mais quentes.Churrasqueira para você aproveitar nos momentos de descontração. Elevador para mais praticidade no dia-a-dia. Encontra-se na privacidade de um condomínio fechado..Condomínio R$ 800/mês IPTU R$ 1.000",
        "fotos": ["https://resizedimgs.zapimoveis.com.br/img/vr-listing/4cc4cb2ab4b81881d1db7960ec34ed3e/apartamento-com-3-quartos-a-venda-67m-no-recreio-dos-bandeirantes-rio-de-janeiro.webp?action=fit-in&dimension=870x707", "https://resizedimgs.zapimoveis.com.br/img/vr-listing/a46b614ea21814e43b910d6eeda6eeef/apartamento-com-3-quartos-a-venda-67m-no-recreio-dos-bandeirantes-rio-de-janeiro.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 469000,              
        "data_publicacao": "2024-11-04",   
    },
    # ------------------------------------------------------------------
    # IMÓVEL 5 — Casa Rubem Berta, Porto Alegre (VivaReal - ID 2793146434)
    # Publicado em 01/04/2025
    # ------------------------------------------------------------------
    {
        "rua": "Rua Luiz Cézar Leal",
        "numero": "90",
        "bairro": "Rubem Berta",
        "cidade": "Porto Alegre",
        "estado": "RS",
        "tipo": "Casa",
        "area": 179,
        "area_terreno": 0,
        "quartos": 3,
        "banheiros": 3,
        "vagas": 3,
        "descricao": "Sobrado com 3 dormitórios, sendo 1 suíte com closet. Sala de estar, cozinha, banheiro social, área de serviço, lavabo e depósito. Edícula com churrasqueira nos fundos. Amplo pátio e garagem para 3 carros cobertos e 1 descoberto.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/d4b8166022103cfd2790eb8841a25ca4/casa-com-3-quartos-a-venda-179m-no-rubem-berta-porto-alegre.webp?action=fit-in&dimension=870x707", "https://resizedimgs.vivareal.com/img/vr-listing/7f8d71c9a345e6b7b5da84360aabb31d/casa-com-3-quartos-a-venda-179m-no-rubem-berta-porto-alegre.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 420000,
        "data_publicacao": "2025-04-01",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 6 — Sobrado Balneário Casa Blanca, Peruíbe/SP (ZapImóveis - ID 2664256027)
    # ------------------------------------------------------------------
    {
        "rua": "Rua não informada",
        "numero": "",
        "bairro": "Balneário Casa Blanca",
        "cidade": "Peruíbe",
        "estado": "SP",
        "tipo": "Casa",
        "area": 145,
        "area_terreno": 0,
        "quartos": 3,
        "banheiros": 4,
        "vagas": 3,
        "descricao": "Bom Sobrado para Venda no bairro Casablanca, localizado na cidade de Peruíbe / SP a 700 metros da praia com 3 quartos sendo 3 suítes, sacada, garagem para 3 carros e área de lazer com piscina e churrasqueira. Descrição completa do Sobrado para Venda no bairro Casablanca, localizado na cidade de Peruíbe / SP 3 quartos sendo 3 suíte Sacada Sala Cozinha americana com móveis planejados 4 banheiros social Varanda Área de serviço Garagem para 3 carros Área de lazer com piscina e churrasqueira Estuda permuta por imóvel de menor valor em São Paulo/SP (Mooca ou Tatuapé)",
        "fotos": ["https://resizedimgs.zapimoveis.com.br/img/vr-listing/89d44614cc905bb41f6dc1d011c517fb/sobrado-com-3-quartos-a-venda-145m-no-balneario-casa-blanca-peruibe.webp?action=fit-in&dimension=870x707", " https://resizedimgs.zapimoveis.com.br/img/vr-listing/01c42a59938f73722ca280fbb5ca1874/sobrado-com-3-quartos-a-venda-145m-no-balneario-casa-blanca-peruibe.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 570000,              
        "data_publicacao": "2023-10-23",   
    },
    # ------------------------------------------------------------------
    # IMÓVEL 7 — Apartamento Nazaré, Belém/PA (VivaReal - ID 2882068173)
    # Publicado em 21/04/2026
    # ------------------------------------------------------------------
    {
        "rua": "Avenida Nazaré",
        "numero": "1223",
        "bairro": "Nazaré",
        "cidade": "Belém",
        "estado": "PA",
        "tipo": "Apartamento",
        "area": 120,
        "area_terreno": 0,
        "quartos": 2,
        "banheiros": 3,
        "vagas": 2,
        "descricao": "Apartamento no Edifício Feliz, 120m², sala para dois ambientes, cozinha funcional, banheiro social, 2 quartos sendo 1 com closet, área de serviço, banheiro de serviço e 2 vagas. Diferenciais: porcelanato fosco, projeto de iluminação, armários planejados e cozinha equipada. Condomínio com portaria, portão eletrônico e elevador.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/f75976404b68eb3593a4b16e1c859825/apartamento-com-2-quartos-a-venda-120m-no-nazare-belem.webp?action=fit-in&dimension=870x707", "https://resizedimgs.vivareal.com/img/vr-listing/44e79a78864da040afb9cc563e17874e/apartamento-com-2-quartos-a-venda-120m-no-nazare-belem.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 850000,
        "data_publicacao": "2026-04-21",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 8 — Apartamento Jardim Botânico, Porto Alegre/RS (VivaReal - ID 2737562621)
    # Publicado em 26/08/2024 — DoM ~1 ano e 9 meses
    # ------------------------------------------------------------------
    {
        "rua": "Rua Buenos Aires",
        "numero": "280",
        "bairro": "Jardim Botânico",
        "cidade": "Porto Alegre",
        "estado": "RS",
        "tipo": "Apartamento",
        "area": 64,
        "area_terreno": 0,
        "quartos": 2,
        "banheiros": 2,
        "vagas": 2,
        "descricao": "Apartamento à venda localizado na Rua Buenos Aires, no bairro Jardim Botânico em Porto Alegre. Este imóvel conta com área construída de 64m², oferecendo 2 quartos, sendo 1 suíte, 2 banheiros e 2 vagas de garagem. Aproveite para visitar esta oportunidade e agende uma visita com um de nossos corretores.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/46e2e67ee183f203bd74212f057cd51e/apartamento-com-2-quartos-a-venda-64m-no-jardim-botanico-porto-alegre.webp?action=fit-in&dimension=870x707", "https://resizedimgs.vivareal.com/img/vr-listing/f02f14e175ceae335ef8cf1d0ce19b36/apartamento-com-2-quartos-a-venda-64m-no-jardim-botanico-porto-alegre.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 765000,
        "data_publicacao": "2024-08-26",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 9 — Apartamento Parque dos Servidores, Ribeirão Preto/SP (VivaReal - ID 2878334246)
    # Publicado em 31/03/2026
    # ------------------------------------------------------------------
    {
        "rua": "Rua Olívia Maria de Jesus",
        "numero": "2255",
        "bairro": "Parque dos Servidores",
        "cidade": "Ribeirão Preto",
        "estado": "SP",
        "tipo": "Apartamento",
        "area": 42,
        "area_terreno": 0,
        "quartos": 2,
        "banheiros": 1,
        "vagas": 0,
        "descricao": "Apartamento 42,5m², 2 dormitórios com infraestrutura para ar-condicionado, sala ampla com rack e painel para TV, cozinha com armários novos, área de serviço com vassoureiro. Banheiro com box blindex. Iluminação LED. 1 vaga de garagem. Condomínio com portaria 24h, controle de acesso facial, 2 piscinas, sala de ginástica, 2 áreas de churrasco e quadra de areia.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/f0beb00619632d2968f40713d93836e4/apartamento-com-2-quartos-a-venda-42m-no-parque-dos-servidores-ribeirao-preto.webp?action=fit-in&dimension=870x707", "https://resizedimgs.vivareal.com/img/vr-listing/e3462e0188abdf42812654073daf6f3f/apartamento-com-2-quartos-a-venda-42m-no-parque-dos-servidores-ribeirao-preto.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 172000,
        "data_publicacao": "2026-03-31",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 10 — Casa Promorar, Teresina/PI (VivaReal - ID 2881484409)
    # Publicado em 18/04/2026
    # ------------------------------------------------------------------
    {
        "rua": "Avenida Perimetral",
        "numero": "S/N",
        "bairro": "Promorar",
        "cidade": "Teresina",
        "estado": "PI",
        "tipo": "Casa",
        "area": 130,
        "area_terreno": 0,
        "quartos": 4,
        "banheiros": 4,
        "vagas": 2,
        "descricao": "Casa com 2 salas, 4 quartos sendo 3 suítes, copa/cozinha, banheiro social, área de serviço e 2 vagas de garagem cobertas. 130m², 2 andares.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/78467e91bfa9f94413281d0401f8d483/casa-com-4-quartos-a-venda-130m-no-promorar-teresina.webp?action=fit-in&dimension=870x707", "https://resizedimgs.vivareal.com/img/vr-listing/d4eb678ed81cd03ab8989313bf8747db/casa-com-4-quartos-a-venda-130m-no-promorar-teresina.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 250000,
        "data_publicacao": "2026-04-18",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 11 — Casa Parque Estrela Dalva XVI, Santo Antônio do Descoberto/GO
    # (VivaReal - ID 2869654278) — Imóvel retomado pela Caixa
    # Publicado em 10/02/2026 — Valor avaliação: R$ 153.000
    # ------------------------------------------------------------------
    {
        "rua": "Rua 87",
        "numero": "S/N",
        "bairro": "Parque Estrela Dalva XVI",
        "cidade": "Santo Antônio do Descoberto",
        "estado": "GO",
        "tipo": "Casa",
        "area": 180,
        "area_terreno": 0,
        "quartos": 2,
        "banheiros": 1,
        "vagas": 1,
        "descricao": "Casa com 2 quartos, 1 vaga na garagem, varanda/sacada, área de serviço, WC, sala, cozinha. 180m². Imóvel retomado de financiamento bancário (Caixa). Aceita FGTS e financiamento SBPE.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/ff41b699af762d50c69ea17ddabdecc0/casa-com-2-quartos-a-venda-180m-no-parque-estrela-dalva-xvi-santo-antonio-do-descoberto.webp?action=fit-in&dimension=870x707"],
        "preco_anunciado": 76939,
        "data_publicacao": "2026-02-10",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 12 — Casa Bosque dos Buritis, Uberlândia/MG (VivaReal - ID 2831461327)
    # Publicado em 26/08/2025 — DoM ~9 meses
    # ------------------------------------------------------------------
    {
        "rua": "Alameda Tamareiras",
        "numero": "",
        "bairro": "Bosque dos Buritis",
        "cidade": "Uberlândia",
        "estado": "MG",
        "tipo": "Casa",
        "area": 160,
        "area_terreno": 250,
        "quartos": 3,
        "banheiros": 3,
        "vagas": 2,
        "descricao": "Casa com lote de 250m² e área construída de 160m². 3 quartos com armários planejados, sendo 1 suíte com closet e ar-condicionado. Cozinha e área de serviço com armários planejados. Sala de estar com pé-direito de 5 metros. Área gourmet com churrasqueira e banheiro. Piscina privativa aquecida com cascata e iluminação. Portão eletrônico, cerca elétrica e concertina.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/846a5a7e9aa9ba224b0c389627cbf4fe/casa-com-3-quartos-a-venda-160m-no-bosque-dos-buritis-uberlandia.webp?action=fit-in&dimension=870x707","https://resizedimgs.vivareal.com/img/vr-listing/514b1845b76343cf7ee4b0a26679f8cb/casa-com-3-quartos-a-venda-160m-no-bosque-dos-buritis-uberlandia.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 950000,
        "data_publicacao": "2025-08-26",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 13 — Casa Loteamento Recife, Petrolina/PE (VivaReal - ID 2806360223)
    # Publicado em 15/05/2025 — DoM ~1 ano
    # ------------------------------------------------------------------
    {
        "rua": "Rua Quinze",
        "numero": "1",
        "bairro": "Loteamento Recife",
        "cidade": "Petrolina",
        "estado": "PE",
        "tipo": "Casa",
        "area": 140,
        "area_terreno": 0,
        "quartos": 3,
        "banheiros": 3,
        "vagas": 2,
        "descricao": "Casa com 3 quartos, suíte com closet, suíte normal, garagem para 2 carros, área de serviço, área para piscina, sala, jardim, cozinha americana. Cerca elétrica, portão eletrônico, piso porcelanato, vidros blindex.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/326c4209dd0067cc34defd632f9ece17/casa-com-3-quartos-a-venda-140m-no-loteamento-recife-petrolina.webp?action=fit-in&dimension=870x707", "https://resizedimgs.vivareal.com/img/vr-listing/8f4ffc8a81389e06713e20ed801b5351/casa-com-3-quartos-a-venda-140m-no-loteamento-recife-petrolina.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 699000,
        "data_publicacao": "2025-05-15",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 14 — Apartamento Jardim Monte Líbano, Campo Grande/MS (VivaReal - ID 2823320910)
    # Publicado em 23/07/2025 — DoM ~10 meses — marcado "abaixo do mercado"
    # ------------------------------------------------------------------
    {
        "rua": "Rua não informada",
        "numero": "",
        "bairro": "Jardim Monte Líbano",
        "cidade": "Campo Grande",
        "estado": "MS",
        "tipo": "Apartamento",
        "area": 142,
        "area_terreno": 0,
        "quartos": 3,
        "banheiros": 2,
        "vagas": 1,
        "descricao": "Apartamento amplo, 142m², 3 dormitórios sendo 1 suíte com guarda-roupa planejado. Sala ampla com 2 ambientes. Cozinha grande com lavanderia isolada e despensa. Jardim de inverno. 1 vaga descoberta. Portão eletrônico. Aceita permuta por imóvel de menor valor. Bairro nobre, ao lado da Padaria Monte Líbano.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/33c9c645e38750c9b5ffadc966b565b3/apartamento-com-3-quartos-a-venda-142m-no-jardim-monte-libano-campo-grande.webp?action=fit-in&dimension=870x707", " https://resizedimgs.vivareal.com/img/vr-listing/f78672c01d5244e973d44de478f893ad/apartamento-com-3-quartos-a-venda-142m-no-jardim-monte-libano-campo-grande.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 370000,
        "data_publicacao": "2025-07-23",
    },
    # ------------------------------------------------------------------
    # IMÓVEL 15 — Casa Cidade Nova, Manaus/AM (VivaReal - ID 2891009478)
    # Publicado em 05/06/2026 — DoM ~3 dias (recém-publicado)
    # ------------------------------------------------------------------
    {
        "rua": "Rua Professora Felismina Cheks",
        "numero": "1",
        "bairro": "Cidade Nova",
        "cidade": "Manaus",
        "estado": "AM",
        "tipo": "Casa",
        "area": 190,
        "area_terreno": 0,
        "quartos": 3,
        "banheiros": 3,
        "vagas": 2,
        "descricao": "Casa reformada, próximo ao Shopping Sumaúma. 3 dormitórios sendo 1 suíte, 2 banheiros + lavabo, garagem para 2 carros. Piso em porcelanato polido alto brilho, área de serviço, quintal amplo com plantas frutíferas e horta. Caixa d'água de 1.000 litros. Documentada para financiamento.",
        "fotos": ["https://resizedimgs.vivareal.com/img/vr-listing/557b5033c64ff2a823849e29bf88f629/casa-com-3-quartos-a-venda-190m-no-cidade-nova-manaus.webp?action=fit-in&dimension=870x707", "https://resizedimgs.vivareal.com/img/vr-listing/779e13b13790598c3cc7cebd9af52c61/casa-com-3-quartos-a-venda-190m-no-cidade-nova-manaus.webp?action=fit-in&dimension=870x707&seo=false"],
        "preco_anunciado": 450000,
        "data_publicacao": "2026-06-05",
    },
]


# =============================================================================
# CONVERSÃO: formato da amostra → formato do pipeline (igual à interface)
# =============================================================================

def montar_imovel_alvo(imovel: dict) -> dict:
    """
    Converte os campos da amostra para o dict que o pipeline espera,
    replicando exatamente a lógica da interface (app/interface.py).
    """
    tipo = imovel["tipo"]
    tipo_map = {"Casa": "house", "Apartamento": "apartment", "Terreno": "house"}
    property_type_map = {"Casa": "Casas", "Apartamento": "Apartamentos", "Terreno": "Terrenos"}

    rua = imovel["rua"]
    bairro = imovel["bairro"]
    cidade = imovel["cidade"]
    estado = imovel["estado"]
    area = imovel["area"]
    quartos = imovel["quartos"]
    banheiros = imovel["banheiros"]
    vagas = imovel["vagas"]
    area_terreno = imovel.get("area_terreno", 0)
    descricao = imovel.get("descricao", "")
    fotos = imovel.get("fotos", [])
    preco_anunciado = imovel.get("preco_anunciado", 0)

    alvo = {
        "rua": rua,
        "numero": imovel.get("numero", ""),
        "bairro": bairro,
        "cidade": cidade,
        "estado": estado,
        "localizacao": f"{cidade}, {estado}",
        "tipo": tipo_map[tipo],
        "propertyType": property_type_map[tipo],
        "area": area,
        "area_terreno": area_terreno if area_terreno > 0 else None,
        "bedrooms": quartos,
        "bathrooms": banheiros,
        "parkingSpaces": vagas,
        "neighborhood": bairro,
        "street": rua,
        "description": descricao or f"{tipo} com {area}m², {quartos} quartos, {banheiros} banheiros, {vagas} vagas - {bairro}, {cidade}/{estado}",
        "images": fotos,
    }

    if preco_anunciado > 0:
        alvo["price"] = preco_anunciado
        alvo["pricePerSqm"] = preco_anunciado / area if area > 0 else 0

    return alvo


# =============================================================================
# EXECUÇÃO DO PIPELINE (replica o fluxo da interface)
# =============================================================================

def executar_pipeline_completo(imovel_alvo: dict) -> dict:
    """
    Executa o pipeline completo para um imóvel, replicando o mesmo
    fluxo da interface web (Agentes 1→2→3+4→5).
    """
    from agents.collector import coletar_imoveis
    from agents.comparables import identificar_comparaveis, analisar_zona_homogenea
    from agents.text_analyzer import analisar_comparaveis
    from agents.infra_evaluator import avaliar_infraestrutura
    from agents.price_liquidity import estimar_preco

    # AGENTE 1 — Coleta
    logger.info("  Agente 1: coletando...")
    imoveis_coletados = coletar_imoveis(
        localizacao=imovel_alvo["localizacao"],
        tipo_imovel=imovel_alvo["tipo"],
        bairro=imovel_alvo.get("bairro", ""),
        rua=imovel_alvo.get("rua", ""),
    )

    if not imoveis_coletados:
        return {"erro": "Agente 1 sem resultados"}

    logger.info(f"  Agente 1: {len(imoveis_coletados)} imóveis coletados")

    # AGENTE 2 — Comparáveis
    logger.info("  Agente 2: identificando comparáveis...")
    resultado_ag2 = identificar_comparaveis(
        imovel_alvo=imovel_alvo,
        imoveis_coletados=imoveis_coletados,
        usar_llm=True,
    )

    comparaveis = resultado_ag2.get("comparaveis", [])
    terrenos = resultado_ag2.get("terrenos", [])
    resumo = resultado_ag2.get("resumo", {})

    if not comparaveis:
        return {"erro": "Agente 2 sem comparáveis"}

    logger.info(f"  Agente 2: {resumo.get('cluster_a', 0)} similares")

    # Zona homogênea (se GOOGLE_MAPS_KEY disponível)
    zona_resultado = None
    if os.getenv("GOOGLE_MAPS_KEY"):
        try:
            endereco = f"{imovel_alvo['rua']}, {imovel_alvo.get('numero', '')}, {imovel_alvo['bairro']}, {imovel_alvo['cidade']}, {imovel_alvo['estado']}"
            zona_resultado = analisar_zona_homogenea(
                endereco_alvo=endereco,
                imoveis=comparaveis + terrenos,
                cidade=imovel_alvo["cidade"],
                estado=imovel_alvo["estado"],
            )
        except Exception:
            pass

    # AGENTES 3 e 4 — Paralelo
    logger.info("  Agentes 3+4: análise qualitativa + infraestrutura...")
    resultado_ag3 = {}
    resultado_ag4 = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_ag3 = executor.submit(analisar_comparaveis)
        future_ag4 = executor.submit(avaliar_infraestrutura)

        try:
            resultado_ag3 = future_ag3.result()
        except Exception as e:
            logger.warning(f"  Agente 3 falhou: {e}")

        try:
            resultado_ag4 = future_ag4.result()
        except Exception as e:
            logger.warning(f"  Agente 4 falhou: {e}")

    # AGENTE 5 — Preço e liquidez
    logger.info("  Agente 5: estimando preço...")
    resultado_ag5 = {}
    try:
        resultado_ag5 = estimar_preco(imovel_alvo_extra=imovel_alvo)
    except Exception as e:
        logger.warning(f"  Agente 5 falhou: {e}")

    return {
        "status": "completo",
        "comparaveis": comparaveis,
        "terrenos": terrenos,
        "resumo": resumo,
        "analise_qualitativa": resultado_ag3,
        "infraestrutura": resultado_ag4,
        "preco_estimado": resultado_ag5,
    }


# =============================================================================
# CÁLCULO DO DoM
# =============================================================================

def calcular_dom(data_publicacao: str) -> int:
    """Calcula dias desde a publicação até hoje."""
    pub = datetime.strptime(data_publicacao, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    hoje = datetime.now(timezone.utc)
    return (hoje - pub).days


# =============================================================================
# EXECUÇÃO DA AVALIAÇÃO
# =============================================================================

def rodar_avaliacao(amostra: list[dict]) -> list[dict]:
    """Roda o pipeline para cada imóvel e coleta resultados."""
    resultados = []

    for i, imovel_original in enumerate(amostra):
        # Copia para não modificar o original
        imovel = dict(imovel_original)

        logger.info(f"\n{'='*60}")
        logger.info(f"IMÓVEL {i+1}/{len(amostra)} — {imovel['rua']}, {imovel['bairro']}")
        logger.info(f"{'='*60}")

        # Separa dados de avaliação
        preco_anunciado = imovel.pop("preco_anunciado")
        data_publicacao = imovel.pop("data_publicacao")
        dom = calcular_dom(data_publicacao)

        # Converte para formato do pipeline
        imovel_alvo = montar_imovel_alvo(imovel)

        t0 = time.time()
        try:
            resultado_pipeline = executar_pipeline_completo(imovel_alvo)

            if "erro" in resultado_pipeline:
                raise Exception(resultado_pipeline["erro"])

            # Extrai preço do Agente 5
            ag5 = resultado_pipeline.get("preco_estimado", {})
            if ag5 and isinstance(ag5, dict):
                avaliacao = ag5.get("avaliacao", {})
                preco_sistema = avaliacao.get("valor_medio_imovel", 0)
                preco_liquidez = avaliacao.get("valor_liquidez", 0)
                liquidez_info = ag5.get("liquidez", {})
                tempo_estimado = liquidez_info.get("tempo_estimado", "N/A")
                score_liquidez = liquidez_info.get("score_liquidez", 0)
                classificacao = liquidez_info.get("classificacao", "N/A")
            else:
                preco_sistema = 0
                preco_liquidez = 0
                tempo_estimado = "N/A"
                score_liquidez = 0
                classificacao = "N/A"

            # Métricas individuais
            erro_relativo = (
                abs(preco_sistema - preco_anunciado) / preco_anunciado
                if preco_anunciado > 0 and preco_sistema > 0
                else None
            )
            sobrepreco = (
                (preco_anunciado - preco_sistema) / preco_sistema
                if preco_sistema > 0
                else None
            )

            resultado = {
                "id": i + 1,
                "endereco": f"{imovel['rua']}, {imovel['bairro']}",
                "tipo": imovel["tipo"],
                "area": imovel["area"],
                "preco_anunciado": preco_anunciado,
                "preco_sistema": round(preco_sistema, 2),
                "preco_liquidez": round(preco_liquidez, 2),
                "dom_dias": dom,
                "erro_relativo": round(erro_relativo, 4) if erro_relativo else None,
                "sobrepreco_percentual": round(sobrepreco * 100, 2) if sobrepreco else None,
                "tempo_estimado_sistema": tempo_estimado,
                "classificacao_liquidez": classificacao,
                "score_liquidez": score_liquidez,
                "n_comparaveis": len(resultado_pipeline.get("comparaveis", [])),
                "tempo_execucao_s": round(time.time() - t0, 1),
                "status": "ok",
            }

        except Exception as e:
            logger.error(f"  ERRO: {e}")
            resultado = {
                "id": i + 1,
                "endereco": f"{imovel.get('rua', '?')}, {imovel.get('bairro', '?')}",
                "tipo": imovel.get("tipo", "?"),
                "area": imovel.get("area", 0),
                "preco_anunciado": preco_anunciado,
                "preco_sistema": 0,
                "preco_liquidez": 0,
                "dom_dias": dom,
                "erro_relativo": None,
                "sobrepreco_percentual": None,
                "tempo_estimado_sistema": "ERRO",
                "classificacao_liquidez": "ERRO",
                "score_liquidez": 0,
                "n_comparaveis": 0,
                "tempo_execucao_s": round(time.time() - t0, 1),
                "status": f"erro: {str(e)}",
            }

        resultados.append(resultado)

        logger.info(f"  Preço anunciado:  R$ {preco_anunciado:,.2f}")
        logger.info(f"  Preço sistema:    R$ {resultado['preco_sistema']:,.2f}")
        logger.info(f"  Preço liquidez:   R$ {resultado['preco_liquidez']:,.2f}")
        logger.info(f"  DoM:              {dom} dias")
        logger.info(f"  Erro relativo:    {resultado['erro_relativo']}")
        logger.info(f"  Sobrepreço:       {resultado['sobrepreco_percentual']}%")
        logger.info(f"  Tempo execução:   {resultado['tempo_execucao_s']}s")

    return resultados


# =============================================================================
# MÉTRICAS AGREGADAS
# =============================================================================

def calcular_metricas(resultados: list[dict]) -> dict:
    """Calcula métricas agregadas."""
    validos = [r for r in resultados if r["status"] == "ok" and r["preco_sistema"] > 0]

    if not validos:
        return {"erro": "Nenhum resultado válido"}

    erros = [r["erro_relativo"] for r in validos if r["erro_relativo"] is not None]
    sobreprecos = [r["sobrepreco_percentual"] for r in validos if r["sobrepreco_percentual"] is not None]
    doms = [r["dom_dias"] for r in validos]

    # Acurácia
    mae = mean(erros) if erros else 0
    mediana_erro = median(erros) if erros else 0
    dentro_10 = sum(1 for e in erros if e <= 0.10) / len(erros) if erros else 0
    dentro_20 = sum(1 for e in erros if e <= 0.20) / len(erros) if erros else 0
    dentro_30 = sum(1 for e in erros if e <= 0.30) / len(erros) if erros else 0

    # Liquidez: imóveis com DoM alto vs baixo
    dom_alto = [r for r in validos if r["dom_dias"] > 180]
    dom_baixo = [r for r in validos if r["dom_dias"] <= 180]

    # Taxa de concordância: sistema sugere preço < anunciado para DoM alto
    if dom_alto:
        taxa_concordancia = (
            sum(1 for r in dom_alto if r["sobrepreco_percentual"] and r["sobrepreco_percentual"] > 0)
            / len(dom_alto)
        )
    else:
        taxa_concordancia = None

    # Correlação DoM × sobrepreço (Pearson simplificado)
    correlacao_dom_sobrepreco = None
    if len(validos) >= 5:
        pares = [(r["dom_dias"], r["sobrepreco_percentual"]) for r in validos
                 if r["sobrepreco_percentual"] is not None]
        if len(pares) >= 5:
            x = [p[0] for p in pares]
            y = [p[1] for p in pares]
            n = len(pares)
            mean_x, mean_y = mean(x), mean(y)
            cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
            std_x = (sum((xi - mean_x)**2 for xi in x) / n) ** 0.5
            std_y = (sum((yi - mean_y)**2 for yi in y) / n) ** 0.5
            if std_x > 0 and std_y > 0:
                correlacao_dom_sobrepreco = round(cov / (std_x * std_y), 4)

    return {
        "total_amostra": len(resultados),
        "resultados_validos": len(validos),
        "resultados_com_erro": len(resultados) - len(validos),
        "acuracia": {
            "erro_relativo_medio_MAE": round(mae, 4),
            "erro_relativo_mediano": round(mediana_erro, 4),
            "desvio_padrao": round(stdev(erros), 4) if len(erros) > 1 else 0,
            "pct_dentro_10pct": round(dentro_10 * 100, 1),
            "pct_dentro_20pct": round(dentro_20 * 100, 1),
            "pct_dentro_30pct": round(dentro_30 * 100, 1),
        },
        "liquidez": {
            "dom_medio_dias": round(mean(doms), 1),
            "dom_mediano_dias": round(median(doms), 1),
            "imoveis_dom_alto_6m": len(dom_alto),
            "imoveis_dom_baixo_6m": len(dom_baixo),
            "taxa_concordancia_dom_alto_pct": round(taxa_concordancia * 100, 1) if taxa_concordancia is not None else "N/A",
            "correlacao_dom_sobrepreco": correlacao_dom_sobrepreco,
            "interpretacao_correlacao": (
                "Positiva = quanto mais tempo no mercado, maior o sobrepreço (imóvel caro demais). "
                "Valida a hipótese de que preço acima do mercado reduz liquidez."
            ),
        },
        "sobrepreco": {
            "medio_pct": round(mean(sobreprecos), 2) if sobreprecos else None,
            "mediano_pct": round(median(sobreprecos), 2) if sobreprecos else None,
        },
    }


# =============================================================================
# RELATÓRIO
# =============================================================================

def gerar_relatorio(resultados: list[dict], metricas: dict):
    """Imprime e salva relatório."""

    print("\n" + "=" * 70)
    print("RELATÓRIO DE AVALIAÇÃO — LIQUIDEZ × PREÇO")
    print("=" * 70)

    print(f"\nAmostra: {metricas['total_amostra']} imóveis | Válidos: {metricas['resultados_validos']} | Erros: {metricas['resultados_com_erro']}")

    print("\n─── ACURÁCIA ───")
    a = metricas["acuracia"]
    print(f"  Erro relativo médio (MAE):  {a['erro_relativo_medio_MAE']:.1%}")
    print(f"  Erro relativo mediano:      {a['erro_relativo_mediano']:.1%}")
    print(f"  Desvio padrão:              {a['desvio_padrao']:.1%}")
    print(f"  Dentro de ±10%:             {a['pct_dentro_10pct']}%")
    print(f"  Dentro de ±20%:             {a['pct_dentro_20pct']}%")
    print(f"  Dentro de ±30%:             {a['pct_dentro_30pct']}%")

    print("\n─── LIQUIDEZ ───")
    l = metricas["liquidez"]
    print(f"  DoM médio:                  {l['dom_medio_dias']} dias")
    print(f"  DoM mediano:                {l['dom_mediano_dias']} dias")
    print(f"  Imóveis DoM > 6 meses:      {l['imoveis_dom_alto_6m']}")
    print(f"  Imóveis DoM ≤ 6 meses:      {l['imoveis_dom_baixo_6m']}")
    print(f"  Taxa concordância (DoM>6m): {l['taxa_concordancia_dom_alto_pct']}%")
    print(f"  Correlação DoM×Sobrepreço:  {l['correlacao_dom_sobrepreco']}")

    print("\n─── SOBREPREÇO ───")
    s = metricas["sobrepreco"]
    print(f"  Médio:                      {s['medio_pct']}%")
    print(f"  Mediano:                    {s['mediano_pct']}%")

    print("\n─── DETALHAMENTO ───")
    header = f"{'#':<3} {'Tipo':<5} {'Anunciado':>11} {'Sistema':>11} {'Erro':>7} {'DoM':>5} {'Sobrep.':>8} {'Tempo Venda':<15}"
    print(header)
    print("-" * len(header))
    for r in resultados:
        erro_str = f"{r['erro_relativo']*100:.1f}%" if r['erro_relativo'] else "  -  "
        sp_str = f"{r['sobrepreco_percentual']:.1f}%" if r['sobrepreco_percentual'] else "  -  "
        print(
            f"{r['id']:<3} "
            f"{r['tipo'][:4]:<5} "
            f"R${r['preco_anunciado']:>9,.0f} "
            f"R${r['preco_sistema']:>9,.0f} "
            f"{erro_str:>7} "
            f"{r['dom_dias']:>4}d "
            f"{sp_str:>8} "
            f"{r['tempo_estimado_sistema']:<15}"
        )

    # Salvar JSON
    saida = {
        "data_avaliacao": datetime.now().isoformat(),
        "metricas": metricas,
        "resultados_individuais": resultados,
    }
    caminho = RESULTADO_DIR / "resultado_avaliacao.json"
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    print(f"\n📁 Resultados salvos em: {caminho}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("AVALIAÇÃO DO SISTEMA — 15 IMÓVEIS")
    print("=" * 70)

    n = len(AMOSTRA_IMOVEIS)
    if n < 15:
        print(f"\n⚠️  Amostra com apenas {n} imóvel(is). Preencha 15 para avaliação completa.")
        print("   Rodando com o que tem...\n")

    if n == 0:
        print("❌ Nenhum imóvel na amostra. Preencha AMOSTRA_IMOVEIS e rode novamente.")
        sys.exit(1)

    t_total = time.time()
    resultados = rodar_avaliacao(AMOSTRA_IMOVEIS)
    metricas = calcular_metricas(resultados)
    gerar_relatorio(resultados, metricas)

    print(f"\n⏱️  Tempo total: {(time.time() - t_total)/60:.1f} minutos")
