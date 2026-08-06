"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil, Plus } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toolOptions } from "@/lib/constants";
import { supervisorSchema, type SupervisorFormValues } from "@/lib/validators";
import { parseJsonObject, stringifyJson } from "@/lib/utils";
import { useCreateSupervisor } from "@/hooks/use-supervisors";
import type { Supervisor } from "@/types/api";

const defaultInstruction =
  "Watch this order from creation to completion. Act quickly on payment failures, shipment exceptions, refund requests, and customer complaints. Keep customer messaging concise and escalate when human judgment is needed.";

export function SupervisorForm({ selected }: { selected: Supervisor | null }) {
  const createSupervisor = useCreateSupervisor();
  const form = useForm<SupervisorFormValues>({
    resolver: zodResolver(supervisorSchema),
    defaultValues: {
      name: "Default Order Supervisor",
      base_instruction: defaultInstruction,
      tools: [...toolOptions],
      wake_policy: stringifyJson({ aggressiveness: "balanced", default_check_hours: 6 }),
      model_config: stringifyJson({ model: "gpt-4o" })
    }
  });

  useEffect(() => {
    if (!selected) return;
    form.reset({
      name: `${selected.name} revised`,
      base_instruction: selected.base_instruction,
      tools: selected.tools,
      wake_policy: stringifyJson(selected.wake_policy ?? {}),
      model_config: stringifyJson(selected.model_config ?? selected.llm_config ?? {})
    });
  }, [selected, form]);

  async function onSubmit(values: SupervisorFormValues) {
    await createSupervisor.mutateAsync({
      name: values.name,
      base_instruction: values.base_instruction,
      tools: values.tools,
      wake_policy: parseJsonObject(values.wake_policy),
      model_config: parseJsonObject(values.model_config)
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{selected ? "Edit supervisor draft" : "Create supervisor"}</CardTitle>
        <CardDescription>
          {selected
            ? "The backend contract has no update endpoint, so saving creates a revised template."
            : "Define the agent instruction, tools, wake policy, and model config."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" {...form.register("name")} />
            <FormError message={form.formState.errors.name?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="base_instruction">Base instruction</Label>
            <Textarea id="base_instruction" className="min-h-40" {...form.register("base_instruction")} />
            <FormError message={form.formState.errors.base_instruction?.message} />
          </div>
          <div className="space-y-2">
            <Label>Available tools</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {toolOptions.map((tool) => (
                <label key={tool} className="flex items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.watch("tools").includes(tool)}
                    onChange={(event) => {
                      const current = form.getValues("tools");
                      form.setValue(
                        "tools",
                        event.target.checked ? [...current, tool] : current.filter((item) => item !== tool),
                        { shouldValidate: true }
                      );
                    }}
                  />
                  <span className="truncate font-mono text-xs">{tool}</span>
                </label>
              ))}
            </div>
            <FormError message={form.formState.errors.tools?.message} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="wake_policy">Wake policy</Label>
              <Textarea id="wake_policy" className="min-h-32 font-mono text-xs" {...form.register("wake_policy")} />
              <FormError message={form.formState.errors.wake_policy?.message} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="model_config">Model config</Label>
              <Textarea id="model_config" className="min-h-32 font-mono text-xs" {...form.register("model_config")} />
              <FormError message={form.formState.errors.model_config?.message} />
            </div>
          </div>
          {createSupervisor.error instanceof Error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {createSupervisor.error.message}
            </div>
          )}
          <Button type="submit" disabled={createSupervisor.isPending}>
            {selected ? <Pencil size={15} /> : <Plus size={15} />}
            {createSupervisor.isPending ? "Saving..." : selected ? "Save revised template" : "Create supervisor"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function FormError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-sm text-red-600">{message}</p>;
}
