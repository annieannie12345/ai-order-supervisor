"use client";

import Link from "next/link";
import { ArrowLeft, Clock, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ActionsPanel } from "@/components/runs/actions-panel";
import { StatusBadge } from "@/components/runs/status-badge";
import { Timeline } from "@/components/runs/timeline";
import { useRunState, useTimeline } from "@/hooks/use-runs";
import { formatDateTime } from "@/lib/utils";

export function RunDetailsPage({ runId }: { runId: string }) {
  const stateQuery = useRunState(runId);
  const timelineQuery = useTimeline(runId);
  const state = stateQuery.data;
  const timeline = timelineQuery.data ?? [];
  const latestEntry = timeline.at(-1);
  const latestKind = latestEntry?.kind ?? "";
  const latestEntryImportant = latestEntry?.payload?.important === true;
  const agentAppearsBusy =
    state?.status === "active" &&
    ((latestKind.startsWith("event:") && latestEntryImportant) ||
      ["instruction_added", "resumed", "terminate_requested"].includes(latestKind));

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <Button asChild variant="ghost" size="sm" className="-ml-3 mb-2">
            <Link href="/">
              <ArrowLeft size={15} /> Back to runs
            </Link>
          </Button>
          <h1 className="text-2xl font-semibold tracking-normal">Run Details</h1>
          <p className="mt-1 font-mono text-sm text-zinc-500">{runId}</p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            void stateQuery.refetch();
            void timelineQuery.refetch();
          }}
        >
          <RefreshCw size={15} /> Refresh
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-zinc-500">Status</CardTitle>
              </CardHeader>
              <CardContent>
                {stateQuery.isLoading ? <Skeleton className="h-7 w-24" /> : <StatusBadge status={state?.status ?? "unknown"} />}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-sm text-zinc-500">
                  <Clock size={15} /> Next wake
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm font-medium">{formatDateTime(state?.next_wake_at)}</CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm text-zinc-500">Live refresh</CardTitle>
              </CardHeader>
              <CardContent className="text-sm font-medium">Every 5 seconds</CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Memory Summary</CardTitle>
            </CardHeader>
            <CardContent>
              {stateQuery.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-4 w-1/2" />
                </div>
              ) : (
                <div className="min-h-32 rounded-md border border-zinc-200 bg-zinc-50 p-4 text-sm leading-6 text-zinc-700">
                  {state?.memory_summary || "No memory summary available yet."}
                </div>
              )}
            </CardContent>
          </Card>

          {agentAppearsBusy && (
            <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <Loader2 className="h-4 w-4 animate-spin" />
              <div>
                <div className="font-medium">Agent is processing the latest update</div>
                <div className="text-amber-700">Actions are temporarily locked until a new agent result appears.</div>
              </div>
            </div>
          )}

          <Timeline entries={timeline} />
        </div>

        <ActionsPanel runId={runId} timeline={timeline} agentBusy={agentAppearsBusy} />
      </div>
    </div>
  );
}
