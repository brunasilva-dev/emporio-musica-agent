"""Camada de dados da Empório da Música.

Carrega os CSVs, trata inconsistências e expõe consultas de negócio prontas
para serem usadas como ferramentas (tools) pelo agente.

Princípio: o LLM conversa, o código calcula. Preço final, promoção,
parcelamento, disponibilidade e prazos de troca são calculados aqui, de forma
determinística, e nunca deixados para o modelo "adivinhar".
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

DESCONTO_PIX = 0.05  # Políticas, seção 3: 5% no PIX (não cumulativo com promoção)

# Políticas, seção 3.1: (máximo de parcelas da faixa, parcela mínima).
# Suposição documentada: a tabela da seção 3 fala em "parcela mínima de R$ 100",
# mas a seção 3.1 é mais detalhada e foi considerada a regra válida.
FAIXAS_PARCELAMENTO = [(3, 50.0), (6, 80.0), (12, 100.0)]

STATUS_PEDIDO = {
    "pending": "pendente (aguardando confirmação de pagamento)",
    "confirmed": "confirmado (em separação para envio)",
    "shipped": "enviado (em transporte)",
    "delivered": "entregue",
    "cancelled": "cancelado",
}

FORMAS_PAGAMENTO = {
    "pix": "PIX",
    "debit": "cartão de débito",
    "boleto": "boleto bancário",
}

# Palavras-chave extras por categoria, para que "violão" encontre a categoria
# "Violões" (os nomes dos produtos nem sempre contêm o tipo do instrumento).
APELIDOS_CATEGORIA = {
    1: "guitarra guitarras eletrica",
    2: "baixo baixos contrabaixo eletrico",
    3: "bateria baterias percussao",
    4: "teclado teclados piano pianos sintetizador synth",
    5: "violao violoes",
    6: "sopro madeiras flauta clarinete saxofone sax oboe",
    7: "sopro metais trompete trombone tuba trompa",
    8: "cordas orquestrais violino viola violoncelo",
    9: "ukulele ukuleles",
}

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "da", "do", "das", "dos", "e",
    "em", "no", "na", "com", "para", "pra", "por", "ate", "que", "tem",
    "voces", "vcs", "quero", "algum", "alguma", "opcoes", "opcao",
}


# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e sem pontuação (para buscas)."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9 ]", " ", texto.lower())
    return re.sub(r"\s+", " ", texto).strip()


def brl(valor: float) -> str:
    """Formata valor no padrão brasileiro: 2199.0 -> 'R$ 2.199,00'."""
    s = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def simular_parcelamento(valor: float) -> dict:
    """Maior número de parcelas sem juros permitido para o valor (seção 3.1)."""
    melhor = 1
    for max_parcelas, minimo in FAIXAS_PARCELAMENTO:
        for n in range(1, max_parcelas + 1):
            if valor / n >= minimo:
                melhor = max(melhor, n)
    return {
        "parcelas": melhor,
        "valor_parcela": brl(valor / melhor),
        "texto": f"até {melhor}x de {brl(valor / melhor)} sem juros",
    }


def _similaridade_nome(consulta: str, nome: str, **_) -> float:
    """Combina comparação por palavras com comparação sem espaços.

    Assim "takamini gd 20" encontra "takamine gd20 dreadnought natural"
    (erro de digitação + espaço no modelo).
    """
    por_palavras = fuzz.token_set_ratio(consulta, nome)
    sem_espacos = fuzz.partial_ratio(consulta.replace(" ", ""), nome.replace(" ", ""))
    return max(por_palavras, sem_espacos * 0.95)


def _forma_pagamento(codigo: str) -> str:
    if codigo.startswith("credit_"):
        return f"cartão de crédito em {codigo.split('_')[1]}"
    return FORMAS_PAGAMENTO.get(codigo, codigo)


def _so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto))


# --------------------------------------------------------------------------
# Repositório de dados
# --------------------------------------------------------------------------

class StoreData:
    """Carrega e consulta os dados operacionais da loja."""

    def __init__(self, data_dir: Path = DATA_DIR, hoje: date | None = None):
        self.hoje = hoje or date.today()
        ler = lambda nome: pd.read_csv(data_dir / f"{nome}.csv")

        self.categorias = ler("categories")
        self.promocoes = ler("promotions")
        self.clientes = ler("customers")
        self.pedidos = ler("orders")
        self.itens = ler("order_items")
        self.produtos = self._preparar_produtos(ler("products"))

    # ---------------------------- produtos --------------------------------

    def _preparar_produtos(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.merge(
            self.categorias[["category_id", "name"]].rename(columns={"name": "categoria"}),
            on="category_id",
            how="left",
        )

        # Promoção vigente: só vale is_active == 1. Se houver mais de uma
        # ativa para o mesmo produto, prevalece o maior desconto.
        ativas = (
            self.promocoes[self.promocoes["is_active"] == 1]
            .sort_values("discount_percent", ascending=False)
            .drop_duplicates("product_id")
            [["product_id", "discount_percent", "description"]]
            .rename(columns={"description": "promocao"})
        )
        df = df.merge(ativas, on="product_id", how="left")

        df["specs"] = df["specs"].apply(lambda s: json.loads(s) if isinstance(s, str) else {})
        df["texto_busca"] = df.apply(
            lambda r: normalizar(
                f"{r['name']} {r['categoria']} {APELIDOS_CATEGORIA.get(r['category_id'], '')} "
                f"{r['description']} {' '.join(map(str, r['specs'].values()))}"
            ),
            axis=1,
        )
        df["nome_norm"] = df["name"].apply(normalizar)
        return df.sort_values("product_id").reset_index(drop=True)

    @staticmethod
    def _disponibilidade(row) -> tuple[str, bool]:
        """Retorna (rótulo, pode_comprar).

        Suposições documentadas:
        - 'discontinued' não é vendável mesmo com estoque (ex.: produto 136).
        - 'coming_soon' não é vendável mesmo com estoque (ex.: produto 130).
        - 'active' com estoque 0 é tratado como esgotado (ex.: produto 96).
        """
        if row["status"] == "discontinued":
            return "descontinuado (não faz mais parte do catálogo)", False
        if row["status"] == "coming_soon":
            return "em breve (ainda não disponível para venda)", False
        if row["stock_quantity"] <= 0:
            return "esgotado no momento", False
        if row["stock_quantity"] <= 2:
            return f"disponível (últimas {int(row['stock_quantity'])} unidades)", True
        return "disponível", True

    def _produto_para_dict(self, row, detalhado: bool = False) -> dict:
        rotulo, pode_comprar = self._disponibilidade(row)
        preco = float(row["price_brl"])
        item = {
            "id": int(row["product_id"]),
            "nome": row["name"],
            "categoria": row["categoria"],
            "preco": brl(preco),
            "disponibilidade": rotulo,
            "pode_comprar": pode_comprar,
        }

        if pd.notna(row.get("discount_percent")):
            desconto = float(row["discount_percent"])
            preco_final = round(preco * (1 - desconto / 100), 2)
            item["promocao"] = {
                "nome": row["promocao"],
                "desconto": f"{desconto:.0f}%",
                "preco_original": brl(preco),
                "preco_promocional": brl(preco_final),
                "regra": "desconto de PIX não se aplica sobre preço promocional",
            }
        else:
            preco_final = preco
            item["preco_no_pix"] = brl(round(preco * (1 - DESCONTO_PIX), 2))

        item["parcelamento"] = simular_parcelamento(preco_final)["texto"]

        if detalhado:
            item["descricao"] = row["description"]
            item["especificacoes"] = row["specs"]
        return item

    def buscar_produtos(
        self,
        termo: str | None = None,
        categoria: str | None = None,
        preco_min: float | None = None,
        preco_max: float | None = None,
        somente_disponiveis: bool = True,
        limite: int = 8,
    ) -> dict:
        """Busca no catálogo por texto livre, categoria e faixa de preço.

        O filtro de preço considera o preço final (com promoção, se houver).
        """
        df = self.produtos.copy()

        if categoria:
            cat_id = self._resolver_categoria(categoria)
            if cat_id is None:
                return {
                    "encontrados": 0,
                    "produtos": [],
                    "aviso": f"Categoria '{categoria}' não encontrada.",
                    "categorias_existentes": self.categorias["name"].tolist(),
                }
            df = df[df["category_id"] == cat_id]

        if termo:
            tokens = [t for t in normalizar(termo).split() if t not in STOPWORDS]
            if tokens:
                df = df[df["texto_busca"].apply(lambda txt: self._casa_tokens(tokens, txt))]

        df["preco_final"] = df["price_brl"] * (1 - df["discount_percent"].fillna(0) / 100)
        if preco_min is not None:
            df = df[df["preco_final"] >= preco_min]
        if preco_max is not None:
            df = df[df["preco_final"] <= preco_max]

        produtos = [self._produto_para_dict(r) for _, r in df.sort_values("preco_final").iterrows()]
        indisponiveis = [p for p in produtos if not p["pode_comprar"]]
        if somente_disponiveis:
            produtos = [p for p in produtos if p["pode_comprar"]]

        resultado = {"encontrados": len(produtos), "produtos": produtos[:limite]}
        if not produtos:
            resultado["aviso"] = "Nenhum produto disponível com esses critérios no momento."
        if len(produtos) > limite:
            resultado["aviso"] = f"Mostrando {limite} de {len(produtos)}. Refine a busca se necessário."
        if somente_disponiveis and indisponiveis:
            resultado["tambem_existem_indisponiveis"] = len(indisponiveis)
        return resultado

    @staticmethod
    def _casa_tokens(tokens: list[str], texto: str) -> bool:
        """Todos os termos precisam aparecer (com tolerância a erro de digitação)."""
        palavras = texto.split()
        for t in tokens:
            if t in texto:
                continue
            if len(t) >= 4 and process.extractOne(t, palavras, scorer=fuzz.ratio, score_cutoff=80):
                continue
            return False
        return True

    def _resolver_categoria(self, categoria: str) -> int | None:
        alvo = normalizar(categoria)
        opcoes = {
            int(r.category_id): normalizar(f"{r.name} {APELIDOS_CATEGORIA.get(r.category_id, '')}")
            for r in self.categorias.itertuples()
        }
        melhor = process.extractOne(alvo, opcoes, scorer=fuzz.partial_token_set_ratio, score_cutoff=80)
        return melhor[2] if melhor else None

    def obter_produto(self, nome_ou_id: str) -> dict:
        """Busca um produto específico por ID ou por nome aproximado."""
        texto = str(nome_ou_id).strip()
        if texto.isdigit():
            linhas = self.produtos[self.produtos["product_id"] == int(texto)]
            if linhas.empty:
                return {"encontrado": False, "mensagem": f"Produto {texto} não existe no catálogo."}
            row = linhas.iloc[0]
        else:
            matches = process.extract(
                normalizar(texto), self.produtos["nome_norm"], scorer=_similaridade_nome, limit=3
            )
            if not matches or matches[0][1] < 75:
                return {
                    "encontrado": False,
                    "mensagem": f"Nenhum produto parecido com '{texto}' no catálogo.",
                    "lembrete": "A loja vende apenas instrumentos musicais (sem acessórios).",
                }
            row = self.produtos.iloc[matches[0][2]]
            # Empate ou quase empate (ex.: "Martin D28" -> D-28 e D-28E): o agente deve confirmar.
            parecidos = [
                self.produtos.iloc[m[2]]["name"] for m in matches[1:] if m[1] >= matches[0][1] - 3
            ]

        produto = self._produto_para_dict(row, detalhado=True)
        resultado = {"encontrado": True, "produto": produto}
        if not texto.isdigit() and parecidos:
            resultado["outros_parecidos"] = parecidos
            resultado["instrucao"] = "Nome ambíguo: confirme com o cliente qual modelo ele procura."
        if not produto["pode_comprar"]:
            resultado["alternativas_disponiveis"] = self._alternativas(row)
        return resultado

    def _alternativas(self, row, n: int = 3) -> list[dict]:
        """Produtos da mesma categoria, disponíveis e com preço próximo (seção 7.3)."""
        df = self.produtos[
            (self.produtos["category_id"] == row["category_id"])
            & (self.produtos["product_id"] != row["product_id"])
            & (self.produtos["status"] == "active")
            & (self.produtos["stock_quantity"] > 0)
        ].copy()
        df["distancia"] = (df["price_brl"] - row["price_brl"]).abs()
        return [self._produto_para_dict(r) for _, r in df.nsmallest(n, "distancia").iterrows()]

    def listar_categorias(self) -> list[dict]:
        vendaveis = self.produtos[(self.produtos["status"] == "active") & (self.produtos["stock_quantity"] > 0)]
        contagem = vendaveis.groupby("category_id").size()
        return [
            {
                "categoria": r.name,
                "descricao": r.description,
                "produtos_disponiveis": int(contagem.get(r.category_id, 0)),
            }
            for r in self.categorias.itertuples()
        ]

    # ---------------------------- pedidos ---------------------------------

    def _clientes_por_contato(self, contato: str) -> pd.DataFrame:
        contato = str(contato).strip()
        if "@" in contato:
            return self.clientes[self.clientes["email"].str.lower() == contato.lower()]
        digitos = _so_digitos(contato)
        if len(digitos) < 8:
            return self.clientes.iloc[0:0]
        return self.clientes[self.clientes["phone"].apply(lambda p: _so_digitos(p).endswith(digitos[-8:]))]

    def consultar_pedidos(self, contato: str, numero_pedido: int | None = None) -> dict:
        """Consulta pedidos exigindo verificação de identidade (LGPD).

        - contato: e-mail ou telefone cadastrado do cliente (obrigatório).
        - numero_pedido: opcional; sem ele, lista os pedidos do cliente.
        A resposta nunca confirma se um pedido ou contato existe quando a
        verificação falha, para não expor dados de terceiros.
        """
        clientes = self._clientes_por_contato(contato)
        falha = {
            "verificado": False,
            "mensagem": "Não foi possível localizar pedido com esses dados. "
                        "Peça ao cliente para conferir o número do pedido e o e-mail ou telefone cadastrado.",
        }
        if clientes.empty:
            return falha

        if numero_pedido is None and len(clientes) > 1:
            # Caso real nos dados: clientes 11 e 43 compartilham o mesmo e-mail.
            return {
                "verificado": False,
                "mensagem": "Este contato está associado a mais de um cadastro. "
                            "Peça o número do pedido ou o telefone cadastrado para identificar o cliente.",
            }

        ids = set(clientes["customer_id"])
        pedidos = self.pedidos[self.pedidos["customer_id"].isin(ids)]
        if numero_pedido is not None:
            pedidos = pedidos[pedidos["order_id"] == int(numero_pedido)]
            if pedidos.empty:
                return falha

        cliente = self.clientes[self.clientes["customer_id"] == pedidos.iloc[0]["customer_id"]].iloc[0] \
            if not pedidos.empty else clientes.iloc[0]
        return {
            "verificado": True,
            "cliente": cliente["name"].split()[0],
            "data_de_hoje": self.hoje.strftime("%d/%m/%Y"),
            "pedidos": [self._pedido_para_dict(p) for _, p in pedidos.sort_values("order_date").iterrows()],
        }

    def _pedido_para_dict(self, p) -> dict:
        itens = self.itens[self.itens["order_id"] == p["order_id"]].merge(
            self.produtos[["product_id", "name", "price_brl"]], on="product_id", how="left"
        )
        data_pedido = date.fromisoformat(p["order_date"])
        pedido = {
            "numero": int(p["order_id"]),
            "data": data_pedido.strftime("%d/%m/%Y"),
            "status": STATUS_PEDIDO.get(p["status"], p["status"]),
            "itens": [
                {"produto": i["name"], "quantidade": int(i["quantity"])} for _, i in itens.iterrows()
            ],
            "total": brl(float(p["total_brl"])),
            "pagamento": _forma_pagamento(p["payment_method"]),
        }
        if pd.notna(p["tracking_code"]):
            pedido["codigo_rastreio"] = p["tracking_code"]
        if pd.notna(p["notes"]):
            pedido["observacao"] = p["notes"]

        alertas: list[str] = []
        if pd.notna(p["estimated_delivery"]):
            entrega = date.fromisoformat(p["estimated_delivery"])
            pedido["entrega_prevista"] = entrega.strftime("%d/%m/%Y")

            if p["status"] == "shipped" and self.hoje > entrega:
                alertas.append(
                    f"Entrega prevista para {entrega:%d/%m/%Y} já passou e o pedido ainda consta como enviado. "
                    "Pedir desculpas e oferecer encaminhamento a um atendente."
                )

            if p["status"] == "delivered":
                # Suposição: não há data real de recebimento; usamos a entrega prevista.
                dias_recebido = (self.hoje - entrega).days
                dias_compra = (self.hoje - data_pedido).days
                pedido["prazos"] = {
                    "base_de_calculo": "data de entrega prevista (não há data real de recebimento no sistema)",
                    "dias_desde_recebimento": dias_recebido,
                    "arrependimento_7_dias": "dentro do prazo" if dias_recebido <= 7 else "prazo encerrado",
                    "troca_por_defeito_30_dias": "dentro do prazo" if dias_compra <= 30 else "prazo encerrado",
                    "garantia_legal_90_dias": "vigente" if dias_recebido <= 90 else "encerrada (acionar garantia do fabricante)",
                }

        if p["status"] in ("pending", "confirmed") and (self.hoje - data_pedido).days > 15:
            alertas.append(
                f"Pedido está como '{p['status']}' há {(self.hoje - data_pedido).days} dias. "
                "Não prometer prazo; oferecer encaminhamento a um atendente."
            )

        soma_itens = float((itens["quantity"] * itens["price_brl"]).sum())
        if abs(soma_itens - float(p["total_brl"])) > 0.01:
            alertas.append(
                "Total registrado difere da soma dos preços atuais dos itens (pode ter havido desconto na época). "
                "Informar o total registrado; se o cliente questionar valores, encaminhar a um atendente."
            )

        if alertas:
            pedido["alertas_para_o_atendente"] = alertas
        return pedido
