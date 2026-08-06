import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      default: "border-zinc-200 bg-zinc-100 text-zinc-800",
      active: "border-emerald-200 bg-emerald-50 text-emerald-700",
      paused: "border-amber-200 bg-amber-50 text-amber-700",
      done: "border-sky-200 bg-sky-50 text-sky-700",
      terminated: "border-red-200 bg-red-50 text-red-700",
      outline: "border-zinc-200 bg-white text-zinc-600"
    }
  },
  defaultVariants: { variant: "default" }
});

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant, className }))} {...props} />;
}
