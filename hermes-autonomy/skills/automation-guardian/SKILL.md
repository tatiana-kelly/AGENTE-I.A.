---
name: automation-guardian
description: Supervisiona as automações da Tatiana (EXPECTED vs ACTUAL), diagnostica, repara com segurança, valida e escala. Use para "as automações rodaram?", "o que falhou hoje?", saúde diária, rodar o guardião ou reprocessar um incidente.
version: 0.1.0
author: Claude Code (AGENTE-I.A / hermes-autonomy)
license: proprietary
platforms: [windows]
metadata:
  hermes:
    tags: [monitoring, reliability, automation, incidents, sre]
    category: autonomy
---

# Automation Guardian (Hermes Autonomy)

Camada autônoma de confiabilidade sobre as automações existentes (Agendador do Windows, GitHub Actions,
scripts). Cinco papéis, um motor determinístico (sem LLM no caminho crítico, sem custo de tokens):

| Papel | O que faz | Nunca faz |
|---|---|---|
| hermes-guardian | compara o que DEVERIA ter acontecido (registry) com o que aconteceu (agendador, logs, arquivos, APIs) | alterar qualquer coisa |
| hermes-diagnostician | investiga em 12 passos fixos e aponta causa com evidência e confiança | inventar causa (usa `UNKNOWN_CAUSE`) |
| hermes-repair-agent | executa só ações de risco baixo autorizadas no registry, idempotentes, com circuit breaker e rate limit | apagar dado, mexer em schema/credencial/código |
| hermes-validator | reexecuta a verificação completa sobre o que a correção escreveu | confiar no retorno do reparo |
| hermes-escalator | chama a Tatiana com problema, causa, evidências, ações, impacto e ação necessária | mandar "automação falhou" |

## Onde está

- App instalado: `%LOCALAPPDATA%\hermes\autonomy\app` (fonte: `AGENTE-I.A\hermes-autonomy`)
- Estado/memória: `%LOCALAPPDATA%\hermes\autonomy\autonomy.db` e `outbox\`
- Registry: `app\registry\automations.json`

Todos os comandos: `python "%LOCALAPPDATA%\hermes\autonomy\app\ha.py" <comando>`
(PowerShell: `python "$env:LOCALAPPDATA\hermes\autonomy\app\ha.py" <comando>`)

## Quando usar → comando

| Pedido | Comando |
|---|---|
| "as automações estão ok?" (somente leitura) | `health` (`-v` mostra as evidências) |
| rodar o ciclo completo agora | `tick` |
| uma automação específica | `health --only <id>` / `tick --only <id>` |
| resumo do dia | `report` |
| modo, última rodada, incidentes, cron | `status` |
| o que o agente fez | `logs` |

## Regras

1. Padrão é `DRY_RUN=true`: detecta, diagnostica e mostra a ação que SERIA feita. Não passe `--live` sem pedido
   explícito da Tatiana.
2. Nunca declare sucesso sem evidência. Diga "validado por X, Y, Z" (campo `validated_by`).
   `INSUFFICIENT_EVIDENCE` não é sucesso.
3. Não reexecute automações que enviam e-mail/WhatsApp (`idempotent: false`) — escale.
4. Para ações de risco médio/alto: crie a correção, teste, registre e ESCALE. Não execute.
5. Não edite o registry sem validar: `registry --list` deve terminar em "registry OK".
