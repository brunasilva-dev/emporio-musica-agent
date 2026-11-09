"""Configuração dos provedores de LLM a partir do arquivo .env.

Todos os provedores são acessados pelo SDK da OpenAI apontando para endpoints
compatíveis (Gemini e Groq oferecem esse formato). Trocar de provedor é só
mudar o .env, sem mexer no código.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

PADROES = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.8-flash"),
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
}


@dataclass(frozen=True)
class Provedor:
    nome: str
    base_url: str
    api_key: str
    modelo: str


def carregar_provedores() -> list[Provedor]:
    """Provedor principal (LLM_PROVIDER) primeiro; os demais com chave viram fallback."""
    principal = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    ordem = [principal] + [p for p in PADROES if p != principal]

    provedores = []
    for nome in ordem:
        chave = os.getenv(f"{nome.upper()}_API_KEY", "").strip()
        if not chave or nome not in PADROES:
            continue
        url_padrao, modelo_padrao = PADROES[nome]
        provedores.append(
            Provedor(
                nome=nome,
                base_url=os.getenv(f"{nome.upper()}_BASE_URL", "").strip() or url_padrao,
                api_key=chave,
                modelo=os.getenv(f"{nome.upper()}_MODEL", "").strip() or modelo_padrao,
            )
        )

    if not provedores:
        raise RuntimeError(
            "Nenhuma chave de LLM configurada. Copie .env.example para .env e preencha "
            "GEMINI_API_KEY e/ou GROQ_API_KEY."
        )
    return provedores
