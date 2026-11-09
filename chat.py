"""Ponto de entrada: python chat.py [--debug] [--sessao NOME]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from emporio.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
