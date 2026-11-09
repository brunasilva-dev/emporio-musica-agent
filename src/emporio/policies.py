"""Manual de políticas da Empório da Música.

Estratégia de retrieval: o manual tem só 8 páginas e uma estrutura clara de
seções numeradas. Em vez de RAG vetorial (chunking + embeddings + busca por
similaridade), o PDF é dividido pelas seções do próprio documento e o LLM
escolhe qual seção consultar a partir de uma lista fechada (enum). Isso evita
erros de recuperação (chunk errado, seção cortada ao meio) e não exige
nenhum serviço extra de embeddings.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfReader

PDF_PATH = Path(__file__).resolve().parents[2] / "data" / "politicas_da_loja.pdf"
FUSO_LOJA = ZoneInfo("America/Campo_Grande")  # UTC-4, uma hora a menos que Brasília

# Número da seção no PDF -> (chave usada pelo LLM, descrição para o LLM escolher)
SECOES = {
    1: ("sobre_a_loja", "endereço, contato, o que a loja vende"),
    2: ("horario_de_funcionamento", "horários"),
    3: ("formas_de_pagamento", "PIX, cartão, boleto, parcelamento"),
    4: ("trocas_e_devolucoes", "arrependimento, defeito, preferência"),
    5: ("frete_e_entregas", "frete, prazos, rastreio"),
    6: ("promocoes", "campanhas e regras"),
    7: ("diretrizes_de_atendimento", "escopo, esgotados, reclamações"),
    8: ("garantia", "legal e de fabricante"),
    9: ("privacidade_lgpd", "dados pessoais, exclusão"),
}

# Notas de curadoria: inconsistências encontradas no PDF e a interpretação adotada.
# Ficam junto do texto para o agente responder de forma consistente.
NOTAS_DE_CURADORIA = {
    "sobre_a_loja": (
        "O manual traz dois telefones: (67) 3341-4444 (capa e tabela de dados da empresa, como "
        "'Telefone / WhatsApp') e (67) 3321-4500 (seção 7). Use (67) 3341-4444 como contato oficial. "
        "O e-mail correto é contato@emporiodamusica.com.br (a versão com acento na tabela é erro de digitação)."
    ),
    "formas_de_pagamento": (
        "A tabela diz 'parcela mínima de R$ 100', mas a seção 3.1 detalha faixas (até 3x: mínimo R$ 50; "
        "4x a 6x: mínimo R$ 80; 7x a 12x: mínimo R$ 100). Vale a seção 3.1, que é mais específica. "
        "O parcelamento de cada produto já vem calculado nas ferramentas de produto."
    ),
    "promocoes": (
        "O calendário acima é apenas a programação geral de campanhas. Só vale desconto que estiver ATIVO "
        "no sistema (ferramentas de produto). Nunca prometa desconto de campanha que não esteja ativa."
    ),
    "diretrizes_de_atendimento": (
        "Para contato, use o telefone oficial (67) 3341-4444 (ver nota em 'sobre_a_loja')."
    ),
}

HORARIOS = {  # weekday() -> (abertura, fechamento) em horas; None = fechado
    0: (9, 18), 1: (9, 18), 2: (9, 18), 3: (9, 18), 4: (9, 18),
    5: (9, 13),
    6: None,
}
NOMES_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def _limpar(texto: str) -> str:
    """Remove cabeçalhos/rodapés de página e espaços excessivos do modo layout."""
    linhas = []
    for linha in texto.splitlines():
        s = linha.strip()
        if re.fullmatch(r"Página \d+", s) or s == "Empório da Música Manual de Políticas e Procedimentos":
            continue
        linhas.append(re.sub(r" {3,}", "  |  ", s) if s else "")
    texto = "\n".join(linhas)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


@lru_cache(maxsize=1)
def carregar_secoes(pdf_path: Path = PDF_PATH) -> dict[str, str]:
    """Lê o PDF e devolve {chave_da_secao: texto}."""
    leitor = PdfReader(str(pdf_path))
    texto = _limpar("\n".join(p.extract_text(extraction_mode="layout") for p in leitor.pages))

    # Títulos de seção de primeiro nível ("1. Sobre...", "2. Horário...") no início da linha.
    # Só aceitamos títulos em ordem crescente: listas numeradas dentro de uma seção
    # (ex.: "1. Saudação" no fluxo de atendimento da seção 7) não viram seções novas.
    secoes: dict[str, str] = {}
    esperado, chave_atual, buffer = 1, None, []
    for linha in texto.splitlines():
        m = re.match(r"^(\d{1,2})\.\s+\S", linha)
        if m and int(m.group(1)) == esperado:
            if chave_atual:
                secoes[chave_atual] = "\n".join(buffer).strip()
            numero = int(m.group(1))
            chave_atual = SECOES.get(numero, (None,))[0]
            buffer, esperado = [linha], numero + 1
        elif chave_atual:
            buffer.append(linha)
    if chave_atual:
        secoes[chave_atual] = "\n".join(buffer).strip()
    return secoes


def consultar_politica(secao: str) -> dict:
    """Retorna o texto de uma seção do manual (com notas de curadoria, se houver)."""
    secoes = carregar_secoes()
    if secao not in secoes:
        return {"erro": f"Seção '{secao}' não existe.", "secoes_disponiveis": list(secoes)}
    resposta = {"secao": secao, "texto": secoes[secao]}
    if secao in NOTAS_DE_CURADORIA:
        resposta["nota_de_curadoria"] = NOTAS_DE_CURADORIA[secao]
    return resposta


def situacao_da_loja(agora: datetime | None = None) -> str:
    """Diz se a loja está aberta agora (horário de Campo Grande) e quando abre/fecha.

    Limitação conhecida: o manual não lista os feriados, então feriados não são considerados.
    """
    agora = (agora or datetime.now(FUSO_LOJA)).astimezone(FUSO_LOJA)
    base = f"Agora são {agora:%H:%M} de {NOMES_DIAS[agora.weekday()]}, {agora:%d/%m/%Y} (horário de Campo Grande/MS)."

    horario = HORARIOS[agora.weekday()]
    if horario and horario[0] <= agora.hour < horario[1]:
        return f"{base} A loja está ABERTA e fecha às {horario[1]}h."

    # Procura a próxima abertura
    for dias in range(0, 8):
        dia = agora + timedelta(days=dias)
        h = HORARIOS[dia.weekday()]
        if h and (dias > 0 or agora.hour < h[0]):
            quando = "hoje" if dias == 0 else ("amanhã" if dias == 1 else NOMES_DIAS[dia.weekday()])
            return f"{base} A loja está FECHADA. Reabre {quando} às {h[0]}h."
    return f"{base} A loja está FECHADA."
