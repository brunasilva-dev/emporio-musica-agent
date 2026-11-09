"""Testes da camada de dados (determinísticos, não usam LLM)."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emporio.data import StoreData, brl, simular_parcelamento  # noqa: E402


@pytest.fixture(scope="module")
def loja():
    return StoreData(hoje=date(2026, 11, 9))


def test_formatacao_brl():
    assert brl(2199) == "R$ 2.199,00"
    assert brl(11499.5) == "R$ 11.499,50"


def test_parcelamento_respeita_parcela_minima():
    assert simular_parcelamento(2199)["parcelas"] == 12   # 12x de 183,25 (>= 100)
    assert simular_parcelamento(799.9)["parcelas"] == 7   # 7x de 114,27 (>= 100)
    assert simular_parcelamento(159.9)["parcelas"] == 3   # 3x de 53,30 (>= 50)
    assert simular_parcelamento(30)["parcelas"] == 1


def test_busca_por_nome_com_erro_de_digitacao(loja):
    r = loja.obter_produto("takamini gd 20")
    assert r["encontrado"] and r["produto"]["nome"].startswith("Takamine GD20")
    assert r["produto"]["preco"] == "R$ 2.199,00"


def test_preco_pix_quando_sem_promocao(loja):
    p = loja.obter_produto("Takamine GD20")["produto"]
    assert p["preco_no_pix"] == "R$ 2.089,05"
    assert "promocao" not in p


def test_promocao_ativa_nao_acumula_com_pix(loja):
    p = loja.obter_produto("Ohana CK-20")["produto"]
    assert p["promocao"]["preco_promocional"] == "R$ 439,20"
    assert "preco_no_pix" not in p


def test_promocao_inativa_e_ignorada(loja):
    # Produto 102 só tem promoção de Black Friday inativa.
    p = loja.obter_produto("102")["produto"]
    assert "promocao" not in p


def test_esgotado_sugere_alternativas(loja):
    r = loja.obter_produto("Giannini GF-3D")
    assert not r["produto"]["pode_comprar"]
    assert len(r["alternativas_disponiveis"]) > 0
    assert all(a["pode_comprar"] for a in r["alternativas_disponiveis"])


def test_descontinuado_com_estoque_nao_e_vendavel(loja):
    p = loja.obter_produto("136")["produto"]
    assert not p["pode_comprar"] and "descontinuado" in p["disponibilidade"]


def test_coming_soon_nao_e_vendavel(loja):
    p = loja.obter_produto("130")["produto"]
    assert not p["pode_comprar"] and "em breve" in p["disponibilidade"]


def test_nome_ambiguo_pede_confirmacao(loja):
    r = loja.obter_produto("Martin D28")
    assert "outros_parecidos" in r


def test_acessorio_nao_encontrado(loja):
    assert not loja.obter_produto("cabo de guitarra")["encontrado"]


def test_busca_violoes_ate_1000(loja):
    r = loja.buscar_produtos(categoria="violão", preco_max=1000, limite=50)
    assert r["encontrados"] > 0
    assert all(p["categoria"] == "Violões" and p["pode_comprar"] for p in r["produtos"])


def test_categoria_inexistente(loja):
    r = loja.buscar_produtos(categoria="amplificador")
    assert r["encontrados"] == 0 and "categorias_existentes" in r


def test_pedido_exige_contato_correto(loja):
    assert loja.consultar_pedidos("pedro.oliveira@jmail.com", 1)["verificado"]
    assert not loja.consultar_pedidos("outra.pessoa@jmail.com", 1)["verificado"]
    # Contato certo, mas pedido de outra pessoa: não pode vazar.
    assert not loja.consultar_pedidos("pedro.oliveira@jmail.com", 8)["verificado"]


def test_pedido_por_telefone(loja):
    r = loja.consultar_pedidos("(67) 99654-7821", 8)
    assert r["verificado"] and r["pedidos"][0]["codigo_rastreio"] == "BRJL5544332BR"


def test_email_compartilhado_pede_mais_dados(loja):
    # Clientes 11 e 43 têm o mesmo e-mail nos dados.
    assert not loja.consultar_pedidos("bruno.martins@jmail.com")["verificado"]
    assert loja.consultar_pedidos("bruno.martins@jmail.com", 10)["verificado"]


def test_entrega_atrasada_gera_alerta(loja):
    pedido = loja.consultar_pedidos("(67) 99654-7821", 8)["pedidos"][0]
    assert "alertas_para_o_atendente" in pedido


def test_prazo_de_arrependimento_encerrado(loja):
    pedido = loja.consultar_pedidos("pedro.oliveira@jmail.com", 1)["pedidos"][0]
    assert pedido["prazos"]["arrependimento_7_dias"] == "prazo encerrado"


def test_prazo_de_arrependimento_dentro():
    # Simulando "hoje" 3 dias após a entrega prevista do pedido 1 (25/10/2025).
    loja = StoreData(hoje=date(2025, 10, 28))
    pedido = loja.consultar_pedidos("pedro.oliveira@jmail.com", 1)["pedidos"][0]
    assert pedido["prazos"]["arrependimento_7_dias"] == "dentro do prazo"


def test_divergencia_de_total_gera_alerta(loja):
    pedido = loja.consultar_pedidos("isabela.moreira@jmail.com", 3)["pedidos"][0]
    assert any("Total registrado" in a for a in pedido["alertas_para_o_atendente"])
