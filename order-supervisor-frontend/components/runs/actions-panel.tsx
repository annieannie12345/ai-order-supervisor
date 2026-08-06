"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Loader2, Pause, Play, Send, Square, StickyNote } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { eventTemplates } from "@/lib/constants";
import { eventSchema, instructionSchema, type EventFormValues, type InstructionFormValues } from "@/lib/validators";
import { parseJsonObject, stringifyJson } from "@/lib/utils";
import { useAddInstruction, useRunCommand, useSubmitEvent } from "@/hooks/use-runs";
import type { TimelineEntry } from "@/types/api";

type PendingAgentWork = {
  label: string;
  mode: "event" | "agent";
  submittedAt: number;
};

const TIMELINE_CLOCK_TOLERANCE_MS = 30_000;

function isAgentOutput(entry: TimelineEntry) {
  return (
    entry.kind === "agent_action" ||
    entry.kind === "memory_updated" ||
    entry.kind === "final_summary" ||
    entry.kind.startsWith("tool:") ||
    entry.kind === "tool_call" ||
    entry.kind === "tool_failed"
  );
}

export function ActionsPanel({
  runId,
  timeline,
  agentBusy
}: {
  runId: string;
  timeline: TimelineEntry[];
  agentBusy: boolean;
}) {
  const submitEvent = useSubmitEvent(runId);
  const addInstruction = useAddInstruction(runId);
  const commandRun = useRunCommand(runId);
  const [pendingAgentWork, setPendingAgentWork] = useState<PendingAgentWork | null>(null);
  const [acknowledgement, setAcknowledgement] = useState<string | null>(null);

  const eventForm = useForm<EventFormValues>({
    resolver: zodResolver(eventSchema),
    defaultValues: {
      type: eventTemplates[0].type,
      payload: stringifyJson(eventTemplates[0].payload)
    }
  });
  const instructionForm = useForm<InstructionFormValues>({
    resolver: zodResolver(instructionSchema),
    defaultValues: {
      instruction: "If shipment is delayed, escalate immediately and create an internal note."
    }
  });

  const watchedType = eventForm.watch("type");
  useEffect(() => {
    const template = eventTemplates.find((item) => item.type === watchedType);
    if (template) eventForm.setValue("payload", stringifyJson(template.payload), { shouldValidate: true });
  }, [watchedType, eventForm]);

  useEffect(() => {
    if (!pendingAgentWork) return;
    const relevantEntries = timeline.filter((entry) => {
      const ts = Date.parse(entry.ts);
      return Number.isFinite(ts) && ts >= pendingAgentWork.submittedAt - TIMELINE_CLOCK_TOLERANCE_MS;
    });

    const hasAgentOutput = relevantEntries.some(isAgentOutput);
    if (hasAgentOutput) {
      setPendingAgentWork(null);
      setAcknowledgement("Agent response received.");
      return;
    }

    if (pendingAgentWork.mode === "event") {
      const eventEntry = [...relevantEntries].reverse().find((entry) => entry.kind.startsWith("event:"));
      if (eventEntry?.payload?.important === false) {
        setPendingAgentWork(null);
        setAcknowledgement("Event logged. The agent did not need to wake for this routine update.");
      }
    }
  }, [pendingAgentWork, timeline]);

  const isMutating = submitEvent.isPending || addInstruction.isPending || commandRun.isPending;
  const controlsLocked = isMutating || Boolean(pendingAgentWork) || agentBusy;
  const statusMessage = useMemo(() => {
    if (submitEvent.isPending) return "Sending event to the workflow...";
    if (addInstruction.isPending) return "Adding instruction...";
    if (commandRun.isPending) return "Sending workflow command...";
    if (pendingAgentWork) return pendingAgentWork.label;
    if (agentBusy) return "Agent is processing the latest timeline update...";
    return acknowledgement;
  }, [acknowledgement, addInstruction.isPending, agentBusy, commandRun.isPending, pendingAgentWork, submitEvent.isPending]);

  async function onEvent(values: EventFormValues) {
    await submitEvent.mutateAsync({
      type: values.type,
      payload: parseJsonObject(values.payload)
    });
    setAcknowledgement("Event accepted.");
    setPendingAgentWork({
      label: "Event accepted. Waiting for the agent response...",
      mode: "event",
      submittedAt: Date.now()
    });
  }

  async function onInstruction(values: InstructionFormValues) {
    await addInstruction.mutateAsync({ instruction: values.instruction });
    setAcknowledgement("Instruction accepted.");
    setPendingAgentWork({
      label: "Instruction accepted. Waiting for the agent response...",
      mode: "agent",
      submittedAt: Date.now()
    });
  }

  function onCommand(command: "interrupt" | "resume" | "terminate") {
    commandRun.mutate(command, {
      onSuccess: () => {
        const labels = {
          interrupt: "Interrupt requested.",
          resume: "Resume requested. Waiting for the agent response...",
          terminate: "Terminate requested. Waiting for final summary..."
        };
        setAcknowledgement(labels[command]);
        if (command !== "interrupt") {
          setPendingAgentWork({
            label: labels[command],
            mode: "agent",
            submittedAt: Date.now()
          });
        }
      }
    });
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Run actions</CardTitle>
          <CardDescription>Control workflow sleep and terminal behavior.</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-3 gap-2">
          <Button variant="outline" onClick={() => onCommand("interrupt")} disabled={controlsLocked}>
            <Pause size={15} /> Interrupt
          </Button>
          <Button variant="outline" onClick={() => onCommand("resume")} disabled={controlsLocked}>
            <Play size={15} /> Resume
          </Button>
          <Button variant="destructive" onClick={() => onCommand("terminate")} disabled={controlsLocked}>
            <Square size={15} /> Terminate
          </Button>
          {statusMessage && <ActionNotice message={statusMessage} busy={isMutating || Boolean(pendingAgentWork) || agentBusy} />}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Submit event</CardTitle>
          <CardDescription>Signal an order update into the workflow.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={eventForm.handleSubmit(onEvent)}>
            <div className="space-y-2">
              <Label>Event type</Label>
              <Select
                value={eventForm.watch("type")}
                onValueChange={(value) => eventForm.setValue("type", value, { shouldValidate: true })}
                disabled={controlsLocked}
              >
                <SelectTrigger aria-label="Event type" disabled={controlsLocked}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {eventTemplates.map((template) => (
                    <SelectItem key={template.type} value={template.type}>
                      {template.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="payload">Payload</Label>
              <Textarea id="payload" className="min-h-44 font-mono text-xs" disabled={controlsLocked} {...eventForm.register("payload")} />
              <FormError message={eventForm.formState.errors.payload?.message} />
            </div>
            <Button type="submit" disabled={controlsLocked}>
              {submitEvent.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send size={15} />}
              {submitEvent.isPending ? "Sending..." : pendingAgentWork ? "Waiting for agent..." : "Submit event"}
            </Button>
            {submitEvent.error instanceof Error && <FormError message={submitEvent.error.message} />}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Add instruction</CardTitle>
          <CardDescription>Attach run-specific guidance for the next agent step.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={instructionForm.handleSubmit(onInstruction)}>
            <div className="space-y-2">
              <Label htmlFor="instruction">Instruction</Label>
              <Textarea id="instruction" className="min-h-28" disabled={controlsLocked} {...instructionForm.register("instruction")} />
              <FormError message={instructionForm.formState.errors.instruction?.message} />
            </div>
            <Button type="submit" disabled={controlsLocked}>
              {addInstruction.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <StickyNote size={15} />}
              {addInstruction.isPending ? "Adding..." : pendingAgentWork ? "Waiting for agent..." : "Add instruction"}
            </Button>
            {addInstruction.error instanceof Error && <FormError message={addInstruction.error.message} />}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function FormError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-sm text-red-600">{message}</p>;
}

function ActionNotice({ message, busy }: { message: string; busy: boolean }) {
  return (
    <div className="col-span-3 flex items-center gap-2 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-700">
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
      <span>{message}</span>
    </div>
  );
}
