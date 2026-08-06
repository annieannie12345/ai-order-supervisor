"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { Supervisor, SupervisorCreate } from "@/types/api";
import { queryKeys } from "@/hooks/query-keys";

export function useSupervisors() {
  return useQuery({
    queryKey: queryKeys.supervisors,
    queryFn: apiClient.listSupervisors
  });
}

export function useCreateSupervisor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SupervisorCreate) => apiClient.createSupervisor(body),
    onSuccess: (supervisor) => {
      queryClient.setQueryData<Supervisor[]>(queryKeys.supervisors, (current) => [
        ...(current ?? []),
        supervisor
      ]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.supervisors });
    }
  });
}
