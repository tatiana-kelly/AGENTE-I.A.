# Dicionário de dados

- `ai_projects`: projetos registrados e snapshots de contexto autorizados.
- `ai_project_permissions`: capacidades concedidas a usuários, serviços e agentes.
- `ai_tasks`: solicitações e estado da orquestração.
- `ai_runs`: tentativas de provider, fallback e reviewer.
- `ai_evidence`: resultados, fontes, bloqueios, erros e limitações.
- `contextSha256`: hash do snapshot de contexto usado pelo agente.
- `sal-memory://v1/<sha256>`: fonte técnica gravada em `ai_evidence.sources`; identifica tarefa, projeto, contexto, classificação e plano idênticos sem expor seu conteúdo.
- `reusePolicy`: `allow` reutiliza resultado READ aprovado e vigente; `refresh` força nova análise sem apagar a memória anterior.
