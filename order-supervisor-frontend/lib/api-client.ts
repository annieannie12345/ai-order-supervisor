import type {
  EventSubmit,
  InstructionSubmit,
  Run,
  RunCommand,
  RunCreate,
  RunState,
  Supervisor,
  SupervisorCreate,
  TimelineEntry
} from "@/types/api";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body.detail) {
        message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // Keep HTTP status text when the backend returns a non-JSON error.
    }
    throw new Error(message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const apiClient = {
  health: () => request<{ status: string }>("/health"),
  listRuns: () => request<Run[]>("/runs"),
  createRun: (body: RunCreate) =>
    request<Run>("/runs", { method: "POST", body: JSON.stringify(body) }),
  getRunState: (runId: string) => request<RunState>(`/runs/${encodeURIComponent(runId)}`),
  getTimeline: (runId: string) =>
    request<TimelineEntry[]>(`/runs/${encodeURIComponent(runId)}/timeline`),
  submitEvent: (runId: string, body: EventSubmit) =>
    request(`/runs/${encodeURIComponent(runId)}/events`, {
      method: "POST",
      body: JSON.stringify(body)
    }),
  addInstruction: (runId: string, body: InstructionSubmit) =>
    request(`/runs/${encodeURIComponent(runId)}/instructions`, {
      method: "POST",
      body: JSON.stringify(body)
    }),
  commandRun: (runId: string, command: RunCommand) =>
    request(`/runs/${encodeURIComponent(runId)}/${command}`, { method: "POST" }),
  listSupervisors: () => request<Supervisor[]>("/supervisors"),
  createSupervisor: (body: SupervisorCreate) =>
    request<Supervisor>("/supervisors", { method: "POST", body: JSON.stringify(body) }),
  getSupervisor: (supervisorId: string) =>
    request<Supervisor>(`/supervisors/${encodeURIComponent(supervisorId)}`)
};
