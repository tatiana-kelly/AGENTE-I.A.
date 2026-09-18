"""Regra arquitetural do ciclo: o que a máquina pode, o que o humano deve e o que a máquina nunca faz.

Este módulo é a única fonte dessas regras; os demais módulos do ciclo chamam os guardas daqui em vez de
repetir verificações. Violação levanta GovernanceViolation — nunca é degradada para aviso.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.core.rbac import Role

MACHINE_MAY = (
    "detectar", "classificar", "investigar", "analisar", "recomendar", "propor", "priorizar",
    "sugerir ação", "verificar",
)
HUMAN_MUST = (
    "aprovar decisão", "rejeitar decisão", "aprovar exceção", "aprovar playbook",
    "assumir responsabilidade quando exigido",
)
MACHINE_MUST_NOT = (
    "aprovar a própria decisão",
    "transformar recomendação em decisão aprovada",
    "executar ação sem autorização",
    "marcar ação como sucesso sem evidência",
    "criar aprendizado dizendo que funcionou sem verificação",
)

APPROVAL_ROLES = frozenset({Role.GESTOR, Role.DIRETORIA})


class GovernanceViolation(RuntimeError):
    """Tentativa de violar a separação máquina × humano."""


class ActorKind(StrEnum):
    HUMAN = "human"
    MACHINE = "machine"


@dataclass(frozen=True)
class Actor:
    """Quem age. `kind` é declarado na origem: agente/serviço nunca se declara humano."""

    id: str
    kind: ActorKind
    role: Role | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise GovernanceViolation("ator sem identidade")
        if self.kind is ActorKind.MACHINE and self.role is not None:
            raise GovernanceViolation("ator máquina não possui papel humano")


def machine(name: str) -> Actor:
    return Actor(id=name, kind=ActorKind.MACHINE)


def human(name: str, role: Role) -> Actor:
    return Actor(id=name, kind=ActorKind.HUMAN, role=role)


def require_human(actor: Actor, operation: str) -> None:
    if actor.kind is not ActorKind.HUMAN:
        raise GovernanceViolation(f"{operation} exige humano identificado; ator '{actor.id}' é máquina")


def require_approval_role(actor: Actor, operation: str) -> None:
    """Mesma regra do RBAC das rotas (.claude/rules/human-approval.md): analista não decide sozinho."""
    require_human(actor, operation)
    if actor.role not in APPROVAL_ROLES:
        raise GovernanceViolation(
            f"{operation} exige papel gestor ou diretoria; '{actor.id}' é {actor.role}"
        )
