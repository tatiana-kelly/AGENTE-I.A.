/**
 * Superfície /v1/agent-runs — ponte oficial SAL Intelligence OS → AI Orchestrator (sal.agent-run/1.0).
 * O Orchestrator executa; caso, decisão, ação, verificação e aprendizado continuam no SAL OS.
 */

export { AUTH_SCHEME, AGENT_RUN_PERMISSION, InMemoryNonceStore, authenticateAgentRun, canonicalString, loadAgentRunAuthFromEnv, sign } from "./auth.js";
export type { AgentRunAuthConfig, AuthResult, NonceStore } from "./auth.js";
export { LIMITS, PROTOCOL_VERSION, agentRunRequestSchema, investigationOutputSchema } from "./contract.js";
export type { AgentRunRequest, AgentRunResponse, AgentRunStatus, EvidenceItem, InvestigationOutput } from "./contract.js";
export {
  AGENT_RUNS_IDENTITY_PATH,
  AGENT_RUNS_PATH,
  PROTOCOL_HEADER,
  RESPONSE_SIGNATURE_HEADER,
  handleAgentRunHttp,
  identityCanonical,
  responseCanonical,
} from "./http.js";
export type { AgentRunHttpDependencies, AgentRunHttpOutcome, RawHttpRequest } from "./http.js";
export { buildProviderPayload, resolveAuthorizedContext } from "./payload.js";
export { AGENT_RUN_PROVIDER_ALLOWLIST, executeAgentRun, parseAgentRunProviders } from "./runner.js";
export type { AgentRunDependencies, AgentRunOutcome } from "./runner.js";
export { InMemoryAgentRunStore, bodyHashHex, hashIdempotencyKey, hashRequest } from "./store.js";
export type { AgentRunAuditRecord, AgentRunStore, StoredAgentRun } from "./store.js";
