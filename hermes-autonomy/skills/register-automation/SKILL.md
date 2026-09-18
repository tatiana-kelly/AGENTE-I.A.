---
name: register-automation
description: Coloca uma automação sob supervisão do Guardião — descobre tarefas fora do registry, escreve a entrada (EXPECTED), valida e reinstala. Use quando surgir automação nova ou o Guardião não conhecer uma rotina.
version: 0.1.0
author: Claude Code (AGENTE-I.A / hermes-autonomy)
license: proprietary
platforms: [windows]
metadata:
  hermes:
    tags: [registry, onboarding, monitoring]
    category: autonomy
---

# Register Automation

Fonte de verdade: `AGENTE-I.A\hermes-autonomy\registry\automations.json` (versionado no Git).
A cópia em `%LOCALAPPDATA%\hermes\autonomy\app` é gerada por `install` — não edite a cópia.

## Passos

1. Descobrir: `python ha.py discover` lista tarefas do Agendador ainda fora do registry.
2. Levantar evidências REAIS (sem inventar): log que a rotina escreve, marcador de sucesso
   (ex.: `=== fim`, `[OK] Publicado`), padrões de erro, saídas, tabela/API que atualiza, se envia e-mail.
3. Escrever a entrada (modelo mínimo):

```json
{
  "id": "minha-rotina", "name": "Minha rotina", "source": "windows_task",
  "task_name": "\\Nome Exato Da Tarefa", "script": "C:/caminho/script.py",
  "schedule": {"type": "daily", "times": ["07:00"]},
  "grace_minutes": 20, "max_duration_minutes": 30,
  "checks": [
    {"type": "file", "kind": "log", "path": "C:/caminho/logs/rotina_{date:%Y%m%d}.log",
     "success_patterns": ["=== fim"], "failure_patterns": ["Traceback|ERROR"]}
  ],
  "dependencies": ["supabase"], "allowed_recovery_actions": [], "idempotent": "unverified",
  "risk_level": "low", "criticality": "medium", "owner": "Tatiana", "enabled": true
}
```

4. Validar: `python ha.py registry --list` → "registry OK".
5. Testar só leitura: `python ha.py health --only minha-rotina -v`.
6. Reinstalar no Hermes: `python ha.py install` (idempotente).

## Regras

- `allowed_recovery_actions: ["rerun_task"]` só com `idempotent: true` confirmado pela Tatiana.
- Rotina que envia e-mail/mensagem: `idempotent: false` ou `rerun_guard: "no_delivery"`.
- Credenciais nunca no registry: use `{env:NOME}`. O validador rejeita segredo literal.
- Tipos de agenda: `daily`, `interval`, `monthly`, `cron` (com `"utc": true` para GitHub), `event`.
