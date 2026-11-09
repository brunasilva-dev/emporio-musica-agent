"""Interface de chat no terminal.

Comandos durante a conversa:
  /debug     mostra ou esconde as ferramentas consultadas pelo agente
  /exportar  salva a conversa atual em Markdown na pasta conversas/
  /nova      começa uma conversa nova
  /sair      encerra
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .agent import Agente
from .config import RAIZ

PASTA_HISTORICO = RAIZ / "historico"
PASTA_CONVERSAS = RAIZ / "conversas"


def exportar_markdown(agente: Agente, titulo: str | None = None) -> Path:
    """Gera um .md legível da conversa, incluindo quais ferramentas foram usadas."""
    PASTA_CONVERSAS.mkdir(exist_ok=True)
    titulo = titulo or f"Conversa {datetime.now():%d/%m/%Y %H:%M}"
    linhas = [f"# {titulo}", ""]
    for item in agente.transcricao:
        if item["autor"] == "cliente":
            linhas += [f"**Cliente:** {item['texto']}", ""]
        else:
            for f in item.get("ferramentas", []):
                args = json.dumps(f["argumentos"], ensure_ascii=False)
                linhas.append(f"> 🔧 *Ferramenta consultada:* `{f['ferramenta']}({args})`")
            if item.get("ferramentas"):
                linhas.append("")
            linhas += [f"**Duda:** {item['texto']}", ""]
    nome = "".join(c if c.isalnum() else "_" for c in titulo.lower()).strip("_")[:60]
    caminho = PASTA_CONVERSAS / f"{nome}.md"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat com a Duda, assistente da Empório da Música")
    parser.add_argument("--sessao", default="padrao", help="Nome da sessão (o histórico é salvo e retomado)")
    parser.add_argument("--debug", action="store_true", help="Mostra as ferramentas consultadas")
    args = parser.parse_args()

    console = Console()
    try:
        agente = Agente()
    except RuntimeError as e:  # ex.: nenhuma chave configurada no .env
        console.print(f"[bold red]Erro de configuração:[/] {e}")
        console.print("[dim]Veja a seção 'Como rodar' do README.[/]")
        return
    arquivo_sessao = PASTA_HISTORICO / f"{args.sessao}.json"
    debug = args.debug

    if arquivo_sessao.exists():
        agente.carregar(arquivo_sessao)
        console.print(f"[dim]Sessão '{args.sessao}' retomada ({len(agente.transcricao)} mensagens).[/]")

    provedores = ", ".join(f"{p.nome} ({p.modelo})" for p in agente.provedores)
    console.print(Panel.fit(
        "[bold]Empório da Música[/] - Sua música começa aqui.\n"
        f"[dim]Modelo: {provedores}\n"
        "Comandos: /debug  /exportar <título>  /nova  /sair[/]",
        border_style="magenta",
    ))

    while True:
        try:
            texto = console.input("\n[bold cyan]Você:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not texto:
            continue
        if texto.lower() in ("/sair", "sair"):
            break
        if texto == "/debug":
            debug = not debug
            console.print(f"[dim]Debug {'ligado' if debug else 'desligado'}.[/]")
            continue
        if texto == "/nova":
            agente.reiniciar()
            arquivo_sessao.unlink(missing_ok=True)
            console.print("[dim]Conversa reiniciada.[/]")
            continue
        if texto.startswith("/exportar"):
            titulo = texto.removeprefix("/exportar").strip() or None
            console.print(f"[green]Conversa salva em {exportar_markdown(agente, titulo)}[/]")
            continue

        with console.status("[magenta]Duda está digitando...[/]"):
            resposta = agente.responder(texto)

        if debug:
            for f in resposta.ferramentas:
                console.print(f"[dim]  ferramenta: {f['ferramenta']} {json.dumps(f['argumentos'], ensure_ascii=False)}[/]")
            if resposta.provedor:
                console.print(f"[dim]  provedor: {resposta.provedor}[/]")
            for erro in agente.erros:
                console.print("  erro de API: " + erro, style="yellow", markup=False)
        console.print("[bold magenta]Duda:[/]", Markdown(resposta.texto))
        agente.salvar(arquivo_sessao)

    console.print("[dim]Até logo![/]")


if __name__ == "__main__":
    main()
