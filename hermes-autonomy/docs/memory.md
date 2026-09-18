# Memória de incidentes

Banco: `%LOCALAPPDATA%\hermes\autonomy\autonomy.db` (SQLite, WAL). Sandbox de provas:
`%LOCALAPPDATA%\hermes\autonomy-sandbox\` (separado para não misturar com produção).

| Tabela | Conteúdo |
|---|---|
| `incidents` | id, automação, janela, tipo, estado, prioridade, desfecho, causa, confiança, incidente raiz, detectado/resolvido, tentativas, solução, ação humana, tempo de recuperação, evidências (JSON), diagnóstico (JSON) |
| `incident_events` | ciclo de vida (de → para, agente, nota) |
| `repair_attempts` | tentativa, ação, chave de idempotência única, dry_run, resultado, validação |
| `audit_log` | timestamp, agent, automation, incident, action, reason, tool, result, validation, risk_level, dry_run |
| `notifications` | canal, tipo, dedupe_key, entregue, corpo (redigido) |
| `circuit` | estado do circuit breaker por automação |
| `skill_candidates` | causa → ação validada, contador |
| `runs`, `checks` | cada rodada e cada verificação (base do relatório diário e do "último sucesso") |

## Consultas

```powershell
python ha.py history torre-importar-ssw-1200 --cause NETWORK_TIMEOUT   # já teve? como resolvemos?
python ha.py incidents --cause TASK_ACCESS_DENIED
python ha.py incident INC-20260918-104905-44f9
python ha.py logs --limit 50
```

Idempotência: um incidente por automação+janela (`fingerprint`). Janela já `RESOLVED`/`ESCALATED` não é
reprocessada. Nenhum dado é apagado pelo sistema; `uninstall` preserva o banco.
