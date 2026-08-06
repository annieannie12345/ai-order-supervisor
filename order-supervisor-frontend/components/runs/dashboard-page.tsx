"use client";

import { Activity, Clock, PauseCircle, Plus } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunsTable } from "@/components/runs/runs-table";
import { useRuns } from "@/hooks/use-runs";

export function DashboardPage() {
  const runsQuery = useRuns();
  const runs = runsQuery.data ?? [];
  const active = runs.filter((run) => run.status === "active").length;
  const paused = runs.filter((run) => run.status === "paused").length;
  const scheduled = runs.filter((run) => run.next_wake_at).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">Runs</h1>
          <p className="mt-1 text-sm text-zinc-500">Monitor active and completed order supervision workflows.</p>
        </div>
        <Button asChild>
          <Link href="/runs/new">
            <Plus size={16} />
            Create run
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm text-zinc-500">
              <Activity size={15} /> Active
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">{active}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm text-zinc-500">
              <PauseCircle size={15} /> Paused
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">{paused}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm text-zinc-500">
              <Clock size={15} /> Scheduled wakeups
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">{scheduled}</CardContent>
        </Card>
      </div>

      <RunsTable
        runs={runs}
        isLoading={runsQuery.isLoading}
        error={runsQuery.error instanceof Error ? runsQuery.error : null}
      />
    </div>
  );
}
