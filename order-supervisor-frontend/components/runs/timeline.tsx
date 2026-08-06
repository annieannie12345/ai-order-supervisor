import { Activity, AlertTriangle, Bot, CheckCircle2, Clock, Hammer, MessageCircle, Pause, Play, Square } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/utils";
import type { JsonValue, TimelineEntry } from "@/types/api";

function iconFor(kind: string) {
  if (kind.startsWith("event:") || kind === "order_event") return MessageCircle;
  if (kind.startsWith("tool:") || kind === "tool_call") return Hammer;
  if (kind.includes("failed")) return AlertTriangle;
  if (kind.includes("wake")) return Clock;
  if (kind === "agent_action" || kind === "memory_updated") return Bot;
  if (kind === "interrupted" || kind === "interrupt") return Pause;
  if (kind === "resumed" || kind === "resume") return Play;
  if (kind === "terminated" || kind === "terminate" || kind === "terminate_requested") return Square;
  if (kind === "final_summary" || kind === "closed" || kind === "lifecycle") return CheckCircle2;
  return Activity;
}

function titleFor(entry: TimelineEntry) {
  const eventType = stringAt(entry.payload, "event_type") ?? entry.kind.replace(/^event:/, "");
  const tool = stringAt(entry.payload, "tool");
  const reason = stringAt(entry.payload, "reason");

  if (entry.kind.startsWith("event:") || entry.kind === "order_event") return humanize(eventType);
  if (entry.kind === "agent_action") return `Agent step${reason ? `: ${humanize(reason)}` : ""}`;
  if (entry.kind === "memory_updated") return "Memory updated";
  if (entry.kind.startsWith("tool:") || entry.kind === "tool_call") return `Tool call${tool ? `: ${humanize(tool)}` : ""}`;
  if (entry.kind === "tool_failed") return `Tool failed${tool ? `: ${humanize(tool)}` : ""}`;
  if (entry.kind === "wake_scheduled") return "Next wake scheduled";
  if (entry.kind === "instruction_added") return "Instruction added";
  if (entry.kind === "interrupted" || entry.kind === "interrupt") return "Workflow interrupted";
  if (entry.kind === "resumed" || entry.kind === "resume") return "Workflow resumed";
  if (entry.kind === "terminate_requested" || entry.kind === "terminate") return "Termination requested";
  if (entry.kind === "final_summary") return "Final summary";
  if (entry.kind === "closed") return "Workflow closed";
  if (entry.kind === "terminated") return "Workflow terminated";
  if (entry.kind === "lifecycle") return `Lifecycle${reason ? `: ${humanize(reason)}` : ""}`;
  return humanize(entry.kind);
}

function summaryFor(entry: TimelineEntry) {
  const payload = entry.payload;
  if (entry.kind.startsWith("event:") || entry.kind === "order_event") {
    return (
      stringAt(payload, "body") ??
      stringAt(payload, "message") ??
      stringAt(payload, "reason") ??
      stringAt(payload, "delay_reason") ??
      sentence([
        stringAt(payload, "carrier"),
        stringAt(payload, "tracking_number"),
        money(payload.requested_amount, stringAt(payload, "currency")),
        money(payload.amount, stringAt(payload, "currency"))
      ]) ??
      "Order event received."
    );
  }

  if (entry.kind === "agent_action") {
    return (
      stringAt(payload, "actions_taken.decision") ??
      stringAt(payload, "actions_taken.reason") ??
      `Agent ran because of ${humanize(stringAt(payload, "reason") ?? "workflow activity")}.`
    );
  }

  if (entry.kind === "memory_updated") return stringAt(payload, "summary") ?? "The run memory was refreshed.";
  if (entry.kind === "final_summary") return stringAt(payload, "summary") ?? "The workflow produced a final summary.";
  if (entry.kind === "wake_scheduled") return `Next check: ${formatDateTime(stringAt(payload, "next_wake_at"))}.`;
  if (entry.kind === "instruction_added") return stringAt(payload, "instruction") ?? "A new instruction was added.";

  if (entry.kind.startsWith("tool:") || entry.kind === "tool_call") {
    return (
      stringAt(payload, "result.message") ??
      stringAt(payload, "result.note") ??
      stringAt(payload, "result.reason") ??
      stringAt(payload, "result.outcome") ??
      "Tool completed successfully."
    );
  }

  if (entry.kind === "tool_failed") return stringAt(payload, "error") ?? "The tool call failed.";
  return stringAt(payload, "reason") ?? "Workflow state changed.";
}

