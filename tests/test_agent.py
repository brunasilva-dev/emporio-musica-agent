"""Testes do loop do agente com um LLM falso (sem chamadas de API).

Validam a mecânica: execução de ferramentas, devolução dos resultados ao
modelo, preservação da thought signature do Gemini e fallback de provedor.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import APIStatusError
from openai.types.chat import ChatCompletionMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import emporio.agent as agente_mod  # noqa: E402
from emporio.agent import Agente  # noqa: E402
from emporio.config import Provedor  # noqa: E402


def _msg_ferramenta(nome, argumentos, assinatura=None):
    chamada = {"id": "call_1", "type": "function", "function": {"name": nome, "arguments": json.dumps(argumentos)}}
    if assinatura:
        chamada["extra_content"] = {"google": {"thought_signature": assinatura}}
    return ChatCompletionMessage.model_validate({"role": "assistant", "content": None, "tool_calls": [chamada]})


def _msg_texto(texto):
    return ChatCompletionMessage.model_validate({"role": "assistant", "content": texto})


class ClienteFalso:
    """Imita client.chat.completions.create devolvendo respostas pré-definidas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.chamadas.append(kwargs)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=r)])


try:  # versões novas do SDK da OpenAI usam httpx2; as antigas, httpx
    import httpx2 as _http
except ImportError:
    import httpx as _http


def _erro(status):
    req = _http.Request("POST", "https://exemplo")
    return APIStatusError("erro", response=_http.Response(status, request=req), body=None)


GEMINI = Provedor("gemini", "https://x", "k", "gemini-teste")
GROQ = Provedor("groq", "https://y", "k", "groq-teste")


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr(agente_mod, "ESPERA_BASE_S", 0)


def test_executa_ferramenta_e_responde():
    cliente = ClienteFalso([
        _msg_ferramenta("obter_produto", {"nome_ou_id": "Takamine GD20"}, assinatura="sig123"),
        _msg_texto("O Takamine GD20 custa R$ 2.199,00."),
    ])
    agente = Agente(provedores=[GEMINI], clientes={"gemini": cliente})
    r = agente.responder("Quanto custa o Takamine GD20?")

    assert r.texto == "O Takamine GD20 custa R$ 2.199,00."
    assert r.ferramentas == [{"ferramenta": "obter_produto", "argumentos": {"nome_ou_id": "Takamine GD20"}}]

    segunda = cliente.chamadas[1]["messages"]
    resultado_tool = next(m for m in segunda if m["role"] == "tool")
    assert "2.199,00" in resultado_tool["content"]  # resultado real da ferramenta voltou ao modelo
    chamada = next(m for m in segunda if m.get("tool_calls"))["tool_calls"][0]
    assert chamada["extra_content"]["google"]["thought_signature"] == "sig123"  # assinatura preservada


def test_fallback_para_outro_provedor():
    gemini = ClienteFalso([_erro(503), _erro(503)])
    groq = ClienteFalso([_msg_texto("Olá! Como posso ajudar?")])
    agente = Agente(provedores=[GEMINI, GROQ], clientes={"gemini": gemini, "groq": groq})
    r = agente.responder("oi")
    assert r.provedor == "groq" and len(gemini.chamadas) == 2


def test_circuit_breaker_pula_provedor_que_falhou():
    gemini = ClienteFalso([_erro(503), _erro(503)])
    groq = ClienteFalso([_msg_texto("Oi!"), _msg_texto("Tudo certo!")])
    agente = Agente(provedores=[GEMINI, GROQ], clientes={"gemini": gemini, "groq": groq})
    agente.responder("oi")
    agente.responder("tudo bem?")
    assert len(gemini.chamadas) == 2  # na segunda mensagem o Gemini nem foi chamado


def test_erro_nao_temporario_pula_direto_para_fallback():
    gemini = ClienteFalso([_erro(400)])
    groq = ClienteFalso([_msg_texto("Oi!")])
    agente = Agente(provedores=[GEMINI, GROQ], clientes={"gemini": gemini, "groq": groq})
    assert agente.responder("oi").provedor == "groq"
    assert len(gemini.chamadas) == 1


def test_todos_provedores_fora_responde_com_educacao():
    gemini = ClienteFalso([_erro(503)] * 2)
    agente = Agente(provedores=[GEMINI], clientes={"gemini": gemini})
    assert "instabilidade" in agente.responder("oi").texto


def test_assinatura_removida_ao_enviar_para_groq():
    agente = Agente(provedores=[GEMINI], clientes={"gemini": ClienteFalso([])})
    agente.historico = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "s"}}}]}]
    assert "extra_content" not in agente._adaptar_historico("groq")[0]["tool_calls"][0]
    assert "extra_content" in agente.historico[0]["tool_calls"][0]  # original intacto


def test_historico_persistido(tmp_path):
    cliente = ClienteFalso([_msg_texto("Oi!")])
    agente = Agente(provedores=[GEMINI], clientes={"gemini": cliente})
    agente.responder("oi")
    arquivo = tmp_path / "sessao.json"
    agente.salvar(arquivo)

    novo = Agente(provedores=[GEMINI], clientes={"gemini": ClienteFalso([])})
    novo.carregar(arquivo)
    assert novo.historico == agente.historico
