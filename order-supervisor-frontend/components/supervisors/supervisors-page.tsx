"use client";

import { useMemo, useState } from "react";
import { Bot, Pencil } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SupervisorForm } from "@/components/supervisors/supervisor-form";
import { useSupervisors } from "@/hooks/use-supervisors";

export function SupervisorsPage() {
  const supervisorsQuery = useSupervisors();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const supervisors = supervisorsQuery.data ?? [];
  const selected = useMemo(
    () => supervisors.find((supervisor) => supervisor.id === selectedId) ?? null,
    [supervisors, selectedId]
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-normal">Supervisors</h1>
        <p className="mt-1 text-sm text-zinc-500">Create and revise reusable AI supervisor templates.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>Templates</CardTitle>
            <Badge variant="outline">{supervisors.length}</Badge>
          </CardHeader>
          <CardContent className="space-y-2">
            {supervisorsQuery.isLoading ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-16 w-full" />)
            ) : supervisors.length === 0 ? (
              <div className="rounded-md border border-dashed border-zinc-200 p-4 text-sm text-zinc-500">
                No supervisors yet.
              </div>
            ) : (
              supervisors.map((supervisor) => (
                <button
                  key={supervisor.id}
                  type="button"
                  onClick={() => setSelectedId(supervisor.id)}
                  className="flex w-full items-start gap-3 rounded-md border border-zinc-200 bg-white p-3 text-left transition hover:bg-zinc-50"
                >
                  <div className="grid h-8 w-8 place-items-center rounded-md bg-zinc-100">
                    <Bot size={15} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{supervisor.name}</div>
                    <div className="mt-1 text-xs text-zinc-500">{supervisor.tools.length} tools</div>
                  </div>
                  <Pencil size={14} className="text-zinc-400" />
                </button>
              ))
            )}
            {selected && (
              <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
                Clear edit draft
              </Button>
            )}
          </CardContent>
        </Card>

        <SupervisorForm selected={selected} />
      </div>
    </div>
  );
}
