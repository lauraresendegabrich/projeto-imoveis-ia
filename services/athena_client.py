"""
Cliente para consultas no Amazon Athena.

Consulta dados de imoveis armazenados no S3 em formato Parquet.

Principais garantias desta versao:
- usa a cadeia padrao de credenciais do boto3 (env/profile/IAM Role);
- trata SUCCEEDED, FAILED e CANCELLED;
- cancela query ao estourar timeout;
- pagina todos os resultados;
- escapa literais SQL recebidos por parametro;
- filtra por estado quando informado;
- compara rua/bairro de forma tolerante a caixa, acentos e prefixos;
- nao agrupa todos os registros sem URL na mesma particao de deduplicacao.
"""

import logging
import os
import re
import time
import unicodedata

import boto3
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class AthenaClient:
    """Cliente para consultas SQL no Amazon Athena."""

    def __init__(self):
        # Nao injeta access key manualmente: boto3 resolve env, ~/.aws, SSO,
        # ECS/EC2 IAM Role e outras fontes da cadeia padrao de credenciais.
        self.athena = boto3.client(
            "athena",
            region_name=os.getenv("AWS_REGION", "us-east-2"),
        )
        self.database = os.getenv("ATHENA_DATABASE", "imoveis")
        self.output_location = os.getenv(
            "ATHENA_OUTPUT_LOCATION",
            "s3://athena-results-imoveis/",
        )
        self.workgroup = os.getenv("ATHENA_WORKGROUP", "").strip() or None
        self.table = "vivareal"

    # ------------------------------------------------------------------
    # Utilitarios SQL
    # ------------------------------------------------------------------

    @staticmethod
    def _sql_escape(valor: object) -> str:
        """Escapa apostrofo para literal SQL do Athena/Presto/Trino."""
        return str(valor).replace("'", "''")

    @staticmethod
    def _normalizar_texto(valor: object) -> str:
        if valor is None:
            return ""
        texto = unicodedata.normalize("NFD", str(valor))
        texto = texto.encode("ascii", "ignore").decode().lower().strip()
        texto = re.sub(r"[^a-z0-9]+", " ", texto)
        return re.sub(r"\s+", " ", texto).strip()

    @classmethod
    def _chave_bairro(cls, bairro: object) -> str:
        valor = cls._normalizar_texto(bairro)
        partes = valor.split()
        aliases = {
            "jd": "jardim", "vl": "vila", "pq": "parque", "res": "residencial",
            "cj": "conjunto", "lot": "loteamento",
        }
        if partes and partes[0] in aliases:
            partes[0] = aliases[partes[0]]
        return " ".join(partes)

    @classmethod
    def _core_bairro(cls, bairro: object) -> str:
        valor = cls._chave_bairro(bairro)
        partes = valor.split()
        prefixos = {"jardim", "vila", "parque", "residencial", "conjunto", "loteamento"}
        if partes and partes[0] in prefixos:
            partes = partes[1:]
        return " ".join(partes) or valor

    @classmethod
    def _chave_rua(cls, rua: object) -> str:
        if rua is None:
            return ""
        bruto = str(rua).strip()
        bruto = re.sub(
            r",\s*(?:n(?:[ºo°.]*)\s*)?\d+[a-zA-Z-]*.*$",
            "",
            bruto,
            flags=re.I,
        )
        bruto = re.sub(
            r"\s+(?:n(?:[ºo°.]*)|numero)\s*\d+[a-zA-Z-]*.*$",
            "",
            bruto,
            flags=re.I,
        )
        valor = cls._normalizar_texto(bruto)
        partes = valor.split()
        prefixos = {
            "rua", "r", "avenida", "av", "alameda", "travessa", "praca", "estrada",
            "rodovia", "largo",
        }
        while partes and partes[0] in prefixos:
            partes.pop(0)
        return " ".join(partes) or valor

    @staticmethod
    def _sql_normalizado(campo: str) -> str:
        """
        Expressao Athena para lowercase + remocao dos acentos mais comuns +
        normalizacao de pontuacao/espacos.
        """
        acentos = "áàãâäéèêëíìîïóòõôöúùûüç"
        sem_acentos = "aaaaaeeeeiiiiooooouuuuc"
        return (
            "trim(regexp_replace("
            f"translate(lower(coalesce(CAST({campo} AS VARCHAR), '')), "
            f"'{acentos}', '{sem_acentos}'), "
            "'[^a-z0-9]+', ' '))"
        )

    @classmethod
    def _condicao_igual_normalizada(cls, campo: str, valor: object) -> str:
        normalizado = cls._normalizar_texto(valor)
        return f"{cls._sql_normalizado(campo)} = '{cls._sql_escape(normalizado)}'"

    @classmethod
    def _condicao_texto_local(cls, campo: str, valor: str, tipo: str) -> str:
        """Monta condicao tolerante sem transformar bairros distintos em equivalentes."""
        if not valor:
            return "FALSE"

        expr = cls._sql_normalizado(campo)
        completo = cls._normalizar_texto(valor)
        partes: list[str] = []

        if tipo == "bairro":
            canonico = cls._chave_bairro(valor)
            core = cls._core_bairro(valor)
            variantes = [canonico]
            # Variante abreviada do prefixo para bases que guardam Jd/Vl/Pq.
            abrevia = {
                "jardim": "jd", "vila": "vl", "parque": "pq",
                "residencial": "res", "conjunto": "cj", "loteamento": "lot",
            }
            tokens = canonico.split()
            if tokens and tokens[0] in abrevia:
                variantes.append(" ".join([abrevia[tokens[0]]] + tokens[1:]))
            if completo not in variantes:
                variantes.append(completo)

            for candidato in dict.fromkeys(v for v in variantes if v):
                lit = cls._sql_escape(candidato)
                partes.append(f"{expr} = '{lit}'")
                partes.append(f"{expr} LIKE '%{lit}%'")

            # A forma sem prefixo e aceita apenas como igualdade, evitando que
            # Jardim Guanabara case com Vila Guanabara por um LIKE generico.
            if core and core != canonico:
                partes.append(f"{expr} = '{cls._sql_escape(core)}'")

        elif tipo == "rua":
            chave = cls._chave_rua(valor)
            candidatos = [completo, chave]
            if chave:
                ultimo = chave.split()[-1]
                if len(ultimo) >= 4:
                    candidatos.append(ultimo)
            for candidato in dict.fromkeys(v for v in candidatos if v):
                lit = cls._sql_escape(candidato)
                partes.append(f"{expr} = '{lit}'")
                partes.append(f"{expr} LIKE '%{lit}%'")
        else:
            raise ValueError(f"tipo de local invalido: {tipo}")

        return "(" + " OR ".join(partes) + ")"

    @staticmethod
    def _normalizar_limit(limit: int, maximo: int = 5000) -> int:
        try:
            valor = int(limit)
        except (TypeError, ValueError):
            raise ValueError(f"limit invalido: {limit!r}")
        if valor <= 0:
            raise ValueError("limit deve ser maior que zero")
        return min(valor, maximo)

    def _chave_dedup_sql(self) -> str:
        """
        URL > listing_id > fingerprint extensa.

        O fallback inclui muitos campos para nao transformar todos os NULL URLs em
        uma unica particao e para evitar apagar anuncios diferentes por acidente.
        """
        return """
            COALESCE(
                NULLIF(TRIM(CAST(url AS VARCHAR)), ''),
                CASE
                    WHEN listing_id IS NOT NULL
                        THEN CONCAT('__listing__', CAST(listing_id AS VARCHAR))
                    ELSE CONCAT(
                        '__fallback__|',
                        COALESCE(CAST(cidade AS VARCHAR), ''), '|',
                        COALESCE(CAST(bairro AS VARCHAR), ''), '|',
                        COALESCE(CAST(rua AS VARCHAR), ''), '|',
                        COALESCE(CAST(tipo AS VARCHAR), ''), '|',
                        COALESCE(CAST(preco AS VARCHAR), ''), '|',
                        COALESCE(CAST(area_construida AS VARCHAR), ''), '|',
                        COALESCE(CAST(quartos AS VARCHAR), ''), '|',
                        COALESCE(CAST(titulo AS VARCHAR), ''), '|',
                        COALESCE(CAST(data_publicacao AS VARCHAR), ''), '|',
                        COALESCE(CAST(fotos_urls AS VARCHAR), '')
                    )
                END
            )
        """.strip()

    # ------------------------------------------------------------------
    # Execucao
    # ------------------------------------------------------------------

    def executar_query(self, sql: str, timeout: int = 30) -> list[dict]:
        """Executa uma query SQL e retorna todas as paginas como lista de dicts."""
        try:
            timeout_segundos = float(timeout)
        except (TypeError, ValueError):
            raise ValueError(f"timeout invalido: {timeout!r}")
        if timeout_segundos <= 0:
            raise ValueError("timeout deve ser maior que zero")

        parametros = {
            "QueryString": sql,
            "QueryExecutionContext": {"Database": self.database},
            "ResultConfiguration": {"OutputLocation": self.output_location},
        }
        if self.workgroup:
            parametros["WorkGroup"] = self.workgroup

        response = self.athena.start_query_execution(**parametros)
        query_id = response["QueryExecutionId"]
        deadline = time.monotonic() + timeout_segundos

        while True:
            status = self.athena.get_query_execution(QueryExecutionId=query_id)
            status_query = status["QueryExecution"]["Status"]
            state = status_query["State"]

            if state == "SUCCEEDED":
                break

            if state in {"FAILED", "CANCELLED"}:
                reason = status_query.get("StateChangeReason", "Erro desconhecido")
                raise RuntimeError(f"Query Athena {state.lower()}: {reason}")

            if time.monotonic() >= deadline:
                try:
                    self.athena.stop_query_execution(QueryExecutionId=query_id)
                except Exception as exc:
                    logger.warning(f"Nao foi possivel cancelar query {query_id}: {exc}")
                raise TimeoutError(f"Query Athena excedeu timeout de {timeout_segundos:g}s")

            time.sleep(0.5)

        # Primeira pagina: usa metadata para os headers e remove a linha-header
        # somente se ela realmente estiver presente.
        pagina = self.athena.get_query_results(QueryExecutionId=query_id)
        metadata = pagina.get("ResultSet", {}).get("ResultSetMetadata", {})
        headers = [col.get("Name", "") for col in metadata.get("ColumnInfo", [])]
        if not headers:
            return []

        data: list[dict] = []
        primeira_pagina = True

        while True:
            rows = pagina.get("ResultSet", {}).get("Rows", [])

            if primeira_pagina and rows:
                primeira = [
                    col.get("VarCharValue") for col in rows[0].get("Data", [])
                ]
                if primeira == headers:
                    rows = rows[1:]

            for row in rows:
                cols = row.get("Data", [])
                values = [
                    cols[idx].get("VarCharValue") if idx < len(cols) else None
                    for idx in range(len(headers))
                ]
                data.append(dict(zip(headers, values)))

            token = pagina.get("NextToken")
            if not token:
                break

            pagina = self.athena.get_query_results(
                QueryExecutionId=query_id,
                NextToken=token,
            )
            primeira_pagina = False

        return data

    # ------------------------------------------------------------------
    # Buscas
    # ------------------------------------------------------------------

    def buscar_cidade(
        self,
        cidade: str,
        estado: str = None,
        quartos_min: int = None,
        preco_max: float = None,
        preco_min: float = None,
        tipo: str = None,
        limit: int = 200,
    ) -> list[dict]:
        """Busca anuncios de venda de uma cidade com filtros opcionais."""
        limit = self._normalizar_limit(limit)
        conditions = [
            self._condicao_igual_normalizada("cidade", cidade),
            "finalidade = 'venda'",
        ]

        if estado:
            conditions.append(f"estado = '{self._sql_escape(str(estado).upper())}'")
        if quartos_min is not None:
            conditions.append(f"quartos >= {int(quartos_min)}")
        if preco_max is not None:
            conditions.append(f"preco <= {float(preco_max)}")
        if preco_min is not None:
            conditions.append(f"preco >= {float(preco_min)}")
        if tipo:
            conditions.append(f"tipo = '{self._sql_escape(tipo)}'")

        where = " AND ".join(conditions)
        chave = self._chave_dedup_sql()
        sql = f"""
            WITH base AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY {chave}
                           ORDER BY data_publicacao DESC NULLS LAST
                       ) AS rn
                FROM {self.table}
                WHERE {where}
            )
            SELECT *
            FROM base
            WHERE rn = 1
            ORDER BY data_publicacao DESC NULLS LAST
            LIMIT {limit}
        """
        return self.executar_query(sql)

    def buscar_bairro_rua(
        self,
        cidade: str,
        bairro: str,
        rua: str = "",
        tipo: str = None,
        limit: int = 200,
        estado: str = None,
    ) -> list[dict]:
        """
        Busca unificada por RUA OU BAIRRO dentro da cidade/UF.

        - mesma rua: prioridade 0;
        - mesmo bairro: prioridade 1;
        - deduplica por URL/listing_id/fallback seguro;
        - tolera caixa, acentos e prefixos comuns (Rua/R., Jardim/Jd. etc.).
        """
        limit = self._normalizar_limit(limit)
        if not bairro and not rua:
            return self.buscar_cidade(
                cidade=cidade,
                estado=estado,
                tipo=tipo,
                limit=limit,
            )

        rua_cond = self._condicao_texto_local("rua", rua, "rua") if rua else "FALSE"
        bairro_cond = (
            self._condicao_texto_local("bairro", bairro, "bairro") if bairro else "FALSE"
        )
        local_cond = f"({rua_cond} OR {bairro_cond})"

        if rua:
            prioridade_sql = (
                f"CASE WHEN {rua_cond} THEN 0 "
                f"WHEN {bairro_cond} THEN 1 ELSE 2 END"
            )
        else:
            prioridade_sql = "1"

        conditions = [
            self._condicao_igual_normalizada("cidade", cidade),
            "finalidade = 'venda'",
            local_cond,
        ]
        if estado:
            conditions.append(f"estado = '{self._sql_escape(str(estado).upper())}'")
        if tipo:
            conditions.append(f"tipo = '{self._sql_escape(tipo)}'")

        where = " AND ".join(conditions)
        chave = self._chave_dedup_sql()
        sql = f"""
            WITH candidatos AS (
                SELECT *, {prioridade_sql} AS prioridade
                FROM {self.table}
                WHERE {where}
            ), dedup AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY {chave}
                           ORDER BY prioridade ASC, data_publicacao DESC NULLS LAST
                       ) AS rn
                FROM candidatos
            )
            SELECT *
            FROM dedup
            WHERE rn = 1
            ORDER BY prioridade ASC, data_publicacao DESC NULLS LAST
            LIMIT {limit}
        """
        return self.executar_query(sql)

    def buscar_bairro(
        self,
        cidade: str,
        bairro: str,
        tipo: str = None,
        limit: int = 200,
        estado: str = None,
    ) -> list[dict]:
        """Wrapper: busca no bairro sem prioridade de rua."""
        return self.buscar_bairro_rua(
            cidade=cidade,
            bairro=bairro,
            rua="",
            tipo=tipo,
            limit=limit,
            estado=estado,
        )

    def buscar_rua(
        self,
        cidade: str,
        bairro: str,
        rua: str,
        tipo: str = None,
        limit: int = 50,
        estado: str = None,
    ) -> list[dict]:
        """Wrapper: busca rua OU bairro e coloca a mesma rua primeiro."""
        return self.buscar_bairro_rua(
            cidade=cidade,
            bairro=bairro,
            rua=rua,
            tipo=tipo,
            limit=limit,
            estado=estado,
        )

    # ------------------------------------------------------------------
    # Estatisticas auxiliares - sempre sobre anuncios de venda deduplicados
    # ------------------------------------------------------------------

    def estatisticas_cidade(self, cidade: str, estado: str = None) -> dict:
        conditions = [
            self._condicao_igual_normalizada("cidade", cidade),
            "finalidade = 'venda'",
            "preco > 0",
        ]
        if estado:
            conditions.append(f"estado = '{self._sql_escape(str(estado).upper())}'")
        where = " AND ".join(conditions)
        chave = self._chave_dedup_sql()

        sql = f"""
            WITH base AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY {chave}
                           ORDER BY data_publicacao DESC NULLS LAST
                       ) AS rn
                FROM {self.table}
                WHERE {where}
            )
            SELECT
                COUNT(*) AS total_anuncios,
                AVG(preco) AS preco_medio,
                MIN(preco) AS preco_minimo,
                MAX(preco) AS preco_maximo,
                AVG(area_construida) AS area_media,
                AVG(quartos) AS quartos_medio
            FROM base
            WHERE rn = 1
        """
        results = self.executar_query(sql)
        return results[0] if results else {}

    def listar_bairros(self, cidade: str, estado: str = None) -> list[dict]:
        conditions = [
            self._condicao_igual_normalizada("cidade", cidade),
            "finalidade = 'venda'",
            "bairro IS NOT NULL",
            "bairro != ''",
        ]
        if estado:
            conditions.append(f"estado = '{self._sql_escape(str(estado).upper())}'")
        where = " AND ".join(conditions)
        chave = self._chave_dedup_sql()

        sql = f"""
            WITH base AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY {chave}
                           ORDER BY data_publicacao DESC NULLS LAST
                       ) AS rn
                FROM {self.table}
                WHERE {where}
            )
            SELECT bairro, COUNT(*) AS total, AVG(preco) AS preco_medio
            FROM base
            WHERE rn = 1
            GROUP BY bairro
            ORDER BY total DESC
        """
        return self.executar_query(sql)

    def listar_cidades(self, estado: str = "SP") -> list[dict]:
        estado_sql = self._sql_escape(str(estado).upper())
        chave = self._chave_dedup_sql()
        sql = f"""
            WITH base AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY {chave}
                           ORDER BY data_publicacao DESC NULLS LAST
                       ) AS rn
                FROM {self.table}
                WHERE estado = '{estado_sql}' AND finalidade = 'venda'
            )
            SELECT cidade, COUNT(*) AS total, AVG(preco) AS preco_medio
            FROM base
            WHERE rn = 1
            GROUP BY cidade
            ORDER BY total DESC
        """
        return self.executar_query(sql)


if __name__ == "__main__":
    client = AthenaClient()

    print("=== Estatisticas de Americana ===")
    stats = client.estatisticas_cidade("Americana", estado="SP")
    print(stats)

    print("\n=== Top 5 bairros de Americana ===")
    bairros = client.listar_bairros("Americana", estado="SP")
    for b in bairros[:5]:
        print(f"  {b['bairro']}: {b['total']} anuncios, media R$ {b['preco_medio']}")

    print("\n=== Anuncios em Americana com 3+ quartos ===")
    anuncios = client.buscar_cidade(
        "Americana",
        estado="SP",
        quartos_min=3,
        limit=5,
    )
    for a in anuncios:
        print(
            f"  {a.get('url', '?')} - R$ {a.get('preco', '?')} - "
            f"{a.get('quartos', '?')}q - {a.get('bairro', '?')}"
        )
