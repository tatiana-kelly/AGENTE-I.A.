"""Launcher: python ha.py <comando>  — funciona tanto no repositório quanto na cópia instalada no Hermes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hermes_autonomy.cli import main  # noqa: E402

sys.exit(main())
