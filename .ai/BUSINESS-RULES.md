# Regras de negócio

- O modo padrão é `READ_ONLY` com `DRY_RUN=true`.
- Efeito desconhecido falha fechado.
- Escrita, custo, push, PR, migration e deploy mantêm gates independentes.
- Push exige autorização explícita a cada vez.
- Nenhuma credencial real pode ser lida, copiada ou versionada.
- O Orchestrator não altera projetos fora do escopo autorizado.
