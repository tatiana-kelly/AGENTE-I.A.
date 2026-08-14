# SAL Intelligence OS

Pacote de especificação para implementação no Claude Code.

## O que já está pronto
- `CLAUDE.md` com regras permanentes.
- 26 agentes especializados em `.claude/agents/`, incluindo Soluções e Ações Práticas.
- regras transversais em `.claude/rules/`.
- arquitetura e backlog.
- contratos JSON.
- score de prioridade.
- roteamento por domínio.
- exemplo de MCP sem credenciais.
- prompt de handoff para iniciar no Claude Code.

## Como usar
1. Extraia este projeto.
2. Abra o terminal na raiz.
3. Inicie o Claude Code.
4. Confirme que `CLAUDE.md` foi carregado.
5. Abra `CLAUDE_CODE_HANDOFF.md` e peça ao Claude Code para executar o projeto conforme o documento.
6. Configure MCP somente quando as fontes reais e credenciais estiverem disponíveis.

## Filosofia
**Dado → desvio → causa → impacto → prioridade → solução → execução → aprendizado.**

O produto principal é a decisão, não o gráfico.


## Novidade v0.2
O diagnóstico validado agora passa obrigatoriamente pelo **Agente de Soluções e Ações Práticas**, que transforma a causa em:
- contenção;
- correção estrutural;
- otimização/prevenção;
- plano;
- dono;
- prazo;
- custo;
- impacto;
- KPI;
- meta;
- contingência.

O caso `examples/dre_margin_case.md` funciona como teste de referência do comportamento esperado.
