# Instruções compartilhadas para agentes

Regras para qualquer agente que trabalhar neste repositório, incluindo Claude Code, Claude Cowork e Codex.

## Antes de agir

- Leia `AI-PROJECT.yaml` e os arquivos declarados em `.ai/`.
- Respeite `access.allowed_paths` e nunca leia `access.denied_paths`.
- Comece em leitura e sustente críticas em arquivo/trecho verificável.
- Nunca invente contexto de negócio ausente.

## Arquitetura — não alterar

```text
n8n = quando/como executar
AI Orchestrator (este repo) = qual IA deve pensar/executar
ChatGPT/OpenAI = decide
Manus = investiga/faz
Claude Code = constrói
Gemini = ecossistema Google
Supabase = dados
GitHub = código
Vercel = deploy
```

Qualquer mudança nessa divisão, inclusive tornar Codex um construtor/fallback oficial, exige aprovação estrutural explícita da Tatiana.

## Governança

```text
TATIANA (negócio, prioridade, aprovação)
   ↓
CHATGPT (arquitetura, PRPs, decisões estruturais)
   ↓
CLAUDE CODE (execução, código, testes)
```

Este repositório não duplica a governança do Control Plane. Decisões estruturais novas voltam para Tatiana/ChatGPT.

## Segurança

- Default: `READ_ONLY`, `DRY_RUN=true`.
- Nunca enfraqueça `evaluateExecution` sem autorização explícita.
- Nunca leia, copie ou versione `.env`, chaves, tokens, certificados ou service accounts reais.
- Escrita, custo, push, pull request, migration e deploy mantêm aprovações independentes.
- Push exige autorização explícita a cada vez. Commits locais são permitidos.
- Nada fora deste repositório pode ser alterado como efeito colateral.

## Projetos integrados

- `AI-PROJECT.yaml` é o contrato legível por máquina.
- `.ai/` contém apenas contexto autorizado e confirmado.
- `.agents/skills/sal-project/` contém o fluxo reutilizável de auditoria/melhoria.
- O `pendency-tracker` e demais projetos Supabase existentes estão fora de escopo.

## Desenvolvimento

- Commits pequenos no padrão `tipo(escopo): descrição`.
- Preserve alterações do usuário e nunca use comandos destrutivos para descartá-las.
- Antes de criar provider, skill, tabela ou integração, verifique se existe algo reaproveitável neste projeto.
- Notificações pertencem ao Email Agent oficial; não implemente SMTP/Resend diretamente.

## Validação obrigatória

```bash
npm test
npm run typecheck
npm run lint
npm run build
```

Alterações no routing/planner devem manter os testes de `tests/routing.test.ts`. Alterações no manifesto, onboarding ou registro devem manter `tests/projects.test.ts`.

## Diretórios protegidos

- `C:\SAL_AI_OS\`: governança externa; não recebe código deste projeto.
- `salexpress-ai`: outro responsável; não alterar.
- Credenciais ou arquivos de configuração secretos fora deste repositório: não acessar.
