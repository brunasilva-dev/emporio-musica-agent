"""Agente de atendimento: loop de function calling com retry e fallback de provedor.

Fluxo de cada turno:
1. Envia ao LLM o prompt de sistema + histórico + mensagem do cliente + schemas das tools.
2. Se o LLM pedir ferramentas, executa cada uma e devolve os resultados.
3. Repete até o LLM responder em texto (ou atingir o limite de passos).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .config import RAIZ, Provedor, carregar_provedores
from .prompts import montar_prompt_sistema
from .tools import TOOLS, executar_ferramenta

MAX_PASSOS = 6            # máximo de rodadas de ferramentas por mensagem do cliente
TENTATIVAS_POR_PROVEDOR = 2
ESPERA_BASE_S = 2
TIMEOUT_S = 20
ESPERA_MAX_429_S = 30     # se o provedor pedir para esperar até isso (rate limit), esperamos
PAUSA_PROVEDOR_S = 120    # circuit breaker: provedor que falhou fica de fora por 2 minutos
ARQUIVO_ERROS = RAIZ / "historico" / "erros.log"

MENSAGEM_INSTABILIDADE = (
    "Desculpa, estou com uma instabilidade técnica agora e não consegui consultar o sistema. "
    "Pode tentar de novo em instantes? Se preferir, fale com a equipe pelo (67) 3341-4444."
)


@dataclass
class Resposta:
    texto: str
    ferramentas: list[dict] = field(default_factory=list)
    provedor: str | None = None


class Agente:
    def __init__(self, provedores: list[Provedor] | None = None, clientes: dict | None = None):
        self.provedores = provedores or carregar_provedores()
        # `clientes` pode ser injetado nos testes (cliente falso, sem chamar API).
        self.clientes = clientes or {
            p.nome: OpenAI(api_key=p.api_key, base_url=p.base_url, max_retries=0, timeout=TIMEOUT_S)
            for p in self.provedores
        }
        self.historico: list[dict] = []
        self.transcricao: list[dict] = []  # versão legível, usada para exportar conversas
        self.erros: list[str] = []         # erros de API do último turno (exibidos no modo debug)
        self._pausado_ate: dict[str, float] = {}  # circuit breaker por provedor

    # ------------------------------------------------------------------ API

    def responder(self, mensagem: str) -> Resposta:
        self.historico.append({"role": "user", "content": mensagem})
        self.transcricao.append({"autor": "cliente", "texto": mensagem})
        self.erros = []
        ferramentas_usadas: list[dict] = []

        for _ in range(MAX_PASSOS):
            resultado = self._chamar_llm()
            if resultado is None:
                return self._finalizar(MENSAGEM_INSTABILIDADE, ferramentas_usadas, None)
            msg, provedor = resultado

            if msg.tool_calls:
                self.historico.append(self._mensagem_assistente(msg))
                for chamada in msg.tool_calls:
                    nome = chamada.function.name
                    try:
                        argumentos = json.loads(chamada.function.arguments or "{}")
                    except json.JSONDecodeError:
                        argumentos = {}
                    saida = executar_ferramenta(nome, argumentos)
                    ferramentas_usadas.append({"ferramenta": nome, "argumentos": argumentos})
                    self.historico.append({
                        "role": "tool",
                        "tool_call_id": chamada.id,
                        "name": nome,  # o Gemini usa o nome para montar a functionResponse
                        "content": json.dumps(saida, ensure_ascii=False, separators=(",", ":")),
                    })
                continue

            texto = (msg.content or "").strip() or "Desculpa, não entendi. Pode reformular?"
            self.historico.append({"role": "assistant", "content": texto})
            return self._finalizar(texto, ferramentas_usadas, provedor)

        texto = "Essa consulta ficou mais complexa do que consigo resolver aqui. Quer que eu encaminhe para a equipe?"
        self.historico.append({"role": "assistant", "content": texto})
        return self._finalizar(texto, ferramentas_usadas, None)

    def reiniciar(self) -> None:
        self.historico.clear()
        self.transcricao.clear()

    def salvar(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        dados = {"historico": self.historico, "transcricao": self.transcricao}
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    def carregar(self, caminho: Path) -> None:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        self.historico = dados.get("historico", [])
        self.transcricao = dados.get("transcricao", [])

    # -------------------------------------------------------------- interno

    def _finalizar(self, texto: str, ferramentas: list[dict], provedor: str | None) -> Resposta:
        self.transcricao.append({"autor": "duda", "texto": texto, "ferramentas": ferramentas})
        return Resposta(texto=texto, ferramentas=ferramentas, provedor=provedor)

    def _chamar_llm(self):
        """Tenta cada provedor com retry exponencial em erros temporários (429, 5xx, timeout).

        Circuit breaker: se um provedor esgota as tentativas, ele fica pausado por
        PAUSA_PROVEDOR_S e as próximas chamadas vão direto para o fallback, sem esperar
        timeouts repetidos. Se todos estiverem pausados, tenta mesmo assim.
        """
        agora = time.monotonic()
        ativos = [p for p in self.provedores if self._pausado_ate.get(p.nome, 0) <= agora]
        for provedor in ativos or self.provedores:
            mensagens = [{"role": "system", "content": montar_prompt_sistema()}]
            mensagens += self._adaptar_historico(provedor.nome, self._historico_compacto())
            for tentativa in range(TENTATIVAS_POR_PROVEDOR):
                try:
                    resposta = self.clientes[provedor.nome].chat.completions.create(
                        model=provedor.modelo,
                        messages=mensagens,
                        tools=TOOLS,
                        temperature=0.3,
                    )
                    self._pausado_ate.pop(provedor.nome, None)
                    return resposta.choices[0].message, provedor.nome
                except (APIConnectionError, APITimeoutError) as e:
                    self._registrar_erro(provedor.nome, tentativa, type(e).__name__, str(e))
                except APIStatusError as e:
                    self._registrar_erro(provedor.nome, tentativa, f"HTTP {e.status_code}", str(e))
                    if e.status_code not in (429, 500, 502, 503, 504):
                        break  # erro não temporário (ex.: 400/401): vai direto para o próximo provedor
                    espera = self._espera_sugerida(e)
                    if espera is not None:
                        if espera > ESPERA_MAX_429_S:
                            break  # cota longa (ex.: diária): não adianta esperar, vai para o fallback
                        if tentativa < TENTATIVAS_POR_PROVEDOR - 1:
                            time.sleep(espera + 0.5)
                        continue
                if tentativa < TENTATIVAS_POR_PROVEDOR - 1:
                    time.sleep(ESPERA_BASE_S * (2 ** tentativa))
            self._pausado_ate[provedor.nome] = time.monotonic() + PAUSA_PROVEDOR_S
        return None

    @staticmethod
    def _espera_sugerida(erro: APIStatusError) -> float | None:
        """Tempo de espera pedido pelo provedor em erros 429 (header Retry-After ou texto do erro)."""
        if erro.status_code != 429:
            return None
        cabecalho = erro.response.headers.get("retry-after") if erro.response is not None else None
        try:
            if cabecalho:
                return float(cabecalho)
        except ValueError:
            pass
        m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(erro))
        if m:
            return int(m.group(1) or 0) * 60 + float(m.group(2))
        return None

    def _historico_compacto(self) -> list[dict]:
        """Economia de tokens: turnos anteriores vão só com as falas (cliente e Duda).

        Os resultados brutos das ferramentas ficam apenas no turno atual. O que importava
        deles já está resumido nas respostas que a Duda deu ao cliente.
        """
        ultimo_usuario = max((i for i, m in enumerate(self.historico) if m["role"] == "user"), default=0)
        anteriores = [
            m for m in self.historico[:ultimo_usuario]
            if m["role"] == "user" or (m["role"] == "assistant" and not m.get("tool_calls"))
        ]
        return anteriores + self.historico[ultimo_usuario:]

    def _registrar_erro(self, provedor: str, tentativa: int, tipo: str, detalhe: str) -> None:
        linha = f"{provedor} (tentativa {tentativa + 1}): {tipo} - {detalhe[:400]}"
        self.erros.append(linha)
        ARQUIVO_ERROS.parent.mkdir(exist_ok=True)
        with ARQUIVO_ERROS.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {linha}\n")

    @staticmethod
    def _mensagem_assistente(msg) -> dict:
        """Guarda só os campos necessários da mensagem com tool_calls.

        `extra_content` é mantido porque o Gemini 3 devolve ali a "thought signature",
        que precisa voltar na próxima chamada.
        """
        chamadas = []
        for c in msg.tool_calls:
            dados = c.model_dump(exclude_none=True)
            item = {"id": c.id, "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
            if "extra_content" in dados:
                item["extra_content"] = dados["extra_content"]
            chamadas.append(item)
        mensagem = {"role": "assistant", "tool_calls": chamadas}
        if msg.content:  # conteúdo vazio ("") é rejeitado por alguns provedores
            mensagem["content"] = msg.content
        return mensagem

    def _adaptar_historico(self, provedor: str, historico: list[dict] | None = None) -> list[dict]:
        """Ajusta o histórico ao provedor (necessário quando há fallback no meio da conversa)."""
        adaptado = []
        for m in (self.historico if historico is None else historico):
            if m.get("tool_calls"):
                m = {**m, "tool_calls": [dict(c) for c in m["tool_calls"]]}
                if provedor == "gemini":
                    # Em chamadas paralelas o Gemini só assina a primeira. Se nenhuma tem assinatura,
                    # a mensagem veio de outro provedor (fallback): usamos o marcador documentado.
                    if not any("extra_content" in c for c in m["tool_calls"]):
                        m["tool_calls"][0]["extra_content"] = {
                            "google": {"thought_signature": "skip_thought_signature_validator"}
                        }
                else:
                    for c in m["tool_calls"]:
                        c.pop("extra_content", None)
            adaptado.append(m)
        return adaptado
