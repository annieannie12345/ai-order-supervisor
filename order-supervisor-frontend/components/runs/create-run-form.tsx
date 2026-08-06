"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { createRunSchema, type CreateRunFormValues } from "@/lib/validators";
import { parseJsonObject, stringifyJson } from "@/lib/utils";
import { useCreateRun } from "@/hooks/use-runs";
import { useSupervisors } from "@/hooks/use-supervisors";

const defaultOrderPayload = {
  customer_name: "Jane Doe",
  email: "jane@example.com",
  items: [{ sku: "ABC-1", qty: 1, name: "Everyday Tote" }],
  status: "placed",
  total: 49.99
};

export function CreateRunForm() {
  const router = useRouter();
  const supervisorsQuery = useSupervisors();
  const createRun = useCreateRun();
  const form = useForm<CreateRunFormValues>({
    resolver: zodResolver(createRunSchema),
    defaultValues: {
      order_id: `ORD-${Math.floor(Math.random() * 90000 + 10000)}`,
      supervisor_id: "",
      order_payload: stringifyJson(defaultOrderPayload),
      initial_memory: ""
    }
  });

  async function onSubmit(values: CreateRunFormValues) {
    const run = await createRun.mutateAsync({
      order_id: values.order_id,
      supervisor_id: values.supervisor_id,
      order_payload: parseJsonObject(values.order_payload),
      initial_memory: values.initial_memory || null
    });
    router.push(`/runs/${run.id}`);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create run</CardTitle>
        <CardDescription>Start one long-running workflow for an order.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="order_id">Order ID</Label>
              <Input id="order_id" {...form.register("order_id")} />
              <FormError message={form.formState.errors.order_id?.message} />
            </div>
            <div className="space-y-2">
              <Label>Supervisor</Label>
              <Select value={form.watch("supervisor_id")} onValueChange={(value) => form.setValue("supervisor_id", value, { shouldValidate: true })}>
                <SelectTrigger aria-label="Supervisor">
                  <SelectValue placeholder="Select supervisor" />
                </SelectTrigger>
                <SelectContent>
                  {(supervisorsQuery.data ?? []).map((supervisor) => (
                    <SelectItem key={supervisor.id} value={supervisor.id}>
                      {supervisor.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormError message={form.formState.errors.supervisor_id?.message} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="order_payload">Order payload</Label>
            <Textarea id="order_payload" className="min-h-64 font-mono text-xs" {...form.register("order_payload")} />
            <FormError message={form.formState.errors.order_payload?.message} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="initial_memory">Initial memory</Label>
            <Textarea id="initial_memory" className="min-h-28" {...form.register("initial_memory")} />
          </div>
          {createRun.error instanceof Error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {createRun.error.message}
            </div>
          )}
          <Button type="submit" disabled={createRun.isPending}>
            {createRun.isPending ? "Starting..." : "Start workflow"}
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
