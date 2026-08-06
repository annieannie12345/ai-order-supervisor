"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Bot, LayoutDashboard, Plus, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/runs/new", label: "Create Run", icon: Plus },
  { href: "/supervisors", label: "Supervisors", icon: Settings2 }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-zinc-200 bg-white lg:block">
        <div className="flex h-16 items-center gap-3 border-b border-zinc-200 px-5">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-zinc-950 text-white">
            <Bot size={19} />
          </div>
          <div>
            <div className="text-sm font-semibold">Order Supervisor</div>
            <div className="text-xs text-zinc-500">AI operations</div>
          </div>
        </div>
        <nav className="space-y-1 p-3">
          {navItems.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-zinc-600 transition hover:bg-zinc-100 hover:text-zinc-950",
                  active && "bg-zinc-100 text-zinc-950"
                )}
              >
                <Icon size={16} />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/90 backdrop-blur">
          <div className="flex h-16 items-center justify-between px-4 sm:px-6">
            <div className="flex items-center gap-2 lg:hidden">
              <Activity size={19} />
              <span className="font-semibold">Order Supervisor</span>
            </div>
            <div className="hidden text-sm text-zinc-500 lg:block">Workflow console</div>
            <Button asChild size="sm">
              <Link href="/runs/new">
                <Plus size={15} />
                New run
              </Link>
            </Button>
          </div>
        </header>
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</div>
      </div>
    </div>
  );
}
