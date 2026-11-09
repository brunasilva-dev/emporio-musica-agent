"""Testes do módulo de políticas (determinísticos, não usam LLM)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emporio.policies import FUSO_LOJA, SECOES, carregar_secoes, consultar_politica, situacao_da_loja  # noqa: E402


def _em(texto: str) -> datetime:
    return datetime.fromisoformat(texto).replace(tzinfo=FUSO_LOJA)


def test_todas_as_secoes_foram_extraidas():
    secoes = carregar_secoes()
    assert set(secoes) == {chave for chave, _ in SECOES.values()}


def test_lista_numerada_nao_quebra_secoes():
    # O fluxo "1. Saudação ... 5. Fechamento" da seção 7 não pode virar seção nova.
    assert carregar_secoes()["sobre_a_loja"].startswith("1. Sobre a Empório da Música")
    assert "Fechamento" in carregar_secoes()["diretrizes_de_atendimento"]


def test_conteudo_das_secoes():
    assert "7 (sete) dias" in consultar_politica("trocas_e_devolucoes")["texto"]
    assert "09:00" in consultar_politica("horario_de_funcionamento")["texto"]
    assert "Rua 14 de Maio" in consultar_politica("sobre_a_loja")["texto"]


def test_notas_de_curadoria():
    assert "3341-4444" in consultar_politica("sobre_a_loja")["nota_de_curadoria"]
    assert "ATIVO" in consultar_politica("promocoes")["nota_de_curadoria"]


def test_secao_inexistente():
    assert "erro" in consultar_politica("cafe_da_manha")


def test_loja_aberta_em_dia_util():
    assert "ABERTA" in situacao_da_loja(_em("2026-11-09 13:10"))


def test_loja_fechada_apos_expediente():
    assert "Reabre amanhã às 9h" in situacao_da_loja(_em("2026-11-09 18:30"))


def test_sabado_fecha_as_13h():
    assert "ABERTA" in situacao_da_loja(_em("2026-11-14 12:59"))
    assert "Reabre segunda-feira" in situacao_da_loja(_em("2026-11-14 13:00"))


def test_domingo_fechado():
    assert "FECHADA" in situacao_da_loja(_em("2026-11-15 10:00"))
