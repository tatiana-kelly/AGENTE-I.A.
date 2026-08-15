"""Wrapper fino sobre a API da Claude — decisão registrada na apresentação da Fase 0:
chamar Claude diretamente neste MVP, sem passar pelo AI Orchestrator (PRP-003/AGENTE-I.A.),
para não acoplar dois projetos antes de ambos provarem valor isoladamente.
"""

from anthropic import Anthropic

from app.core.config import get_settings


class ClaudeClient:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            self._client = None
        else:
            self._client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    @property
    def client(self) -> Anthropic:
        if self._client is None:
            raise RuntimeError(
                "ANTHROPIC_API_KEY não configurada. Defina no .env (ver .env.example) antes de "
                "chamar o orchestrator com agentes reais."
            )
        return self._client

    def complete(self, system: str, user_message: str, max_tokens: int = 4096) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    def complete_structured(self, system: str, user_message: str, tool_schema: dict, max_tokens: int = 4096) -> dict:
        """Força saída estruturada via tool use — usado na extração final do Diagnosis
        (mesmo padrão do StructuredOutput usado pelo Workflow tool: valida na camada de chamada,
        não confia em parsing de texto livre)."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=[tool_schema],
            tool_choice={"type": "tool", "name": tool_schema["name"]},
            messages=[{"role": "user", "content": user_message}],
        )
        if response.stop_reason == "max_tokens":
            # A geração da tool call foi cortada por max_tokens antes de fechar o JSON — a SDK
            # normalmente devolve block.input == {} nesse caso, o que depois vira "Field required"
            # em TODOS os campos na validação Pydantic e esconde a causa real. Achado real ao
            # rodar o caso DRE de ponta a ponta (2026-08-15) — ver orchestrator.py.
            raise RuntimeError(
                f"resposta cortada por max_tokens={max_tokens} antes de completar a tool call "
                f"'{tool_schema['name']}' — aumente max_tokens em vez de tratar isso como falha "
                "de validação do schema."
            )
        for block in response.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError("a resposta não incluiu uma chamada de tool_use estruturada")
