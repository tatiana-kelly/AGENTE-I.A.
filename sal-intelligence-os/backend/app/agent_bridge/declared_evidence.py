"""Evidência DECLARADA (modo autônomo, 2026-09-19): liga uma fonte nova sem escrever um montador por fonte.

Cada fonte declara em `config/evidence_sources.json` uma LISTA FECHADA de campos do registro de origem, com
significado e unidade. Só esses campos saem; tudo que não foi declarado — conclusão do motor, classificação,
causa, recomendação, nome de pessoa ou cliente — fica de fora por construção.

O registro de origem é achado pelo `source_ref` do adaptador (`<arquivo> <caminho>[seletor]`, com `+` quando o
alerta combina dois registros), lido só do diretório de dados da própria fonte.

Cada alerta vira até 2 evidências:
- `ev-<fonte>-alerta`: o que o adaptador calculou (métrica, valor atual, referência, materialidade, período) e as
  transformações que ele declarou — determinístico, sem IA;
- `ev-<fonte>-registro`: os campos declarados do registro de origem, com o dicionário (significado + unidade).
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent_bridge.contract import Evidence, EvidenceQuality
from app.decision_router.adapters.base import AdaptedAlert, TorreDataReader

DEFAULT_DECLARATIONS = Path(__file__).resolve().parents[3] / "config" / "evidence_sources.json"
_STEP = re.compile(r"([^.\[\]]+)(?:\[([^\]]*)\])?")


class EvidenceNotDeclared(LookupError):
    """A fonte não tem declaração: nenhuma evidência é montada e nenhum provider é chamado."""


@dataclass(frozen=True)
class FieldSpec:
    meaning: str
    unit: str


def load_declarations(path: Path = DEFAULT_DECLARATIONS) -> dict[str, dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {key: value for key, value in raw.items() if not key.startswith("_")}


def resolve_record(document: Any, path: str) -> dict[str, Any] | None:
    """Navega `a.b[sel].c[sel]`; seletor = índice inteiro ou `campo=valor`. None se não achar exatamente um."""
    node = document
    for name, selector in _STEP.findall(path):
        if not isinstance(node, dict):
            return None
        node = node.get(name)
        if selector == "" or selector is None:
            continue
        if isinstance(node, dict):
            node = node.get(selector)
        elif isinstance(node, list):
            if selector.isdigit():
                index = int(selector)
                node = node[index] if index < len(node) else None
            elif "=" in selector:
                key, value = selector.split("=", 1)
                matches = [item for item in node if isinstance(item, dict) and str(item.get(key)) == value]
                node = matches[0] if len(matches) == 1 else None
            else:
                return None
        else:
            return None
    return node if isinstance(node, dict) else None


def _records(reader: TorreDataReader, source_ref: str) -> list[dict[str, Any]]:
    first_file = source_ref.split(" ", 1)[0]
    records = []
    for part in source_ref.split(" + "):
        part = part.strip()
        file, _, path = part.partition(" ") if " " in part else (first_file, "", part)
        if not path:
            file, path = first_file, part
        record = resolve_record(reader.read_json(file), path)
        if record is not None:
            records.append(record)
    return records


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def build_declared_evidence(reader: TorreDataReader, adapted: AdaptedAlert,
                            declarations: dict[str, dict[str, Any]]) -> tuple[Evidence, ...]:
    declaration = declarations.get(adapted.source)
    if not declaration:
        raise EvidenceNotDeclared(f"fonte {adapted.source} sem evidência declarada")
    alert = adapted.envelope.alert
    slug = _slug(adapted.source.split(".")[-1])
    evaluated = adapted.envelope.evaluated_at
    stamp = evaluated if isinstance(evaluated, datetime) else datetime.fromisoformat(str(evaluated))
    quality = EvidenceQuality(source_quality=str(alert.source_quality))
    base = Evidence(
        id=f"ev-{slug}-alerta", source=f"{adapted.source} (adaptador determinístico)", period=str(alert.period),
        timestamp=stamp, filters={"entidade": adapted.envelope.entity_type, "id_entidade": adapted.envelope.entity_id},
        quality=quality, limitations=list(declaration.get("limitations", [])),
        data={"metrica": alert.metric_id, "valor_atual": alert.current_value, "referencia": alert.reference_value,
              "materialidade": alert.materiality, "unidade_materialidade": declaration.get("materiality_unit", "R$"),
              "transformacoes_do_adaptador": list(adapted.transformations)},
    )
    fields: dict[str, dict[str, str]] = declaration.get("fields", {})
    records = _records(reader, adapted.source_ref)
    values: dict[str, Any] = {}
    for record in records:
        for name in fields:
            if name in record and name not in values and not isinstance(record[name], (dict, list)):
                values[name] = record[name]
    if not values:
        return (base,)
    registro = Evidence(
        id=f"ev-{slug}-registro", source=f"{adapted.source_ref.split(' ', 1)[0]} (campos declarados)", period=str(alert.period),
        timestamp=stamp, filters={"entidade": adapted.envelope.entity_type, "id_entidade": adapted.envelope.entity_id},
        quality=quality, limitations=["só campos declarados em evidence_sources.json; conclusões do motor excluídas"],
        data={"valores": values, "dicionario": {name: fields[name] for name in values}},
    )
    return (base, registro)
