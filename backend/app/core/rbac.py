"""RBAC mínimo — Fase 0. Papéis genéricos até o RH/DP mapear papéis reais (Fase 2, ver
docs/IMPLEMENTATION_BACKLOG.md). Autenticação real (RS/JWT/SSO) também fica para depois:
por ora, o papel vem de um header simples, suficiente para gatear rotas sensíveis nos testes
e no MVP local.
"""

from enum import StrEnum

from fastapi import Header, HTTPException


class Role(StrEnum):
    ANALISTA = "analista"
    GESTOR = "gestor"
    DIRETORIA = "diretoria"


_APPROVAL_ROLES = {Role.GESTOR, Role.DIRETORIA}


def get_current_role(x_sal_role: str = Header(default=Role.ANALISTA.value)) -> Role:
    try:
        return Role(x_sal_role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"papel inválido: {x_sal_role}") from exc


def require_approval_role(role: Role) -> None:
    """Gate para decisões sensíveis (.claude/rules/human-approval.md) — analista não decide sozinho."""
    if role not in _APPROVAL_ROLES:
        raise HTTPException(
            status_code=403,
            detail="decisão exige papel gestor ou diretoria (.claude/rules/human-approval.md)",
        )
