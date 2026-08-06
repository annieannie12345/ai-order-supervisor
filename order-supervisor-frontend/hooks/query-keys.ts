export const queryKeys = {
  health: ["health"] as const,
  runs: ["runs"] as const,
  runState: (runId: string) => ["runs", runId, "state"] as const,
  timeline: (runId: string) => ["runs", runId, "timeline"] as const,
  supervisors: ["supervisors"] as const,
  supervisor: (supervisorId: string) => ["supervisors", supervisorId] as const
};
