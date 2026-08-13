export type TaskStatus = "success" | "error" | "skipped";

/** FASE 17 — structured log fields. Missing metrics are "unknown", never invented. */
export interface ObservabilityRecord {
  task_id: string;
  provider: string | "unknown";
  model: string | "unknown";
  skill: string | "unknown";
  status: TaskStatus;
  duration_ms: number | "unknown";
  error: string | "unknown";
  cost_usd: number | "unknown";
}

export interface LogSink {
  emit(record: ObservabilityRecord): void;
}

export class ConsoleLogSink implements LogSink {
  emit(record: ObservabilityRecord): void {
    console.log(JSON.stringify(record));
  }
}

export class Observability {
  constructor(private readonly sink: LogSink = new ConsoleLogSink()) {}

  log(partial: Partial<ObservabilityRecord> & Pick<ObservabilityRecord, "task_id" | "status">): void {
    this.sink.emit({
      task_id: partial.task_id,
      provider: partial.provider ?? "unknown",
      model: partial.model ?? "unknown",
      skill: partial.skill ?? "unknown",
      status: partial.status,
      duration_ms: partial.duration_ms ?? "unknown",
      error: partial.error ?? "unknown",
      cost_usd: partial.cost_usd ?? "unknown",
    });
  }
}
