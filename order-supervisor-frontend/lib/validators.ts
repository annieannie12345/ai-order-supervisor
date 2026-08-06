import { z } from "zod";
import { parseJsonObject } from "@/lib/utils";

const jsonObjectString = z.string().superRefine((value, ctx) => {
  try {
    parseJsonObject(value);
  } catch (error) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: error instanceof Error ? error.message : "Invalid JSON object."
    });
  }
});

export const supervisorSchema = z.object({
  name: z.string().min(2, "Name is required."),
  base_instruction: z.string().min(10, "Base instruction is required."),
  tools: z.array(z.string()).min(1, "Select at least one tool."),
  wake_policy: jsonObjectString,
  model_config: jsonObjectString
});

export const createRunSchema = z.object({
  order_id: z.string().min(2, "Order ID is required."),
  supervisor_id: z.string().min(1, "Choose a supervisor."),
  order_payload: jsonObjectString,
  initial_memory: z.string().optional()
});

export const eventSchema = z.object({
  type: z.string().min(1, "Event type is required."),
  payload: jsonObjectString
});

export const instructionSchema = z.object({
  instruction: z.string().min(2, "Instruction is required.")
});

export type SupervisorFormValues = z.infer<typeof supervisorSchema>;
export type CreateRunFormValues = z.infer<typeof createRunSchema>;
export type EventFormValues = z.infer<typeof eventSchema>;
export type InstructionFormValues = z.infer<typeof instructionSchema>;
