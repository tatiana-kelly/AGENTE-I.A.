# SAL Intelligence OS — backend (Fase 0)

Implementa a fundação descrita em `docs/IMPLEMENTATION_BACKLOG.md` Fase 0: modelos de dados,
Metric Registry, Data Quality Gate, Audit Trail, conectores (mock + real) e o orquestrador que
chama os 26 subagentes de `.claude/agents/` via API da Claude.

## Rodando localmente

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate  # ou source .venv/bin/activate no Linux/Mac
pip install -r requirements.txt
cp .env.example .env    # preencha ANTHROPIC_API_KEY e/ou SUPABASE_RELATORIOS_RAW_URL se for usar
python -m pytest -q
```

## Decisões tomadas na apresentação da Fase 0 (não redescobrir)

- **DRE/orçamento/faturamento continuam mock.** As 3 bases Supabase reais da SAL
  (`relatorios-raw`, `Gente & Gestao`, `pendency-tracker`) não têm essa informação estruturada
  hoje — só dado operacional/fiscal/folha/RH. `MockDreConnector` usa os números de
  `examples/dre_margin_case.md`.
- **Custo/frete/atraso operacionais já são reais**, via `SupabaseOperationalConnector` contra
  `relatorios-raw` (tabelas `os_custos`, `relatorio_455_processado`, `455_consolidado_mes_atual`,
  `mapa_filial`). Requer `SUPABASE_RELATORIOS_RAW_URL` no `.env` — sem ela, levanta `RuntimeError`
  explicando o que falta, nunca inventa dado.
- **Orquestração chama a API da Claude diretamente**, sem passar pelo AI Orchestrator
  (PRP-003 / repo `AGENTE-I.A.`), para não acoplar os dois projetos antes de ambos provarem valor
  isoladamente. Reavaliar essa decisão quando ambos estiverem maduros.
- **Persistência própria (Alert/Diagnosis/...) em SQLite por padrão.** Trocar `DATABASE_URL` por
  Postgres quando volume/concorrência justificarem; sem Alembic por enquanto (schema ainda muda
  rápido demais para migrations valerem o esforço) — `Base.metadata.create_all()` no startup.
- **RBAC é só 3 papéis genéricos** (analista/gestor/diretoria) via header `X-Sal-Role`. Refinar
  quando RH/DP mapear papéis reais (Fase 2).

## Rodar o caso obrigatório de validação

```bash
python -m scripts.seed_mock_data   # registra a MetricDefinition margem-bruta
python -m scripts.run_dre_case     # roda examples/dre_margin_case.md ponta a ponta
```

Sem `ANTHROPIC_API_KEY`, o script mostra só o Alert determinístico (conector mock) e para —
a investigação completa via subagentes precisa da chave.

## O que falta (próxima sessão, ver task list / IMPLEMENTATION_BACKLOG.md Fase 1)

- Detection Engine sobre os dados operacionais reais.
- UI mínima da Decision Queue.
- Rodar `scripts/run_dre_case.py` com `ANTHROPIC_API_KEY` real e revisar a saída dos 26 agentes.
- Achar (ou confirmar que não existe) uma fonte real de DRE/orçamento antes de sair do mock.
