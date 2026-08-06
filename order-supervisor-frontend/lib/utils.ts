import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { JsonObject, JsonValue } from "@/types/api";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "None";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

export function isJsonObject(value: JsonValue): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function parseJsonObject(value: string): JsonObject {
  const parsed = JSON.parse(value) as JsonValue;
  if (!isJsonObject(parsed)) throw new Error("Expected a JSON object.");
  return parsed;
}

export function stringifyJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}
