import type {
  AccessRequest,
  BackupSettings,
  BackupSettingsUpdate,
  EgressEvent,
  Failure,
  FailureDetail,
  RcaReport,
  Repository,
  RepositoryUpdate,
  SecuritySummary,
  TaskAccepted,
  WikiDoc,
  WikiDocContent,
  WikiSearchHit,
} from "./types";

const BASE = "/api/v1";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    const message =
      (detail as { detail?: string; error?: string })?.detail ??
      (detail as { detail?: string; error?: string })?.error ??
      response.statusText;
    throw new Error(`HTTP ${response.status}: ${message}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  // ---- failures ------------------------------------------------------------
  listFailures: (limit = 100) => request<{ failures: Failure[] }>(`/failures?limit=${limit}`),
  getFailure: (id: string, includeFull = false) =>
    request<FailureDetail>(`/failures/${id}${includeFull ? "?include_full=true" : ""}`),
  getFailureRca: (id: string) => request<RcaReport>(`/failures/${id}/rca`),
  requestRca: (failureId: string) =>
    request<TaskAccepted>(`/rca`, {
      method: "POST",
      body: JSON.stringify({ failure_id: failureId }),
    }),

  // ---- wiki ---------------------------------------------------------------
  listWiki: () => request<{ docs: WikiDoc[] }>(`/wiki`),
  readWiki: (path: string) => request<WikiDocContent>(`/wiki/doc?path=${encodeURIComponent(path)}`),
  searchWiki: (query: string) =>
    request<{ hits: WikiSearchHit[] }>(`/wiki/search?q=${encodeURIComponent(query)}`),

  // ---- backup settings -----------------------------------------------------
  getBackupSettings: () => request<BackupSettings>(`/settings/backup`),
  saveBackupSettings: (update: BackupSettingsUpdate) =>
    request<BackupSettings>(`/settings/backup`, {
      method: "PUT",
      body: JSON.stringify(update),
    }),
  triggerBackup: () => request<TaskAccepted>(`/settings/backup/trigger`, { method: "POST" }),

  // ---- chat ---------------------------------------------------------------
  chat: (message: string) =>
    request<TaskAccepted>(`/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  // ---- repositories + access -----------------------------------------------
  listRepositories: () => request<{ repositories: Repository[] }>(`/repositories`),
  updateRepository: (id: string, update: RepositoryUpdate) =>
    request<Repository>(`/repositories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(update),
    }),
  listAccessRequests: (status?: string) =>
    request<{ requests: AccessRequest[] }>(`/access-requests${status ? `?status=${status}` : ""}`),
  resolveAccessRequest: (id: string, decision: "approved" | "denied") =>
    request<AccessRequest>(`/access-requests/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    }),

  // ---- security ------------------------------------------------------------
  getSecuritySummary: () => request<SecuritySummary>(`/security/summary`),
  listEgressEvents: (params: { kind?: string; sensitive?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (params.kind) q.set("kind", params.kind);
    if (params.sensitive) q.set("sensitive", "true");
    const qs = q.toString();
    return request<{ events: EgressEvent[] }>(`/security/egress${qs ? `?${qs}` : ""}`);
  },

  // ---- tasks ---------------------------------------------------------------
  getTask: <T = unknown>(taskId: string) =>
    request<{
      task_id: string;
      status: string;
      result?: T;
      error?: string | null;
    }>(`/tasks/${taskId}`),
};

export async function pollTask<T>(
  taskId: string,
  { intervalMs = 1000, timeoutMs = 120_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<T> {
  const started = Date.now();
  while (true) {
    const snapshot = await api.getTask<T>(taskId);
    if (snapshot.status === "SUCCESS") {
      return snapshot.result as T;
    }
    if (snapshot.status === "FAILURE" || snapshot.status === "REVOKED") {
      throw new Error(snapshot.error ?? `Task ${taskId} ${snapshot.status}`);
    }
    if (Date.now() - started > timeoutMs) {
      throw new Error(`Task ${taskId} timed out after ${timeoutMs}ms`);
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
