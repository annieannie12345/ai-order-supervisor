"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Run, RunCommand, RunCreate } from "@/types/api";
import { queryKeys } from "@/hooks/query-keys";

export function useRuns() {
  return useQuery({
    queryKey: queryKeys.runs,
    queryFn: apiClient.listRuns
  });
}

export function useCreateRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RunCreate) => apiClient.createRun(body),
    onSuccess: (run) => {
      queryClient.setQueryData<Run[]>(queryKeys.runs, (current) => [run, ...(current ?? [])]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs });
    }
  });
}

export function useRunState(runId: string) {
  return useQuery({
    queryKey: queryKeys.runState(runId),
    queryFn: () => apiClient.getRunState(runId),
    enabled: Boolean(runId),
    refetchInterval: 5_000
  });
}

export function useTimeline(runId: string) {
  return useQuery({
    queryKey: queryKeys.timeline(runId),
    queryFn: () => apiClient.getTimeline(runId),
    enabled: Boolean(runId),
    refetchInterval: 5_000
  });
}

export function useRunCommand(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (command: RunCommand) => apiClient.commandRun(runId, command),
    onMutate: async (command) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.runs });
      const previousRuns = queryClient.getQueryData<Run[]>(queryKeys.runs);
      const nextStatus = command === "interrupt" ? "paused" : command === "resume" ? "active" : "terminated";
      queryClient.setQueryData<Run[]>(queryKeys.runs, (current) =>
        current?.map((run) => (run.id === runId ? { ...run, status: nextStatus } : run))
      );
      return { previousRuns };
    },
    onError: (_error, _command, context) => {
      if (context?.previousRuns) queryClient.setQueryData(queryKeys.runs, context.previousRuns);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runState(runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline(runId) });
    }
  });
}

export function useSubmitEvent(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: apiClient.submitEvent.bind(null, runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline(runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runState(runId) });
    }
  });
}

export function useAddInstruction(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: apiClient.addInstruction.bind(null, runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline(runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runState(runId) });
    }
  });
}
