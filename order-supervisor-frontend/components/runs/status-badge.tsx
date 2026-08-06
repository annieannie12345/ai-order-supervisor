import { Badge } from "@/components/ui/badge";

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const variant =
    normalized === "active"
      ? "active"
      : normalized === "paused"
        ? "paused"
        : normalized === "done"
          ? "done"
          : normalized === "terminated"
            ? "terminated"
            : "default";

  return <Badge variant={variant}>{status}</Badge>;
}