function factsFor(entry: TimelineEntry) {
  const payload = entry.payload;
  const facts = [
    ["Status", stringAt(payload, "result.status")],
    ["Carrier", stringAt(payload, "carrier") ?? stringAt(payload, "result.carrier")],
    ["Tracking", stringAt(payload, "tracking_number") ?? stringAt(payload, "result.tracking_number")],
    ["Channel", stringAt(payload, "channel") ?? stringAt(payload, "result.channel")],
    ["Priority", stringAt(payload, "result.priority")],
    ["Important", booleanAt(payload, "important")],
    ["Amount", money(payload.amount, stringAt(payload, "currency")) ?? money(payload.requested_amount, stringAt(payload, "currency"))]
  ];
  return facts.filter((fact): fact is [string, string] => Boolean(fact[1]));
}

export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Timeline</CardTitle>
        <span className="text-sm text-zinc-500">{entries.length} entries</span>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <div className="rounded-md border border-dashed border-zinc-200 p-6 text-sm text-zinc-500">
            No timeline entries yet.
          </div>
        ) : (
          <div className="space-y-4">
            {[...entries].reverse().map((entry, index) => {
              const Icon = iconFor(entry.kind);
              const facts = factsFor(entry);
              return (
                <article key={`${entry.ts}-${entry.kind}-${index}`} className="grid grid-cols-[32px_1fr] gap-3">
                  <div className="grid h-8 w-8 place-items-center rounded-md border border-zinc-200 bg-zinc-50">
                    <Icon size={15} className="text-zinc-600" />
                  </div>
                  <div className="rounded-lg border border-zinc-200 bg-white p-3">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium text-zinc-950">{titleFor(entry)}</div>
                        <div className="mt-0.5 text-xs text-zinc-500">{formatDateTime(entry.ts)}</div>
                      </div>
                      <Badge variant="outline">{humanize(entry.kind)}</Badge>
                    </div>
                    <p className="text-sm leading-6 text-zinc-700">{summaryFor(entry)}</p>
                    {facts.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {facts.map(([label, value]) => (
                          <span key={`${label}-${value}`} className="rounded-md bg-zinc-50 px-2 py-1 text-xs text-zinc-600">
                            <span className="font-medium text-zinc-800">{label}:</span> {value}
                          </span>
                        ))}
                      </div>
                    )}
                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs font-medium text-zinc-500 hover:text-zinc-800">
                        Technical payload
                      </summary>
                      <pre className="mt-2 max-h-56 overflow-auto rounded-md bg-zinc-50 p-3 text-xs text-zinc-700">
                        {JSON.stringify(entry.payload, null, 2)}
                      </pre>
                    </details>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function stringAt(payload: Record<string, JsonValue>, path: string) {
  const value = valueAt(payload, path);
  return typeof value === "string" && value.trim() ? value : undefined;
}

function booleanAt(payload: Record<string, JsonValue>, path: string) {
  const value = valueAt(payload, path);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return undefined;
}

function valueAt(payload: Record<string, JsonValue>, path: string): JsonValue | undefined {
  return path.split(".").reduce<JsonValue | undefined>((current, key) => {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    return current[key];
  }, payload);
}

function humanize(value: string) {
  return value.replace(/^event:/, "").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function money(value: JsonValue | undefined, currency = "USD") {
  if (typeof value !== "number") return undefined;
  return `${currency} ${value.toFixed(2)}`;
}

function sentence(parts: Array<string | undefined>) {
  const filtered = parts.filter(Boolean);
  return filtered.length ? filtered.join(" · ") : undefined;
}
