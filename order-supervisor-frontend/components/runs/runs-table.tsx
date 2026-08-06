"use client";

import Link from "next/link";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/runs/status-badge";
import { EmptyState } from "@/components/runs/empty-state";
import { formatDateTime } from "@/lib/utils";
import type { Run } from "@/types/api";

export function RunsTable({
  runs,
  isLoading,
  error
}: {
  runs: Run[];
  isLoading: boolean;
  error: Error | null;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return runs.filter((run) => {
      const matchesSearch =
        !query ||
        run.order_id.toLowerCase().includes(query) ||
        run.id.toLowerCase().includes(query) ||
        run.workflow_id.toLowerCase().includes(query);
      const matchesStatus = status === "all" || run.status === status;
      return matchesSearch && matchesStatus;
    });
  }, [runs, search, status]);

  if (error) {
    return <EmptyState title="Backend unavailable" detail={error.message} />;
  }

  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-col gap-3 border-b border-zinc-200 p-4 md:flex-row md:items-center md:justify-between">
          <div className="relative w-full md:max-w-sm">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-400" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search order, run, workflow"
              className="pl-9"
            />
          </div>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger aria-label="Status filter" className="w-full md:w-44">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="paused">Paused</SelectItem>
              <SelectItem value="done">Done</SelectItem>
              <SelectItem value="terminated">Terminated</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-6 text-sm text-zinc-500">No runs match the current filters.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-left text-xs uppercase text-zinc-500">
                <tr>
                  <th className="px-4 py-3 font-medium">Order</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Next wake</th>
                  <th className="px-4 py-3 font-medium">Updated</th>
                  <th className="px-4 py-3 text-right font-medium">Open</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((run) => (
                  <tr key={run.id} className="border-t border-zinc-100">
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-950">{run.order_id}</div>
                      <div className="mt-1 max-w-xs truncate font-mono text-xs text-zinc-500">{run.workflow_id}</div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3 text-zinc-600">{formatDateTime(run.next_wake_at)}</td>
                    <td className="px-4 py-3 text-zinc-600">{formatDateTime(run.updated_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <Button asChild variant="outline" size="sm">
                        <Link href={`/runs/${run.id}`}>Details</Link>
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
