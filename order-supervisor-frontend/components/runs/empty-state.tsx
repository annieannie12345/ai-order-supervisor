import { AlertCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 p-6">
        <AlertCircle className="mt-0.5 h-5 w-5 text-zinc-400" />
        <div>
          <div className="font-medium">{title}</div>
          <div className="mt-1 text-sm text-zinc-500">{detail}</div>
        </div>
      </CardContent>
    </Card>
  );
}
