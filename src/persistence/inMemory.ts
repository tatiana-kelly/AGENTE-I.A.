import type { EvidenceRecord } from "../orchestrator/types.js";
import type {
  OrchestrationRepository,
  OrchestrationRunRecord,
  OrchestrationRunUpdate,
  OrchestrationTaskRecord,
  OrchestrationTaskUpdate,
  PersistedTaskSnapshot,
} from "./types.js";

export class InMemoryOrchestrationRepository implements OrchestrationRepository {
  private readonly tasks = new Map<string, OrchestrationTaskRecord>();
  private readonly runs = new Map<string, OrchestrationRunRecord>();
  private readonly evidence: EvidenceRecord[] = [];

  async createTask(task: OrchestrationTaskRecord): Promise<void> {
    if (this.tasks.has(task.id)) throw new Error(`Task ${task.id} já existe.`);
    this.tasks.set(task.id, structuredClone(task));
  }

  async updateTask(taskId: string, update: OrchestrationTaskUpdate): Promise<void> {
    const current = this.tasks.get(taskId);
    if (!current) throw new Error(`Task ${taskId} não encontrada.`);
    this.tasks.set(taskId, structuredClone({ ...current, ...update }));
  }

  async claimTaskForContinuation(taskId: string, updatedAt: string): Promise<boolean> {
    const current = this.tasks.get(taskId);
    if (!current || current.status !== "awaiting_approval") return false;
    this.tasks.set(taskId, structuredClone({ ...current, status: "running", updatedAt }));
    return true;
  }

  async createRun(run: OrchestrationRunRecord): Promise<void> {
    if (!this.tasks.has(run.taskId)) throw new Error(`Task ${run.taskId} não encontrada.`);
    if (this.runs.has(run.id)) throw new Error(`Run ${run.id} já existe.`);
    this.runs.set(run.id, structuredClone(run));
  }

  async updateRun(runId: string, update: OrchestrationRunUpdate): Promise<void> {
    const current = this.runs.get(runId);
    if (!current) throw new Error(`Run ${runId} não encontrada.`);
    this.runs.set(runId, structuredClone({ ...current, ...update }));
  }

  async record(evidence: EvidenceRecord): Promise<void> {
    if (!this.tasks.has(evidence.task_id)) throw new Error(`Task ${evidence.task_id} não encontrada.`);
    this.evidence.push(structuredClone(evidence));
  }

  async getTask(taskId: string): Promise<PersistedTaskSnapshot | undefined> {
    const task = this.tasks.get(taskId);
    if (!task) return undefined;
    return structuredClone({
      task,
      runs: [...this.runs.values()].filter((run) => run.taskId === taskId),
      evidence: this.evidence.filter((record) => record.task_id === taskId),
    });
  }
}
