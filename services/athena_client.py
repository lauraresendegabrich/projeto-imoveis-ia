"""
Cliente para consultas no Amazon Athena.
Consulta dados de imóveis armazenados no S3 em formato Parquet.

Uso:
    from services.athena_client import AthenaClient
    client = AthenaClient()
    resultados = client.buscar_cidade("Campinas")
    resultados = client.buscar_cidade("Americana", quartos_min=3, preco_max=500000)
"""

import boto3
import time
import os
from dotenv import load_dotenv

load_dotenv()


class AthenaClient:
    """Cliente para consultas SQL no Amazon Athena."""

    def __init__(self):
        self.athena = boto3.client(
            "athena",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-2"),
        )
        self.database = "imoveis"
        self.output_location = "s3://athena-results-imoveis/"

    def executar_query(self, sql: str, timeout: int = 30) -> list[dict]:
        """Executa uma query SQL e retorna lista de dicts."""
        # Inicia a query
        response = self.athena.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": self.database},
            ResultConfiguration={"OutputLocation": self.output_location},
        )
        query_id = response["QueryExecutionId"]

        # Aguarda resultado
        for _ in range(timeout):
            status = self.athena.get_query_execution(QueryExecutionId=query_id)
            state = status["QueryExecution"]["Status"]["State"]
            if state == "SUCCEEDED":
                break
            elif state == "FAILED":
                reason = status["QueryExecution"]["Status"].get("StateChangeReason", "Erro desconhecido")
                raise Exception(f"Query falhou: {reason}")
            time.sleep(1)
        else:
            raise Exception("Query timeout")

        # Pega resultados
        results = self.athena.get_query_results(QueryExecutionId=query_id)
        rows = results["ResultSet"]["Rows"]

        if len(rows) < 2:
            return []

        # Primeira row é o header
        headers = [col["VarCharValue"] for col in rows[0]["Data"]]

        # Converte para lista de dicts
        data = []
        for row in rows[1:]:
            values = [col.get("VarCharValue", None) for col in row["Data"]]
            data.append(dict(zip(headers, values)))

        # Pagina se tiver mais resultados
        while "NextToken" in results:
            results = self.athena.get_query_results(
                QueryExecutionId=query_id,
                NextToken=results["NextToken"],
            )
            for row in results["ResultSet"]["Rows"]:
                values = [col.get("VarCharValue", None) for col in row["Data"]]
                data.append(dict(zip(headers, values)))

        return data

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
        """Busca anúncios de uma cidade com filtros opcionais."""
        conditions = [f"cidade = '{cidade}'", "finalidade = 'venda'"]
        if estado:
            conditions.append(f"estado = '{estado}'")
        if quartos_min:
            conditions.append(f"quartos >= {quartos_min}")
        if preco_max:
            conditions.append(f"preco <= {preco_max}")
        if preco_min:
            conditions.append(f"preco >= {preco_min}")
        if tipo:
            conditions.append(f"tipo = '{tipo}'")

        where = " AND ".join(conditions)
        sql = f"""WITH base AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY url ORDER BY data_publicacao DESC) AS rn
            FROM vivareal WHERE {where}
        ) SELECT * FROM base WHERE rn = 1 LIMIT {limit}"""
        return self.executar_query(sql)

    def buscar_bairro_rua(self, cidade: str, bairro: str, rua: str = "", tipo: str = None, limit: int = 200) -> list[dict]:
        """
        Query unificada: busca no bairro com prioridade pra mesma rua.
        1 query por tipo — dedup por URL, prioridade 0=rua, 1=bairro.
        Fallback de acentos: nome exato → sem acento → parte final.
        """
        import unicodedata
        bairro_sem_acento = unicodedata.normalize("NFD", bairro).encode("ascii", "ignore").decode()
        palavras_b = bairro.split()
        prefixos_bairro = {"jardim", "jd", "jd.", "vila", "vl", "parque", "pq", "residencial", "res", "conjunto", "cj"}
        palavras_sem_prefixo_b = [p for p in palavras_b if p.lower() not in prefixos_bairro]
        parte_final_b = palavras_sem_prefixo_b[-1] if palavras_sem_prefixo_b else palavras_b[-1]

        # Monta campo de prioridade
        if rua:
            rua_sem_acento = unicodedata.normalize("NFD", rua).encode("ascii", "ignore").decode()
            palavras_r = rua.split()
            prefixos_rua = {"rua", "avenida", "av", "av.", "alameda", "travessa", "praça", "estrada"}
            palavras_sem_prefixo_r = [p for p in palavras_r if p.lower() not in prefixos_rua]
            parte_final_r = palavras_sem_prefixo_r[-1] if palavras_sem_prefixo_r else palavras_r[-1]
            # Usa parte final da rua pra LIKE (mais robusto com acentos)
            rua_like = parte_final_r if len(parte_final_r) >= 4 else rua_sem_acento
            prioridade_sql = f"CASE WHEN rua LIKE '%{rua_like}%' THEN 0 ELSE 1 END"
        else:
            prioridade_sql = "1"

        def _build_sql(bairro_cond, limit):
            tipo_cond = f"AND tipo = '{tipo}'" if tipo else ""
            return f"""WITH candidatos AS (
                SELECT *, {prioridade_sql} AS prioridade
                FROM vivareal
                WHERE cidade = '{cidade}' AND {bairro_cond} AND finalidade = 'venda' {tipo_cond}
            ), dedup AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY url ORDER BY prioridade ASC, data_publicacao DESC) AS rn
                FROM candidatos
            )
            SELECT * FROM dedup WHERE rn = 1 ORDER BY prioridade ASC, data_publicacao DESC LIMIT {limit}"""

        # Tentativa 1: bairro exato
        resultados = self.executar_query(_build_sql(f"bairro = '{bairro}'", limit))

        # Tentativa 2: sem acento
        if not resultados and bairro_sem_acento != bairro:
            resultados = self.executar_query(_build_sql(f"bairro = '{bairro_sem_acento}'", limit))

        # Tentativa 3: LIKE parte final
        if not resultados and len(parte_final_b) >= 4:
            resultados = self.executar_query(_build_sql(f"bairro LIKE '%{parte_final_b}%'", limit))

        return resultados

    def buscar_bairro(self, cidade: str, bairro: str, tipo: str = None, limit: int = 200) -> list[dict]:
        """Wrapper: busca no bairro sem prioridade de rua."""
        return self.buscar_bairro_rua(cidade, bairro, rua="", tipo=tipo, limit=limit)

    def buscar_rua(self, cidade: str, bairro: str, rua: str, tipo: str = None, limit: int = 50) -> list[dict]:
        """Wrapper: busca com prioridade pra rua (retorna mesma rua primeiro)."""
        return self.buscar_bairro_rua(cidade, bairro, rua=rua, tipo=tipo, limit=limit)

    def estatisticas_cidade(self, cidade: str) -> dict:
        """Retorna estatísticas de uma cidade."""
        sql = f"""
            SELECT
                COUNT(*) as total_anuncios,
                AVG(preco) as preco_medio,
                MIN(preco) as preco_minimo,
                MAX(preco) as preco_maximo,
                AVG(area_construida) as area_media,
                AVG(quartos) as quartos_medio
            FROM vivareal
            WHERE cidade = '{cidade}' AND preco > 0
        """
        results = self.executar_query(sql)
        return results[0] if results else {}

    def listar_bairros(self, cidade: str) -> list[dict]:
        """Lista bairros de uma cidade com contagem de anúncios."""
        sql = f"""
            SELECT bairro, COUNT(*) as total, AVG(preco) as preco_medio
            FROM vivareal
            WHERE cidade = '{cidade}' AND bairro IS NOT NULL AND bairro != ''
            GROUP BY bairro
            ORDER BY total DESC
        """
        return self.executar_query(sql)

    def listar_cidades(self, estado: str = "SP") -> list[dict]:
        """Lista cidades de um estado com contagem de anúncios."""
        sql = f"""
            SELECT cidade, COUNT(*) as total, AVG(preco) as preco_medio
            FROM vivareal
            WHERE estado = '{estado}'
            GROUP BY cidade
            ORDER BY total DESC
        """
        return self.executar_query(sql)


# Exemplo de uso
if __name__ == "__main__":
    client = AthenaClient()

    print("=== Estatísticas de Americana ===")
    stats = client.estatisticas_cidade("Americana")
    print(stats)

    print("\n=== Top 5 bairros de Americana ===")
    bairros = client.listar_bairros("Americana")
    for b in bairros[:5]:
        print(f"  {b['bairro']}: {b['total']} anúncios, média R$ {b['preco_medio']}")

    print("\n=== Anúncios em Americana com 3+ quartos ===")
    anuncios = client.buscar_cidade("Americana", quartos_min=3, limit=5)
    for a in anuncios:
        print(f"  {a.get('url', '?')} - R$ {a.get('preco', '?')} - {a.get('quartos', '?')}q - {a.get('bairro', '?')}")
