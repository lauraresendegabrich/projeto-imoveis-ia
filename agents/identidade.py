"""
Identidade de anuncios ("e o mesmo imovel?") e deduplicacao de comparaveis
=============================================================================

Usado pelo Agente 1 (descarta repeticoes entre/dentro dos portais antes do
Agente 2) e pelo Agente 2 (regras comuns do teste "comparavel = imovel alvo").

Origem: proposta calibrada em set/2026 com todos os anuncios de venda de casa e
apartamento de Belo Horizonte (proposta_deduplicacao/, fora deste repositorio).
Resultado na calibracao (codigo do anunciante escondido do teste):

                     duplicatas encontradas   imoveis diferentes fundidos
    apartamento              89,1%                      6,0%
    casa                     60,7%                      9,8%

O que os dados mostraram:
  - PRECO IDENTICO (<=0,5%) e o sinal mais forte: o mesmo anuncio em outro portal
    tem o mesmo preco em >95% dos casos; unidades diferentes da mesma rua, ~15-20%.
  - Coordenada nao serve para dizer que dois ANUNCIOS sao o mesmo imovel: o mesmo
    imovel aparece a ~110 m entre portais, e anuncios diferentes da mesma
    imobiliaria repetem a mesma coordenada.
  - Casa exige MAIS rigor que apartamento (casas vizinhas da mesma construtora
    sao quase identicas, e casa nao tem andar/vaga/suite para desempatar).
  - Mesmo codigo do imovel + mesmo anunciante prova que e o mesmo imovel; mesmo
    portal + mesmo anunciante + codigos diferentes prova o contrario.

Diferencas em relacao a proposta original:
  - Casa em condominio so e identificavel no VivaReal (CONDOMINIUM) e no Chaves
    na Mao; ImovelWeb/Lugar Certo dizem so "Casa". A proposta punha casa em
    condominio no grupo apartamento, e a mesma casa em dois portais caia em
    "tipos diferentes" (nunca fundida). Aqui o grupo continua "casa"; a regra de
    apartamento so e usada quando OS DOIS anuncios sao casa em condominio.
  - Blocos de preco vizinhos tambem sao comparados (R$ 450.400 e R$ 450.600 caiam
    em blocos de milhar diferentes e nunca eram comparados).
  - deduplicar devolve tambem os anuncios descartados completos (auditoria).
  - Portal normalizado ("Lugar Certo" do Apify = "lugarcerto" do Athena).
  - Casa com mesma rua + mesmo numero + preco identico + area <=2% e o mesmo
    imovel sem exigir descricao parecida (cada portal reescreve o texto). Nao vale
    quando o anuncio pode ser de condominio de casas (numero compartilhado).
    Na calibracao de BH nao mudou as taxas (quase nenhum par tinha numero nos dois
    lados); no Santa Monica juntou 16 anuncios a mais.

  - Mesmo imovel com areas mais de 5% diferentes entre portais: casa/apto usa a
    menor area do grupo e guarda as areas em `areas_entre_portais` (alerta).
  - Na prova direta (mesmo codigo + anunciante), o nome do anunciante e comparado
    sem palavras genericas ("Habicarmo" = "Habicarmo Imoveis"): em Sao Jose do Rio
    Preto (out/2026) a mesma casa e o mesmo terreno escapavam por isso.

Limitacoes: calibrado so em BH/venda; poucos pares de casa (61); terreno e
comercial nao tem regra calibrada: so sao fundidos pela prova direta (mesmo
codigo + mesmo anunciante).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# ---------------------------------------------------------------- parametros
# Calibrados em BH (set/2026).
PRECO_IDENTICO = 0.005                      # diferenca maxima de preco para "mesmo anuncio"
VETO_AREA = {"apto": 0.03, "casa": 0.10}    # acima disso, com certeza sao imoveis diferentes
APTO_AREA = 0.02                            # apto: area ate 2% OU descricao >= APTO_DESC
APTO_DESC = 0.60
CASA_AREA = 0.01                            # casa: area ate 1% E descricao >= CASA_DESC
CASA_DESC = 0.75
# Casa com mesma rua E mesmo numero dispensa a descricao (cada portal reescreve o
# texto; casas vizinhas iguais de construtora tem numeros diferentes).
CASA_AREA_COM_NUMERO = 0.02
# Mesmo imovel com areas diferentes entre portais (ex.: um portal mostra a area do
# terreno no lugar da construida): acima desta diferenca, casa/apto usa a MENOR area
# do grupo e o anuncio e marcado para o alerta "area diferente entre portais".
AREA_DIVERGENTE_ENTRE_PORTAIS = 0.05

SUFIXOS_ANUNCIANTE = {"ltda", "me", "eireli", "sa", "epp", "s", "a"}
# Palavras genericas que cada portal poe ou tira do nome da mesma imobiliaria
# ("Habicarmo" x "Habicarmo Imoveis", "Sumares Imoveis" x "Sumares Negocios
# Imobiliarios"). Ignoradas so na prova direta (mesmo codigo + mesmo anunciante).
PALAVRAS_GENERICAS_ANUNCIANTE = {
    "imoveis", "imovel", "imobiliaria", "imobiliarias", "imobiliario", "imobiliarios",
    "negocios", "corretor", "corretora", "corretores", "consultoria", "assessoria",
    "empreendimentos", "creci", "de", "do", "da", "dos", "das", "e",
}
PREFIXOS_RUA = {"rua", "r", "avenida", "av", "alameda", "al", "travessa", "tv",
                "praca", "estrada", "rodovia", "largo"}

# Campos copiados para cada duplicata absorvida, para o Agente 2 testar o alvo
# tambem contra os anuncios descartados do grupo (a regra nao e transitiva).
CAMPOS_IDENTIDADE = (
    "portal", "source", "listing_id", "url", "tipo", "propertyType", "property_sub_type",
    "price", "preco", "area", "area_construida", "bedrooms", "quartos",
    "parkingSpaces", "vagas", "suites", "andar", "street", "rua", "numero",
    "neighborhood", "bairro", "lat", "lon", "description", "descricao", "titulo", "title",
    # Para a checagem do proprio anuncio contra os repetidos: banheiros, fotos.
    "bathrooms", "banheiros", "images", "fotos_urls",
)


# ---------------------------------------------------------------- utilitarios
def _vazio(x) -> bool:
    return x is None or x == "" or (isinstance(x, float) and x != x)


def _campo(d: dict, *nomes):
    for n in nomes:
        v = d.get(n)
        if not _vazio(v):
            return v
    return None


def _num(v) -> float | None:
    if _vazio(v) or isinstance(v, bool):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _norm(t) -> str:
    t = "" if _vazio(t) else str(t)
    t = unicodedata.normalize("NFD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def portal(d: dict) -> str:
    """Chave do portal: coluna portal (Athena) ou source (Apify) sem espacos."""
    p = _norm(_campo(d, "portal", "source", "source_site")).replace(" ", "")
    return "vivareal" if p == "athenas3" else p


def _anunciante(d: dict) -> str:
    nome = _campo(d, "anunciante_nome", "advertiser", "publisher")
    return " ".join(p for p in _norm(nome).split() if p not in SUFIXOS_ANUNCIANTE)


def _juntar_letras_soltas(palavras: list[str]) -> list[str]:
    """
    Siglas escritas com letras soltas viram uma palavra: "b e g" (B E G), "b g" (B&G,
    o "&" ja virou espaco) e "bg" ficam todos "bg". O "e" entre letras e conjuncao.
    """
    saida, sequencia = [], []

    def fechar():
        if len(sequencia) >= 2:
            letras = [l for i, l in enumerate(sequencia) if not (l == "e" and 0 < i < len(sequencia) - 1)]
            saida.append("".join(letras))
        else:
            saida.extend(sequencia)
        sequencia.clear()

    for p in palavras:
        if len(p) == 1 and p.isalpha():
            sequencia.append(p)
        else:
            fechar()
            saida.append(p)
    fechar()
    return saida


def _anunciante_base(d: dict) -> str:
    """
    Nome do anunciante sem palavras genericas, numeros (CRECI) e letras soltas; siglas
    com letras separadas ("B E G", "B&G") viram uma palavra ("bg").
    """
    return " ".join(
        p for p in _juntar_letras_soltas(_anunciante(d).split())
        if p not in PALAVRAS_GENERICAS_ANUNCIANTE and len(p) > 1 and not any(ch.isdigit() for ch in p)
    )


def _codigo(d: dict) -> str | None:
    c = _campo(d, "codigo_imovel_anunciante")
    c = "" if c is None else re.sub(r"\s+", "", str(c)).upper()
    return c if len(c) >= 2 else None


# Codigos gerados pelo portal (nao pela imobiliaria): no ImovelWeb, "MI-<13 digitos>-..."
# (as vezes com prefixo: "TIA-A6PG-MI-..."), ~22 mil anuncios de poucos anunciantes
# (Rankim, Sucursal). Cada anuncio do mesmo imovel ganha um codigo novo, entao codigos
# diferentes nao provam unidades diferentes. Ja "IMCX<13 digitos>SP" se repete igual
# em VivaReal, Chaves na Mao e ImovelWeb: e do sistema da imobiliaria e continua valendo.
_CODIGO_DO_PORTAL = re.compile(r"(?:^|-)MI-\d{13}-")


def codigo_do_portal(codigo: str | None) -> bool:
    return bool(codigo and _CODIGO_DO_PORTAL.search(codigo))


def _codigos_de_unidades_diferentes(a: dict, b: dict) -> bool:
    """Mesmo portal + mesmo anunciante + codigos da imobiliaria diferentes = outra unidade."""
    ca, cb = _codigo(a), _codigo(b)
    return bool(ca and cb and ca != cb and not codigo_do_portal(ca) and not codigo_do_portal(cb)
                and _anunciante(a) and _anunciante(a) == _anunciante(b) and portal(a) == portal(b))


def grupo(d: dict) -> str | None:
    """apto, casa ou None (terreno/comercial: sem calibracao, nunca fundidos)."""
    tipo = _norm(_campo(d, "tipo", "propertyType"))
    if any(x in tipo for x in ("terreno", "lote", "land", "allotment")):
        return None
    if any(x in tipo for x in ("apartamento", "apartment", "cobertura", "flat", "kitnet", "loft", "studio")):
        return "apto"
    if any(x in tipo for x in ("casa", "house", "sobrado", "village")):
        return "casa"
    return None


def _em_condominio(d: dict) -> bool:
    return "condomin" in _norm(_campo(d, "property_sub_type"))


def _pode_ser_condominio(d: dict) -> bool:
    """
    Casas de um condominio (ou varias casas no mesmo lote) dividem o numero da rua.
    ImovelWeb/Lugar Certo nao marcam o subtipo, entao procura tambem no texto.
    """
    if _em_condominio(d):
        return True
    original = " ".join(str(_campo(d, c) or "") for c in ("rua", "street", "titulo", "title", "descricao", "description"))
    texto = _norm(original)
    # Negacoes e o aviso padrao dos portais nao indicam condominio (21/10/2026: "sem
    # condominio" e "valores de condominio e IPTU podem sofrer alteracoes" desligavam
    # a regra rua + numero).
    texto = re.sub(
        r"\b(?:sem|nao (?:tem|paga|possui|ha|cobra)|isent[oa] de|livre de|fora de|nao e(?: de| em)?)"
        r"\s+(?:taxa de\s+|um\s+)?condomini\w*"
        r"|\bcondomini\w*\s+(?:isento|zero|gratis)\b"
        r"|\bvalores? de condomini\w* e iptu",
        " ", texto,
    )
    if re.search(r"\bcondomini|\bunidade\b|\bbloco\b|\blote \d", texto):
        return True
    # "casa N" so quando for a unidade: "casa 3 do condominio", "casa 03", "casa n 3",
    # "casa A". Nao: "Casa 3 dormitorios", "casa 601361091" (codigo do anuncio).
    if re.search(r"\bcasa (?:n[o.]? ?)?(?:0\d|\d{1,3} (?:do|no|da|na) (?:condominio|conjunto|residencial|vila))\b"
                 r"|\bcasa n[o.]? ?\d{1,3}\b", texto):
        return True
    # Letra de unidade so seguida de pontuacao, fim do texto ou "do/no/da/na": "Casa A,"
    # e "Casa B do condominio" sim; "Casa E Terreno a Venda" (titulo) e "Casa A Venda" nao.
    sem_acento = unicodedata.normalize("NFKD", original).encode("ascii", "ignore").decode()
    return bool(re.search(r"\b[Cc]asa ([A-H])(?=\s*(?:[,.;:)\-–]|$)|\s+(?:do|no|da|na)\b)", sem_acento))


def regra_do_par(a: dict, b: dict) -> tuple[str | None, str]:
    """
    Qual regra usar para o par: ("apto" | "casa", "") ou (None, motivo do veto).
    Casa em condominio dos DOIS lados usa a regra de apartamento (unidades
    padronizadas); se so um lado informa condominio, vale a regra de casa (mais
    rigorosa), porque ImovelWeb/Lugar Certo nao distinguem casa em condominio.
    """
    g_a, g_b = grupo(a), grupo(b)
    if g_a is None or g_b is None:
        return None, "tipo_sem_regra_calibrada"
    if g_a != g_b:
        return None, "veto_tipo_diferente"
    if g_a == "casa" and _em_condominio(a) and _em_condominio(b):
        return "apto", ""
    return g_a, ""


def similaridade_descricao(a, b) -> float:
    """Mesma formula de _similaridade_descricao do Agente 2: 0,6*SequenceMatcher + 0,4*Jaccard."""
    a, b = _norm(a), _norm(b)
    if len(a) < 60 or len(b) < 60:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(re.findall(r"\w+", a)), set(re.findall(r"\w+", b))
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return round(0.6 * ratio + 0.4 * jac, 3)


def rua(d: dict) -> str | None:
    """Nome da rua sem prefixo e sem numero ('Rua Espirito Santo, 1059' -> 'espirito santo')."""
    valor = _campo(d, "rua", "street")
    if valor is None:
        return None
    nome = re.split(r",\s*(?:n[º°o.]*\s*)?\d", str(valor), flags=re.I)[0]
    partes = _norm(nome).split()
    while partes and partes[0] in PREFIXOS_RUA:
        partes.pop(0)
    return " ".join(partes) or None


def numero(d: dict) -> str | None:
    """Numero do endereco: campo proprio ou 'Rua X, 123' / 'Rua X, n. 123' na rua."""
    for chave in ("numero", "streetNumber", "street_number", "addressNumber"):
        v = d.get(chave)
        if not _vazio(v) and re.fullmatch(r"\d{1,6}", str(v).strip()):
            return str(v).strip().lstrip("0") or None
    m = re.search(r",\s*(?:n[º°o.]*\s*)?(\d{1,6})\b", str(_campo(d, "rua", "street") or ""), re.I)
    if m:
        return m.group(1).lstrip("0") or None
    return _numero_no_link(d)


def _numero_no_link(d: dict) -> str | None:
    """
    ImovelWeb sem numero na rua: alguns anunciantes poem as iniciais do bairro e da rua
    seguidas do numero no comeco do link ("jcjpv-888-casa-..." = Jardim Consorcio, Joao
    Peixoto Viegas, 888). So vale quando as letras terminam com as iniciais da rua do
    proprio anuncio (assim "3-quartos" ou "140-m2" nunca viram numero).
    """
    url = str(_campo(d, "url") or "")
    if "imovelweb" not in url.lower():
        return None
    m = re.match(r"([a-z]{2,12})-(\d{1,5})-", url.rstrip("/").rsplit("/", 1)[-1].lower())
    nome_rua = rua(d)
    if not m or not nome_rua:
        return None
    iniciais = "".join(p[0] for p in nome_rua.split())
    if len(iniciais) >= 2 and m.group(1).endswith(iniciais):
        return m.group(2).lstrip("0") or None
    return None


def _bairros(d: dict) -> set[str]:
    """Nomes possiveis do bairro: 'Lagoinha Leblon (Venda Nova)' -> {'lagoinha leblon', 'venda nova'}."""
    b = _campo(d, "bairro", "neighborhood")
    if b is None:
        return set()
    nomes = {_norm(re.sub(r"\(.*?\)", "", str(b)))} | {_norm(x) for x in re.findall(r"\((.*?)\)", str(b))}
    return {n for n in nomes if n}


def _nomes_parecidos(x: str, y: str) -> bool:
    # Grafias diferentes entre portais: Jacqueline/Jaqueline, Santa Teresa/Santa Tereza
    return x == y or x in y or y in x or SequenceMatcher(None, x, y).ratio() >= 0.85


def local_compativel(a: dict, b: dict) -> bool:
    """
    False so quando ha evidencia de lugares diferentes: os dois informam bairro, os
    bairros nao batem (nem com tolerancia de grafia) e a rua tambem nao bate.
    Bairro ausente num dos lados nao veta.
    """
    ra, rb = rua(a), rua(b)
    if ra and rb and _nomes_parecidos(ra, rb):
        return True
    ba, bb = _bairros(a), _bairros(b)
    if not ba or not bb:
        return True
    return any(_nomes_parecidos(x, y) for x in ba for y in bb)


def dif_relativa(a, b) -> float | None:
    a, b = _num(a), _num(b)
    if not a or not b:
        return None
    return abs(a - b) / max(a, b)


def _diferentes(a, b) -> bool:
    """True so quando os dois informam e os valores sao diferentes."""
    a, b = _num(a), _num(b)
    return a is not None and b is not None and int(a) != int(b)


def area(d: dict):
    return _campo(d, "area_construida", "area", "usableArea")


def preco(d: dict):
    return _campo(d, "preco", "price")


def motivo_veto(a: dict, b: dict, g: str, ignorar: tuple = ()) -> str | None:
    """
    Primeiro veto encontrado (com certeza imoveis diferentes) ou None.
    `ignorar`: campos que um dos lados nao informa de verdade (ex.: vagas=0 padrao
    do formulario do alvo).
    """
    area_dif = dif_relativa(area(a), area(b))
    if "area" not in ignorar and area_dif is not None and area_dif > VETO_AREA[g]:
        return "veto_area"
    if _diferentes(_campo(a, "quartos", "bedrooms"), _campo(b, "quartos", "bedrooms")):
        return "veto_quartos"
    if g == "apto":
        for nomes in (("vagas", "parkingSpaces"), ("suites",), ("andar", "floor")):
            if nomes[0] in ignorar:
                continue
            if _diferentes(_campo(a, *nomes), _campo(b, *nomes)):
                return f"veto_{nomes[0]}"
    return None


# ---------------------------------------------------------------- regra entre anuncios
def mesmo_imovel(a: dict, b: dict) -> tuple[bool, str]:
    """Decide se dois ANUNCIOS sao o mesmo imovel. Retorna (sim/nao, motivo)."""
    # 1) Prova direta: mesmo codigo do imovel + mesmo anunciante
    # (o nome do anunciante e comparado sem palavras genericas: cada portal escreve
    # a mesma imobiliaria de um jeito). Vale tambem para terreno.
    cod_a, cod_b = _codigo(a), _codigo(b)
    base_a, base_b = _anunciante_base(a), _anunciante_base(b)
    if cod_a and cod_a == cod_b and base_a and base_a == base_b:
        return True, "mesmo_codigo_e_anunciante"
    # O proprio anunciante diz que sao imoveis diferentes: mesmo portal, mesmo
    # anunciante e codigos diferentes = outras unidades (era a maior fonte de fusao
    # indevida em BH). Codigos gerados pelo portal ("MI-...") nao contam.
    if _codigos_de_unidades_diferentes(a, b):
        return False, "veto_codigos_diferentes"

    g, motivo = regra_do_par(a, b)
    if g is None:
        return False, motivo
    # Sem isso, apartamentos iguais em bairros diferentes (mesma planta e preco)
    # seriam fundidos.
    if not local_compativel(a, b):
        return False, "veto_local"

    # Casa com a mesma rua e o mesmo numero, sem indicio de condominio (varias casas no
    # mesmo numero): a area diferente nao veta, porque um portal costuma mostrar a area
    # total no lugar da construida (Av. Joao Peixoto Viegas, 888: 135 x 203 m2). Junta
    # com preco identico; o grupo usa a menor area e ganha o alerta "area diferente
    # entre portais" (_ajustar_area_do_grupo). Decisao da usuaria, 21/10/2026.
    num = numero(a)
    mesmo_endereco_casa = bool(
        g == "casa" and num and num == numero(b) and rua(a) and rua(a) == rua(b)
        and not _pode_ser_condominio(a) and not _pode_ser_condominio(b)
    )

    # 2) Vetos: basta um para nao ser o mesmo imovel
    veto = motivo_veto(a, b, g, ignorar=("area",) if mesmo_endereco_casa else ())
    if veto:
        return False, veto

    # 3) Nucleo: preco identico
    preco_dif = dif_relativa(preco(a), preco(b))
    if preco_dif is None or preco_dif > PRECO_IDENTICO:
        return False, "preco_diferente"

    area_dif = dif_relativa(area(a), area(b))
    desc = similaridade_descricao(_campo(a, "descricao", "description"), _campo(b, "descricao", "description"))
    area_ok = area_dif is not None
    if g == "apto":
        if (area_ok and area_dif <= APTO_AREA) or desc >= APTO_DESC:
            return True, f"apto_preco_identico(area_dif={_fmt(area_dif)}, desc={desc})"
    else:
        if area_ok and area_dif <= CASA_AREA and desc >= CASA_DESC:
            return True, f"casa_preco_area_descricao(area_dif={_fmt(area_dif)}, desc={desc})"
        if mesmo_endereco_casa and area_ok and area_dif <= CASA_AREA_COM_NUMERO:
            return True, f"casa_preco_area_rua_numero(area_dif={_fmt(area_dif)}, numero={num})"
        if mesmo_endereco_casa and area_ok:
            return True, f"casa_preco_rua_numero_area_diferente(area_dif={_fmt(area_dif)}, numero={num})"
    return False, f"sem_prova(area_dif={_fmt(area_dif)}, desc={desc})"


def _fmt(v: float | None) -> str:
    return "?" if v is None else f"{v:.3f}"


# ---------------------------------------------------------------- deduplicacao
def _completude(d: dict) -> int:
    return sum(1 for v in d.values() if not _vazio(v))


def _resumo(d: dict) -> dict:
    return {
        "portal": portal(d) or None,
        "source": _campo(d, "source"),
        "listing_id": _campo(d, "listing_id", "id"),
        "url": _campo(d, "url"),
    }


def _ajustar_area_do_grupo(rep: dict, membros: list[dict]) -> None:
    """
    Compara a area do representante com a dos anuncios absorvidos. Com diferenca
    acima de AREA_DIVERGENTE_ENTRE_PORTAIS, guarda as areas de cada portal em
    `areas_entre_portais` e, para casa/apto, usa a menor (o erro mais comum e um
    portal mostrar a area do terreno, maior que a construida). Terreno mantem a
    area (a menor daria um R$/m2 maior, nao conservador); so fica marcado.
    """
    areas = []
    for d in [rep] + membros:
        a = _num(area(d))
        if a and a > 0:
            areas.append({"portal": _campo(d, "source") or portal(d) or None, "area": a, "url": _campo(d, "url")})
    if len(areas) < 2:
        return
    menor, maior = min(x["area"] for x in areas), max(x["area"] for x in areas)
    if (maior - menor) / maior <= AREA_DIVERGENTE_ENTRE_PORTAIS:
        return
    rep["areas_entre_portais"] = areas
    area_atual = _num(area(rep))
    if grupo(rep) is None or area_atual == menor:
        return
    rep["area_original"] = area_atual
    rep["area"] = menor
    for campo in ("area_construida", "usableArea"):
        if not _vazio(rep.get(campo)):
            rep[campo] = menor
    p = _num(preco(rep))
    if p and not _vazio(rep.get("pricePerSqm")):
        rep["pricePerSqm"] = round(p / menor, 2)


def deduplicar(anuncios: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Agrupa anuncios que sao o mesmo imovel e devolve (unicos, descartados).

    - unicos: um anuncio por imovel, o mais completo (mais campos preenchidos).
      Recebe `duplicatas` (portal, listing_id, url, motivo, preco, area e os campos
      de identidade de cada absorvido) e `fontes_origem` (portais onde aparece).
    - descartados: os anuncios absorvidos, COMPLETOS, com `duplicata_de` (quem
      ficou no lugar) e `motivo_duplicata`, para conferencia posterior.

    Sem fusao em cadeia: um anuncio so entra num grupo se for o mesmo imovel que o
    REPRESENTANTE do grupo (se A=B e B=C por criterios diferentes, C nao e
    arrastado para o grupo de A). Tambem nao entra se o grupo ja tem um anuncio do
    mesmo portal e anunciante com outro codigo (sao unidades diferentes).

    Para nao comparar todos com todos, compara dentro de blocos com o mesmo numero
    de quartos e preco no mesmo milhar ou nos milhares vizinhos (a regra exige
    preco identico), mais um bloco por codigo+anunciante (prova direta).
    """
    # Codigo so vale se for unico dentro do mesmo portal + anunciante: alguns
    # anunciantes poem o mesmo texto em todos os anuncios ("OBVI", nome da imobiliaria).
    contagem: dict[tuple, int] = {}
    for d in anuncios:
        k = (portal(d), _anunciante(d), _codigo(d))
        contagem[k] = contagem.get(k, 0) + 1
    limpos = []
    for d in anuncios:
        if _codigo(d) and contagem[(portal(d), _anunciante(d), _codigo(d))] > 1:
            d = {**d, "codigo_imovel_anunciante": None}
        limpos.append(d)
    original, anuncios = anuncios, limpos

    def _bloco_preco(d, deslocamento=0):
        p = _num(preco(d))
        q = _num(_campo(d, "quartos", "bedrooms"))
        milhar = int(round(p / 1000)) + deslocamento if p else None
        return ("preco", milhar, int(q) if q is not None else None)

    def _bloco_codigo(d):
        if _codigo(d) and _anunciante_base(d):
            return [("codigo", _codigo(d), _anunciante_base(d))]
        return []

    def blocos_registro(d):
        return [_bloco_preco(d)] + _bloco_codigo(d)

    def blocos_busca(d):
        vizinhos = [_bloco_preco(d, -1), _bloco_preco(d, 1)] if _num(preco(d)) else []
        return [_bloco_preco(d)] + vizinhos + _bloco_codigo(d)

    def _unidades_diferentes(x, y):
        # Regra 2 aplicada DENTRO do grupo: o representante pode ser de outro portal
        # (sem veto com ninguem), mas dois membros do mesmo portal + anunciante com
        # codigos diferentes sao unidades diferentes (ex.: lancamento com dezenas
        # de unidades de mesmo preco/area) e nao podem ser o mesmo imovel.
        return _codigos_de_unidades_diferentes(x, y)

    ordem = sorted(range(len(anuncios)), key=lambda k: -_completude(anuncios[k]))
    representantes: dict[tuple, list[int]] = {}   # bloco -> representantes nele
    membros: dict[int, list[tuple[int, str]]] = {}

    for i in ordem:
        d = anuncios[i]
        destino, motivo = None, None
        vistos = set()
        for chave in blocos_busca(d):
            for r in representantes.get(chave, []):
                if r in vistos:
                    continue
                vistos.add(r)
                igual, motivo = mesmo_imovel(anuncios[r], d)
                if igual and not any(_unidades_diferentes(anuncios[m], d) for m, _ in membros[r]):
                    destino = r
                    break
            if destino is not None:
                break
        if destino is None:
            membros[i] = []
            for chave in blocos_registro(d):
                representantes.setdefault(chave, []).append(i)
        else:
            membros[destino].append((i, motivo))

    unicos, descartados = [], []
    for rep_idx in sorted(membros):   # preserva a ordem de entrada dos representantes
        outros = membros[rep_idx]
        rep = dict(original[rep_idx])
        if outros:
            rep["duplicatas"] = [
                {
                    **_resumo(original[k]),
                    "motivo": motivo,
                    "preco": _num(preco(original[k])),
                    "area": _num(area(original[k])),
                    "dados_identidade": {c: original[k][c] for c in CAMPOS_IDENTIDADE
                                         if not _vazio(original[k].get(c))},
                }
                for k, motivo in outros
            ]
            fontes = list(rep.get("fontes_origem") or [rep.get("source") or portal(rep)])
            for k, _ in outros:
                fonte = original[k].get("source") or portal(original[k])
                if fonte and fonte not in fontes:
                    fontes.append(fonte)
            rep["fontes_origem"] = fontes
            _ajustar_area_do_grupo(rep, [original[k] for k, _ in outros])
            for k, motivo in outros:
                descartados.append({
                    **original[k],
                    "duplicata_de": _resumo(original[rep_idx]),
                    "motivo_duplicata": motivo,
                })
        unicos.append(rep)
    return unicos, descartados
