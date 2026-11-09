"""Ferramentas (function calling) disponíveis para o agente.

Cada ferramenta tem um schema no formato OpenAI (o LLM decide quando chamar)
e uma função Python que executa a consulta de verdade.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from functools import lru_cache

from .config import RAIZ
from .data import StoreData
from .policies import FUSO_LOJA, SECOES, consultar_politica

ARQUIVO_ENCAMINHAMENTOS = RAIZ / "historico" / "encaminhamentos.jsonl"


@lru_cache(maxsize=1)
def loja() -> StoreData:
    return StoreData()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_produtos",
            "description": (
                "Busca aberta no catálogo (ex.: 'violões até R$ 1000'). Retorna preço, promoção, PIX, "
                "parcelamento e disponibilidade já calculados."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "termo": {"type": "string", "description": "Marca, modelo ou característica (ex.: 'yamaha nylon')."},
                    "categoria": {"type": "string", "description": "Tipo de instrumento (ex.: 'violão', 'ukulele')."},
                    "preco_min": {"type": "number"},
                    "preco_max": {"type": "number"},
                    "somente_disponiveis": {"type": "boolean", "description": "Padrão true; false inclui esgotados."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obter_produto",
            "description": (
                "Detalhes de um produto pelo nome aproximado ou ID. Inclui preço, promoção, parcelamento, "
                "disponibilidade, especificações e alternativas se indisponível."
            ),
            "parameters": {
                "type": "object",
                "properties": {"nome_ou_id": {"type": "string"}},
                "required": ["nome_ou_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_categorias",
            "description": "Categorias da loja e quantidade de produtos disponíveis em cada.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_pedido",
            "description": (
                "Status, itens, rastreio e prazos de troca/devolução de pedidos. Exige e-mail ou telefone "
                "cadastrado informado pelo cliente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contato": {"type": "string"},
                    "numero_pedido": {"type": "integer"},
                },
                "required": ["contato"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_politica",
            "description": (
                "Manual de políticas da loja (regras e informações institucionais). Seções: "
                + "; ".join(f"{chave} ({desc})" for chave, desc in SECOES.values())
            ),
            "parameters": {
                "type": "object",
                "properties": {"secao": {"type": "string", "enum": [chave for chave, _ in SECOES.values()]}},
                "required": ["secao"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "encaminhar_para_atendente",
            "description": (
                "Registra o caso para a equipe humana (reclamação, atraso, divergência de valor, LGPD, "
                "negociação ou pedido para falar com uma pessoa)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string", "enum": ["reclamacao", "atraso_pedido", "divergencia_valor", "lgpd", "negociacao", "pedido_do_cliente", "outro"]},
                    "resumo": {"type": "string"},
                    "contato": {"type": "string"},
                    "numero_pedido": {"type": "integer"},
                },
                "required": ["motivo", "resumo"],
            },
        },
    },
]


def encaminhar_para_atendente(motivo: str, resumo: str, contato: str | None = None, numero_pedido: int | None = None) -> dict:
    protocolo = f"EM-{datetime.now(FUSO_LOJA):%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"
    registro = {
        "protocolo": protocolo,
        "data_hora": datetime.now(FUSO_LOJA).isoformat(timespec="seconds"),
        "motivo": motivo,
        "resumo": resumo,
        "contato": contato,
        "numero_pedido": numero_pedido,
    }
    ARQUIVO_ENCAMINHAMENTOS.parent.mkdir(exist_ok=True)
    with ARQUIVO_ENCAMINHAMENTOS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {
        "registrado": True,
        "protocolo": protocolo,
        "prazo_de_retorno": "até 24 horas úteis (políticas, seção 7.3)",
    }


def executar_ferramenta(nome: str, argumentos: dict) -> dict | list:
    """Executa a ferramenta pedida pelo LLM. Erros viram resposta, não exceção."""
    funcoes = {
        "buscar_produtos": lambda a: loja().buscar_produtos(**a),
        "obter_produto": lambda a: loja().obter_produto(**a),
        "listar_categorias": lambda a: loja().listar_categorias(),
        "consultar_pedido": lambda a: loja().consultar_pedidos(**a),
        "consultar_politica": lambda a: consultar_politica(**a),
        "encaminhar_para_atendente": lambda a: encaminhar_para_atendente(**a),
    }
    if nome not in funcoes:
        return {"erro": f"Ferramenta '{nome}' não existe."}
    try:
        return funcoes[nome](argumentos)
    except Exception as e:  # o agente recebe o erro e pode se corrigir
        return {"erro": f"Falha ao executar {nome}: {e}"}
