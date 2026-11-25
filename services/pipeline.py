"""
Fluxo completo de uma avaliacao: o MESMO para a tela e para o terminal
======================================================================

A pagina "Avaliacao de imovel" (app/paginas/avaliacao.py) e o terminal (app/main.py,
app/graph.py) chamam `executar_avaliacao`. Antes cada um tinha o seu fluxo e o do
terminal ficou para tras (24/11/2026: sem localizar o alvo antes da coleta, terrenos
por outro caminho na zona, sem leilao nem verificacoes). Qualquer mudanca no fluxo
entra aqui e vale para os dois.

  localizar o alvo -> Agente 1 (coleta) -> Agente 2 (comparaveis) -> zona homogenea
  -> Agentes 3 e 4 (juntos) -> Agente 5 (preco) -> fim (leilao, verificacoes, banco)

A tela acompanha cada etapa por um `Observador` (mensagens, barra de progresso); o
terminal usa `ObservadorLog`, que so registra no log. O observador nunca muda o
calculo.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from services.leilao import avaliar_imovel_leilao, contar_status_zona, texto_aviso_raio, texto_aviso_zona

logger = logging.getLogger("pipeline")

TIPO_AGENTE = {"Casa": "house", "Apartamento": "apartment"}
TIPO_PORTAL = {"Casa": "Casas", "Apartamento": "Apartamentos"}
TIPO_FORMULARIO = {v: k for k, v in TIPO_AGENTE.items()}
MAX_FOTOS_ALVO = 8


# ─────────────────────────────────────────────────────────────────────────────
# Imovel alvo
# ─────────────────────────────────────────────────────────────────────────────

def montar_imovel_alvo(
    *, rua: str, numero: str, bairro: str, cidade: str, estado: str, tipo: str, area: float,
    quartos: int, banheiros: int, vagas: int | None = None, area_terreno: float | None = None,
    descricao: str = "", fotos: list[str] | tuple = (), link_anuncio: str = "", em_condominio: bool = False,
    preco: float = 0.0,
) -> dict:
    """
    O dict que os agentes recebem, a partir dos campos do formulario (`tipo` = "Casa" ou
    "Apartamento"; areas e preco ja lidos como numero).
    """
    link_anuncio = (link_anuncio or "").strip()
    imovel_alvo = {
        "rua": rua,
        "numero": numero,
        "bairro": bairro,
        "cidade": cidade,
        "estado": estado,
        "localizacao": f"{cidade}, {estado}",
        "tipo": TIPO_AGENTE[tipo],
        "propertyType": TIPO_PORTAL[tipo],
        "area": area,
        "area_terreno": area_terreno if area_terreno and area_terreno > 0 else None,
        "bedrooms": quartos,
        "bathrooms": banheiros,
        "parkingSpaces": vagas,
        "neighborhood": bairro,
        "street": rua,
        "description": descricao or (
            f"{tipo} com {area}m², {quartos} quartos, {banheiros} banheiros"
            + (f", {vagas} vagas" if vagas is not None else "") + f" - {bairro}, {cidade}/{estado}"
        ),
        # Texto generico gerado acima: nao serve de prova de identidade no Ag2.
        "descricao_gerada": not descricao,
        # Links diretos das fotos informadas (so os que comecam com http, ate 8).
        "images": [u.strip() for u in fotos if u and u.strip().startswith("http")][:MAX_FOTOS_ALVO],
        # Prova mais forte de que um comparavel e o anuncio do proprio imovel (Ag2).
        "link_anuncio": link_anuncio or None,
        # Casa em condominio fechado (formulario): Ag2 nao tira os comparaveis de condominio.
        "em_condominio": bool(em_condominio) if tipo == "Casa" else None,
    }
    if preco and preco > 0:
        imovel_alvo["price"] = preco
        imovel_alvo["pricePerSqm"] = preco / area if area > 0 else 0
    logger.info(f"  [fotos] Fotos selecionadas: {len(imovel_alvo['images'])}")
    return imovel_alvo


# ─────────────────────────────────────────────────────────────────────────────
# Observadores
# ─────────────────────────────────────────────────────────────────────────────

class Observador:
    """
    Avisos do fluxo, na ordem em que acontecem. Nao muda nada no calculo.

    etapa(nome, **dados): "inicio", "coleta_inicio", "coleta_fim", "sem_anuncios",
        "comparaveis_inicio", "comparaveis_fim", "sem_comparaveis", "zona_inicio",
        "zona_fim", "zona_falhou", "agentes34_inicio", "agente4_fim", "agente4_falhou",
        "agente3_fim", "agente3_falhou", "preco_inicio", "preco_fim", "preco_falhou", "fim".
    aguardar(nome, terminou, situacao): chamado enquanto uma etapa roda em paralelo
        ("coleta", "agentes34"). A tela fica atualizando a barra ate terminou();
        sem isso, o fluxo so espera a etapa terminar.
    """

    def etapa(self, nome: str, **dados) -> None:
        pass

    def aguardar(self, nome: str, terminou, situacao=None) -> None:
        pass


class ObservadorLog(Observador):
    """Terminal: cada etapa vira uma linha no log."""

    def etapa(self, nome: str, **dados) -> None:
        resumo = {k: v for k, v in dados.items() if isinstance(v, (str, int, float, bool)) or v is None}
        logger.info(f"[Fluxo] {nome} {resumo if resumo else ''}".rstrip())


# ─────────────────────────────────────────────────────────────────────────────
# Fim da avaliacao (leilao, verificacoes, banco)
# ─────────────────────────────────────────────────────────────────────────────

def montar_resultado_final(ctx: dict, resultado_ag5: dict, id_registro=None, gravar: bool = True) -> dict:
    """
    Fim da avaliacao, depois do Agente 5: aviso da zona, avaliacao de leilao,
    resultado da tela, verificacoes e registro no banco (em segundo plano).

    ctx: o que os agentes 1 a 4 produziram (montado no fluxo e guardado na sessao).
    id_registro: id da linha no banco; outro quando o calculo e refeito pela resposta
    "Este anuncio e do seu imovel?" (os arquivos dos agentes continuam com o id da avaliacao).
    gravar: False = monta o registro (Excel) mas nao grava no banco (terminal, testes).
    """
    from services.detalhe_leilao import resultado_para_gravar
    from services.verificacoes import verificar_execucao

    id_execucao = ctx["id_execucao"]
    escopo_busca = ctx["escopo_busca"]
    tempos = ctx["tempos"]

    # ── RESUMO DA EXECUCAO (log para auditoria) ───────────────────
    logger.info("")
    logger.info("=" * 55)
    logger.info("  RESUMO DA EXECUCAO")
    logger.info("=" * 55)
    logger.info(f"  Agente 1 (coleta): {tempos['agente1']:.1f}s")
    logger.info(f"  Agente 2 (clustering): {tempos['agente2']:.1f}s")
    logger.info(f"  Agente 3+4 (paralelo): {tempos['agentes3e4']:.1f}s")
    logger.info(f"  Tempo total: {tempos['total']:.1f}s")
    # Comparaveis usados por situacao da zona (os nao verificados contam para o minimo).
    contagem_zona = contar_status_zona(resultado_ag5)
    aviso_zona = texto_aviso_zona(contagem_zona, escopo_busca)
    logger.info(
        f"  Usados no calculo: {contagem_zona['confirmado']} confirmados | "
        f"{contagem_zona['fallback']} zona_nao_verificada (contam para o minimo de 5) | "
        f"{contagem_zona['sem_validacao']} sem_validacao (socorro) | escopo_busca={escopo_busca}"
    )
    logger.info("=" * 55)

    # Avaliacao de leilao: so depois do Agente 5, com os valores do formulario
    # (nunca passaram por nenhum agente). A etapa atual (1o/2o leilao) sai pela data.
    dados_leilao = ctx["dados_leilao"]
    leilao_entrada = leilao = None
    if dados_leilao:
        leilao_entrada = {**dados_leilao, "origem": dados_leilao["banco"],
                          "codigo_caixa": dados_leilao.get("numero_imovel")}
        leilao = avaliar_imovel_leilao(resultado_ag5, dados_leilao)
    if leilao is not None:
        leilao["aviso_zona"] = aviso_zona
        # Endereco nao localizado com precisao de rua/bairro: o calculo segue, mas o
        # aviso fica junto da decisao para nao passar despercebido.
        leilao["alvo_sem_localizacao"] = ctx["alvo_sem_localizacao"]

    imoveis_coletados = ctx["imoveis_coletados"]
    resultado = {
        "status": "completo",
        "id_execucao": id_execucao,
        "aviso_zona": aviso_zona,
        "aviso_raio": texto_aviso_raio(ctx["zona_resultado"]),
        "leilao_entrada": leilao_entrada,
        "leilao": leilao,
        "duplicatas_descartadas": ctx["duplicatas_descartadas"],
        "comparaveis": ctx["comparaveis"],
        "terrenos": ctx["terrenos"],
        "zona_homogenea": ctx["zona_resultado"],
        "analise_qualitativa": ctx["resultado_ag3"],
        "infraestrutura": ctx["resultado_ag4"],
        "preco_estimado": resultado_ag5,
        "resumo": ctx["resumo"],
        # Para as verificacoes automaticas (services/verificacoes.py).
        "imovel_alvo": ctx["imovel_alvo"],
        # Situacao de cada fonte e contagens da coleta (Agente 1).
        "resumo_coleta": (imoveis_coletados[0].get("resumo_coleta") if imoveis_coletados
                          else ctx.get("resumo_coleta")),
        "falhas": ctx["falhas"],
        "localizacao_alvo": ctx["localizacao_alvo"],
    }
    # Verificacoes automaticas: leem o resultado de cada agente e conferem regras
    # (nao mudam nenhum calculo). Tela (modo conferencia), banco e Excel.
    resultado["verificacoes"] = verificar_execucao(resultado)

    # Grava a avaliacao no banco (Neon) em segundo plano: a tela nao espera e uma
    # falha do banco so vira aviso no log (services/banco.py).
    try:
        from services.banco import gravar_em_segundo_plano
        from services.registro_execucao import montar_registro
        entrada_usuario = ctx["entrada_usuario"]
        if id_registro:
            # Calculo refeito pela resposta da pessoa: linha nova no banco, ligada a original.
            entrada_usuario = {**(entrada_usuario or {}), "refeita_de": id_execucao,
                               "anuncios_do_alvo_pela_usuaria": resultado_ag5.get("anuncios_do_alvo_pela_usuaria")}
        registro_execucao, registro_comparaveis = montar_registro(
            id_execucao=id_registro or id_execucao,
            imovel_alvo=ctx["imovel_alvo"],
            leilao_entrada=leilao_entrada,
            leilao=leilao,
            imoveis_coletados=imoveis_coletados,
            resultado_ag2=ctx["resultado_ag2"],
            zona_resultado=ctx["zona_resultado"],
            resultado_ag3=ctx["resultado_ag3"],
            resultado_ag4=ctx["resultado_ag4"],
            resultado_ag5=resultado_ag5,
            tempos=tempos,
            falhas=ctx["falhas"],
            localizacao_alvo=ctx["localizacao_alvo"],
            entrada_usuario=entrada_usuario,
        )
        # Guardado no resultado (sessao) para o botao de exportar Excel: mesmo
        # conteudo gravado no banco.
        registro_execucao["verificacoes"] = resultado["verificacoes"]
        # Para o "Ver avaliacao completa" da pagina "Leiloes ativos" (migracao 006).
        registro_execucao["resultado_completo"] = resultado_para_gravar(resultado, ctx["tela_resultado"])
        resultado["registro"] = {"execucao": registro_execucao, "comparaveis": registro_comparaveis}
        if gravar:
            gravar_em_segundo_plano(registro_execucao, registro_comparaveis)
        else:
            logger.info("[Banco] avaliacao nao gravada (gravar=False)")
    except Exception as e:
        logger.warning(f"[Banco] registro nao montado: {type(e).__name__}: {e}")
    return resultado


def resultado_sem_anuncios(motivo: str) -> dict:
    """Resultado do Agente 5 quando a coleta nao trouxe nenhum anuncio (nao ha o que comparar)."""
    return {"status_avaliacao": "sem_amostra", "avaliacao_confiavel": False, "sem_anuncios": True,
            "zona_calculada_nesta_avaliacao": False, "avisos": [motivo],
            "comparaveis_usados": {"construcao": [], "terreno": []}}


def contexto_sem_anuncios(*, id_execucao, imovel_alvo, dados_leilao, alvo_sem_localizacao, falhas,
                          localizacao_alvo, entrada_usuario, tela_resultado, tempo_ag1, tempo_total) -> dict:
    """Contexto de montar_resultado_final sem anuncios: agentes 2 a 4 nao rodaram."""
    from agents.collector import resumo_da_coleta
    return {
        "id_execucao": id_execucao, "imovel_alvo": imovel_alvo, "imoveis_coletados": [],
        "escopo_busca": None, "resumo": {"total_coletados": 0, "tempo_coleta_s": round(tempo_ag1, 1)},
        "duplicatas_descartadas": [], "dados_leilao": dados_leilao, "alvo_sem_localizacao": alvo_sem_localizacao,
        "comparaveis": [], "terrenos": [], "zona_resultado": {}, "resultado_ag2": {}, "resultado_ag3": {},
        "resultado_ag4": {}, "falhas": falhas, "localizacao_alvo": localizacao_alvo,
        "entrada_usuario": entrada_usuario, "tela_resultado": tela_resultado,
        # Quantos anuncios o banco trouxe e por que nenhum sobrou (agents/collector.py).
        "resumo_coleta": resumo_da_coleta(id_execucao),
        "tempos": {"total": round(tempo_total, 1), "agente1": round(tempo_ag1, 1), "agente2": 0.0,
                   "zona": 0.0, "agentes3e4": 0.0},
    }


# ─────────────────────────────────────────────────────────────────────────────
# O fluxo
# ─────────────────────────────────────────────────────────────────────────────

def _localizar_alvo(imovel_alvo: dict) -> tuple[bool, str]:
    """
    Geocodificacao unica do alvo (a mesma do Agente 2), gravada em imovel_alvo para todos
    os agentes. Recusa precisao de cidade. Devolve (alvo_sem_localizacao, localizacao_alvo).
    """
    if imovel_alvo.get("lat") and imovel_alvo.get("lon"):
        logger.info(f"[Geo][Alvo] lat={imovel_alvo['lat']} | lon={imovel_alvo['lon']} | "
                    "geocodificacao_nova=false (ja existente)")
        return False, "coordenada_informada"
    from agents.comparables import _geocodificar_com_fallback
    a = imovel_alvo
    endereco_geo = ", ".join(p for p in (a.get("rua"), a.get("numero"), a.get("bairro"), a.get("cidade"),
                                         a.get("estado"), "Brasil") if p)
    logger.info(f"[Geo][Alvo] endereco={endereco_geo}")
    lat, lon, nivel, endereco_usado = _geocodificar_com_fallback(
        endereco_principal=endereco_geo, rua=a.get("rua"), numero=a.get("numero"), bairro=a.get("bairro"),
        cidade=a.get("cidade"), estado=a.get("estado"), permitir_cidade=False,
    )
    if lat is None or lon is None:
        logger.warning("[Geo][Alvo] Nao foi possivel localizar o alvo com precisao de rua ou bairro")
        return True, "nao_localizado"
    imovel_alvo.update({"lat": lat, "lon": lon, "geocodificacao_nivel": nivel})
    logger.info(f"[Geo][Alvo] lat={lat:.6f} | lon={lon:.6f} | nivel={nivel} | "
                f"endereco_usado={endereco_usado!r} | geocodificacao_nova=true")
    return False, nivel


def _duplicatas(imoveis_coletados: list[dict]) -> list[dict]:
    """O Ag1 junta o mesmo imovel de varios portais: cada representante guarda os descartados."""
    return [
        {
            "Mantido": im.get("source") or "-",
            "Preço": im.get("price") or im.get("preco"),
            "Área": im.get("area") or im.get("area_construida"),
            "Anúncio mantido": im.get("url") or "",
            "Descartado": dup.get("source") or dup.get("portal") or "-",
            "Anúncio descartado": dup.get("url") or "",
            "Motivo": str(dup.get("motivo") or "").split("(")[0],
        }
        for im in imoveis_coletados
        for dup in (im.get("duplicatas") or [])
    ]


def _resumo_da_coleta_para_tela(resumo: dict, imoveis_coletados: list[dict], rua: str, tempo_ag1: float,
                                n_duplicatas: int) -> dict:
    """Totais da coleta que a tela mostra (portais, quantos na rua)."""
    resumo["total_coletados"] = len(imoveis_coletados)
    resumo["tempo_coleta_s"] = round(tempo_ag1, 1)
    portais = {}
    for im in imoveis_coletados:
        # Os agentes gravam a origem em "source"; nenhum produz "portal".
        origem = str(im.get("source") or "").strip() or "Banco próprio"
        minusc = origem.lower()
        if "vivareal" in minusc or "viva real" in minusc:
            origem = "VivaReal"
        elif "lugar" in minusc:
            origem = "LugarCerto"
        elif "athena" in minusc or "s3" in minusc:
            origem = "Banco próprio"
        portais[origem] = portais.get(origem, 0) + 1
    resumo["portais"] = portais
    resumo["na_rua"] = sum(1 for im in imoveis_coletados
                           if rua and rua.lower() in (im.get("street") or im.get("rua") or "").lower())
    resumo["duplicatas_descartadas"] = n_duplicatas
    return resumo


def executar_avaliacao(
    imovel_alvo: dict,
    *,
    dados_leilao: dict | None = None,
    entrada_usuario: dict | None = None,
    tela_resultado: dict | None = None,
    obs: Observador | None = None,
    gravar: bool = True,
) -> dict:
    """
    Avaliacao completa. Devolve {"parada", "resultado", "contexto"}:
      parada: None (completa), "sem_anuncios" (resultado "Sem estimativa", ja montado e
              gravado) ou "sem_comparaveis" (resultado None: nada a calcular);
      resultado: o de montar_resultado_final (o que a tela mostra e o banco grava);
      contexto: o que os agentes 1 a 4 produziram (a tela guarda para refazer o calculo).
    gravar: False = nao grava no banco (terminal por padrao, testes).
    """
    from agents.collector import coletar_imoveis
    from agents.comparables import analisar_zona_homogenea, identificar_comparaveis, reiniciar_contagem_tomtom
    from agents.execucao import novo_id_execucao
    from agents.infra_evaluator import avaliar_infraestrutura
    from agents.price_liquidity import estimar_preco
    from agents.text_analyzer import analisar_comparaveis
    from services.textos_tela import texto_sem_anuncios

    obs = obs or Observador()
    tela_resultado = tela_resultado or {}
    a = imovel_alvo

    # Identifica esta avaliacao nos JSONs que os agentes trocam: os Agentes 3/4/5
    # ignoram arquivos de avaliacoes anteriores (ver agents/execucao.py).
    id_execucao = novo_id_execucao()
    # Limite de chamadas da TomTom (ultima tentativa de geocodificacao) e por avaliacao.
    reiniciar_contagem_tomtom()
    # Falhas desta avaliacao, gravadas no banco (a tela continua mostrando os avisos).
    falhas = []

    alvo_sem_localizacao, localizacao_alvo = _localizar_alvo(a)
    obs.etapa("inicio", alvo_sem_localizacao=alvo_sem_localizacao, id_execucao=id_execucao)
    inicio_total = time.time()

    # ── Agente 1: coleta (em outra thread, para a tela atualizar a barra) ──
    obs.etapa("coleta_inicio")
    resultado_coleta = [None]

    def _coletar():
        resultado_coleta[0] = coletar_imoveis(
            localizacao=a["localizacao"],
            tipo_imovel=a["tipo"],
            bairro=a.get("bairro", ""),
            rua=a.get("rua", ""),
            # Coordenada e precisao da localizacao feita acima: com rua ou bairro,
            # o Agente 1 traz tambem os anuncios mais proximos do imovel.
            lat_alvo=a.get("lat"),
            lon_alvo=a.get("lon"),
            nivel_geo_alvo=a.get("geocodificacao_nivel"),
            # Gravado em cada anuncio (verificacoes: dados desta execucao).
            id_execucao=id_execucao,
        )

    t1 = time.time()
    thread_coleta = threading.Thread(target=_coletar)
    thread_coleta.start()
    obs.aguardar("coleta", lambda: not thread_coleta.is_alive())
    thread_coleta.join()
    imoveis_coletados = resultado_coleta[0] or []
    tempo_ag1 = time.time() - t1

    if not imoveis_coletados:
        # Feijo/AC (31/10/2026): "Sem estimativa", gravada como as outras (aparece nos
        # leiloes ativos e conta nas estatisticas). Agentes 2 a 5 vazios.
        motivo = texto_sem_anuncios(TIPO_FORMULARIO.get(a["tipo"], "Casa"), a.get("cidade"), a.get("estado"))
        resultado = montar_resultado_final(
            contexto_sem_anuncios(
                id_execucao=id_execucao, imovel_alvo=a, dados_leilao=dados_leilao,
                alvo_sem_localizacao=alvo_sem_localizacao, falhas=falhas,
                localizacao_alvo=localizacao_alvo, entrada_usuario=entrada_usuario,
                tela_resultado=tela_resultado, tempo_ag1=tempo_ag1, tempo_total=time.time() - inicio_total,
            ),
            resultado_sem_anuncios(motivo),
            gravar=gravar,
        )
        obs.etapa("sem_anuncios", motivo=motivo, resultado=resultado)
        return {"parada": "sem_anuncios", "resultado": resultado, "contexto": None}

    duplicatas_descartadas = _duplicatas(imoveis_coletados)
    escopo_busca = imoveis_coletados[0].get("escopo_busca")
    obs.etapa("coleta_fim", imoveis_coletados=imoveis_coletados, duplicatas=duplicatas_descartadas,
              escopo_busca=escopo_busca, total=len(imoveis_coletados))

    # ── Agente 2: comparaveis ──
    obs.etapa("comparaveis_inicio")
    t2 = time.time()
    resultado_ag2 = identificar_comparaveis(
        imovel_alvo=a, imoveis_coletados=imoveis_coletados, usar_llm=True, id_execucao=id_execucao,
    )
    tempo_ag2 = time.time() - t2
    comparaveis = resultado_ag2.get("comparaveis", [])
    terrenos = resultado_ag2.get("terrenos", [])
    resumo = resultado_ag2.get("resumo", {})
    obs.etapa("comparaveis_fim", resumo=resumo, cluster_a=resumo.get("cluster_a", 0))
    if not comparaveis:
        obs.etapa("sem_comparaveis")
        return {"parada": "sem_comparaveis", "resultado": None, "contexto": None}

    # ── Zona homogenea (precisa da imagem de satelite: GOOGLE_MAPS_KEY) ──
    zona_resultado = None
    tempo_zona = 0.0
    if os.getenv("GOOGLE_MAPS_KEY"):
        obs.etapa("zona_inicio")
        try:
            t2z = time.time()
            zona_resultado = analisar_zona_homogenea(
                endereco_alvo=f"{a.get('rua')}, {a.get('numero')}, {a.get('bairro')}, {a.get('cidade')}, {a.get('estado')}",
                imoveis=[c for c in comparaveis if c.get("cluster") == "A"] + terrenos,
                cidade=a.get("cidade"),
                estado=a.get("estado"),
                lat_alvo_precomp=a.get("lat"),
                lon_alvo_precomp=a.get("lon"),
                id_execucao=id_execucao,
            )
            tempo_zona = time.time() - t2z
            obs.etapa("zona_fim", zona_resultado=zona_resultado, comparaveis=comparaveis, terrenos=terrenos)
        except Exception as e:
            falhas.append(f"zona_homogenea: {type(e).__name__}: {e}")
            obs.etapa("zona_falhou", erro=e)
    else:
        logger.info("GOOGLE_MAPS_KEY nao configurada — zona homogenea pulada")

    # ── Agentes 3 e 4, juntos ──
    obs.etapa("agentes34_inicio")
    resultado_ag3, resultado_ag4 = {}, {}
    t34 = time.time()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_ag3 = executor.submit(analisar_comparaveis, a, id_execucao=id_execucao)
        futuro_ag4 = executor.submit(avaliar_infraestrutura, id_execucao=id_execucao)
        obs.aguardar("agentes34", lambda: futuro_ag3.done() and futuro_ag4.done(),
                     lambda: (futuro_ag3.done(), futuro_ag4.done()))
        try:
            resultado_ag4 = futuro_ag4.result()
            obs.etapa("agente4_fim", resultado_ag4=resultado_ag4)
        except Exception as e:
            falhas.append(f"agente4: {type(e).__name__}: {e}")
            obs.etapa("agente4_falhou", erro=e)
        try:
            resultado_ag3 = futuro_ag3.result()
            obs.etapa("agente3_fim", resultado_ag3=resultado_ag3)
        except Exception as e:
            falhas.append(f"agente3: {type(e).__name__}: {e}")
            obs.etapa("agente3_falhou", erro=e)
    tempo_ag34 = time.time() - t34

    # ── Agente 5: preco ──
    obs.etapa("preco_inicio")
    resultado_ag5 = {}
    a["escopo_busca"] = escopo_busca   # so para o log do Agente 5
    try:
        resultado_ag5 = estimar_preco(imovel_alvo_extra=a, id_execucao=id_execucao)
        obs.etapa("preco_fim", resultado_ag5=resultado_ag5)
    except Exception as e:
        falhas.append(f"agente5: {type(e).__name__}: {e}")
        obs.etapa("preco_falhou", erro=e)

    tempo_total = time.time() - inicio_total
    obs.etapa("fim", tempo_total=tempo_total)

    resumo = _resumo_da_coleta_para_tela(resumo, imoveis_coletados, a.get("rua"), tempo_ag1,
                                         len(duplicatas_descartadas))
    # Tudo o que o fim do fluxo usa (resultado, leilao, verificacoes, banco). A tela
    # guarda na sessao: roda de novo quando a pessoa responde "Este anuncio e do seu imovel?".
    contexto = {
        "id_execucao": id_execucao, "imovel_alvo": a, "imoveis_coletados": imoveis_coletados,
        "escopo_busca": escopo_busca, "resumo": resumo, "duplicatas_descartadas": duplicatas_descartadas,
        "dados_leilao": dados_leilao, "alvo_sem_localizacao": alvo_sem_localizacao,
        "comparaveis": comparaveis, "terrenos": terrenos, "zona_resultado": zona_resultado,
        "resultado_ag2": resultado_ag2, "resultado_ag3": resultado_ag3, "resultado_ag4": resultado_ag4,
        "falhas": falhas, "localizacao_alvo": localizacao_alvo,
        "entrada_usuario": entrada_usuario, "tela_resultado": tela_resultado,
        "tempos": {
            "total": round(tempo_total, 1),
            "agente1": round(tempo_ag1, 1),
            "agente2": round(tempo_ag2, 1),
            "zona": round(tempo_zona, 1),
            "agentes3e4": round(tempo_ag34, 1),
        },
    }
    resultado = montar_resultado_final(contexto, resultado_ag5, gravar=gravar)
    return {"parada": None, "resultado": resultado, "contexto": contexto}
