"""Base de conhecimento de causas. Só classifica com evidência textual/código — nunca inventa causa."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import IncidentType as T


@dataclass(frozen=True)
class CausePattern:
    code: str
    regex: str
    incident_type: str
    cause: str
    transient: bool
    human_action: str | None = None
    dependency: str = "generic"

    def search(self, text: str) -> "re.Match[str] | None":
        return re.search(self.regex, text, re.IGNORECASE | re.MULTILINE)


# Ordem importa: causas específicas antes de sintomas genéricos.
CAUSE_PATTERNS: list[CausePattern] = [
    CausePattern("CREDENTIAL_MISSING",
                 r"(vari[aá]vel|env(ironment)?\s*var(iable)?)\s+\S+\s+(n[aã]o\s+(definida|encontrada|configurada)|not\s+(set|found|defined))"
                 r"|KeyError:\s*'[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|SENHA)[A-Z0-9_]*'"
                 r"|credencia\w*\s+(ausente|n[aã]o\s+encontrad)|missing\s+credential|CREDENTIAL_MISSING",
                 T.AUTHENTICATION_FAILURE.value, "Credencial ausente no ambiente de execução", False,
                 "Configurar a credencial ausente (variável de ambiente/secret manager) e reexecutar", "credential"),
    CausePattern("AUTH_EXPIRED",
                 r"invalid_grant|token\s+(has\s+)?expired|JWT\s+expired|expired\s+token|Token has been expired or revoked"
                 r"|refresh\s+token.*(invalid|revoked)",
                 T.AUTHENTICATION_FAILURE.value, "Token/credencial expirado ou revogado", False,
                 "Reconectar/renovar a credencial expirada (ex.: reautorizar OAuth) e reexecutar", "auth"),
    CausePattern("AUTH_DENIED",
                 r"\bHTTP\s*(Error\s*)?40[13]\b|\b40[13]\s+(Unauthorized|Forbidden)|Unauthorized|Forbidden"
                 r"|invalid\s+api\s+key|permission denied for (table|relation|schema)",
                 T.AUTHENTICATION_FAILURE.value, "Acesso negado pela API/banco (401/403)", False,
                 "Verificar permissão/chave da integração e reexecutar", "auth"),
    CausePattern("NETWORK_TIMEOUT",
                 r"WinError 10060|timed?\s*out|ETIMEDOUT|ConnectTimeout|ReadTimeout|tempo limite",
                 T.API_FAILURE.value, "Timeout de conexão com API/host remoto", True, None, "network"),
    CausePattern("CONNECTION_FAILED",
                 r"WinError 1006[14]|WinError 11001|ECONNREFUSED|ECONNRESET|Connection (refused|reset|aborted)"
                 r"|getaddrinfo failed|Name or service not known|RemoteDisconnected",
                 T.API_FAILURE.value, "Falha de conexão/DNS com API remota", True, None, "network"),
    CausePattern("HTTP_5XX",
                 r"\bHTTP\s*(Error\s*)?50[0234]\b|\b50[234]\s+(Bad Gateway|Service Unavailable|Gateway Time-?out)"
                 r"|status(_code)?\s*[=:]\s*50[0234]|API_503",
                 T.API_FAILURE.value, "API remota indisponível (5xx)", True, None, "api"),
    CausePattern("RATE_LIMITED", r"\b429\b|Too Many Requests|rate.?limit",
                 T.API_FAILURE.value, "Limite de requisições da API atingido (429)", True, None, "api"),
    CausePattern("BROWSER_TIMEOUT", r"playwright.*timeout|TimeoutError:\s*(page|locator)|selenium.*timeout",
                 T.API_FAILURE.value, "Timeout na automação de navegador (portal lento/indisponível)", True, None, "portal"),
    CausePattern("FILE_LOCKED", r"WinError 32|being used by another process|sendo usad[oa] por outro processo",
                 T.RESOURCE_FAILURE.value, "Arquivo bloqueado por outro processo", True, None, "filesystem"),
    CausePattern("DISK_FULL", r"No space left|espa[cç]o insuficiente|not enough space|MemoryError|Out of memory",
                 T.RESOURCE_FAILURE.value, "Recurso esgotado (disco/memória)", False,
                 "Liberar disco/memória na máquina e reexecutar", "host"),
    CausePattern("MODULE_MISSING", r"ModuleNotFoundError|ImportError:|Cannot find module|No module named",
                 T.DEPENDENCY_FAILURE.value, "Dependência de software ausente (módulo/pacote)", False,
                 "Instalar a dependência ausente no ambiente do script", "runtime"),
    CausePattern("FILE_NOT_FOUND",
                 r"FileNotFoundError|No such file or directory|n[aã]o pode encontrar o (arquivo|caminho)"
                 r"|cannot find the (file|path)",
                 T.DEPENDENCY_FAILURE.value, "Arquivo/caminho de entrada inexistente", False,
                 "Verificar o arquivo/caminho de entrada esperado pela automação", "filesystem"),
    CausePattern("GIT_PUSH_REJECTED", r"\[rejected\]|failed to push some refs|non-fast-forward",
                 T.DELIVERY_FAILURE.value, "Publicação no git rejeitada (branch remota divergente)", True, None, "git"),
    CausePattern("EMPTY_SOURCE", r"Nenhum registro lido|\b0 registros lidos|no rows returned",
                 T.DATA_NOT_UPDATED.value, "Fonte de dados retornou vazia", True, None, "data"),
]

# LastTaskResult do Agendador de Tarefas (inteiro sem sinal)
TASK_RESULT_CODES: dict[int, tuple[str, str, bool, str | None]] = {
    0x80070005: ("TASK_ACCESS_DENIED", "Agendador não conseguiu iniciar a ação: acesso negado (0x80070005)", False,
                 "Revisar conta/permissões da tarefa agendada (executar com o usuário correto, caminho acessível)"),
    0x80070002: ("TASK_FILE_NOT_FOUND", "Executável/script da tarefa não encontrado (0x80070002)", False,
                 "Corrigir o caminho do script/executável na tarefa agendada"),
    0x8007010B: ("TASK_BAD_DIRECTORY", "Diretório de trabalho inválido (0x8007010B)", False,
                 "Corrigir o diretório 'Iniciar em' da tarefa agendada"),
    0x800710E0: ("TASK_REFUSED", "Operador/sistema recusou a execução (0x800710E0) — máquina ocupada/sessão", True, None),
    0x8004131F: ("TASK_ALREADY_RUNNING", "Instância anterior ainda em execução (0x8004131F)", True, None),
    0x8007042B: ("TASK_PROCESS_ABORTED", "Processo encerrado inesperadamente (0x8007042B)", True, None),
    0x41306: ("TASK_TERMINATED", "Tarefa encerrada pelo usuário/sistema (0x41306)", True, None),
    0x40010004: ("TASK_TERMINATED", "Processo terminado externamente (0x40010004)", True, None),
    0xC000013A: ("TASK_TERMINATED", "Processo interrompido (Ctrl+C/sessão encerrada) (0xC000013A)", True, None),
    0xFFFFFFFF: ("SCRIPT_EXIT_NONZERO", "Script terminou com código -1", True, None),
    1: ("SCRIPT_EXIT_NONZERO", "Script terminou com código de erro 1", True, None),
    2: ("SCRIPT_EXIT_NONZERO", "Script terminou com código de erro 2", True, None),
}


def match_causes(text: str) -> list[tuple[CausePattern, str]]:
    """Todas as causas com evidência no texto, na ordem de prioridade, com o trecho que casou."""
    hits = []
    for pattern in CAUSE_PATTERNS:
        m = pattern.search(text or "")
        if m:
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            hits.append((pattern, text[start:end if end != -1 else None].strip()[:300]))
    return hits


def pattern_by_code(code: str) -> CausePattern | None:
    return next((p for p in CAUSE_PATTERNS if p.code == code), None)


def describe_task_result(code: int | None) -> tuple[str, str, bool, str | None]:
    if code is None:
        return ("UNKNOWN_RESULT", "Código de retorno indisponível", False, None)
    if code in TASK_RESULT_CODES:
        return TASK_RESULT_CODES[code]
    return ("SCRIPT_EXIT_NONZERO", f"Código de retorno não catalogado: {code} (0x{code:08X})", True, None)
