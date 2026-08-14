"""Carrega os 26 subagentes de .claude/agents/*.md como configuração — não reescrevê-los em Python.

Cada arquivo é front matter YAML (name/description/model/memory/effort) + corpo em Markdown,
que vira o system prompt do agente ao chamar a API da Claude diretamente.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

AGENTS_DIR = Path(__file__).resolve().parents[3] / ".claude" / "agents"
DOMAIN_ROUTING_PATH = Path(__file__).resolve().parents[3] / "config" / "domain-routing.yaml"


@dataclass
class AgentSpec:
    name: str
    description: str
    model: str
    effort: str
    system_prompt: str


def _parse_agent_file(path: Path) -> AgentSpec:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path} não tem front matter YAML no formato esperado")
    _, front_matter, body = raw.split("---", 2)
    meta = yaml.safe_load(front_matter)
    return AgentSpec(
        name=meta["name"],
        description=meta.get("description", ""),
        model=meta.get("model", "inherit"),
        effort=meta.get("effort", "medium"),
        system_prompt=body.strip(),
    )


def load_agent(name: str) -> AgentSpec:
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"agente '{name}' não existe em {AGENTS_DIR}")
    return _parse_agent_file(path)


def list_agent_names() -> list[str]:
    return sorted(p.stem for p in AGENTS_DIR.glob("*.md"))


def load_domain_routing() -> dict[str, list[str]]:
    with open(DOMAIN_ROUTING_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return {case_type: spec["agents"] for case_type, spec in config["routing"].items()}
