"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/ops", label: "Dashboard" },
  { href: "/ops/analytics", label: "Analytics" },
  { href: "/ops/websites", label: "Websites" },
  { href: "/ops/prompts", label: "Prompts" },
  { href: "/ops/tracking", label: "Tracking" },
  { href: "/ops/gaps", label: "Gaps & Slips" },
  { href: "/ops/pipeline", label: "Content Pipeline" },
  { href: "/ops/site-audit", label: "Site Audit" },
  { href: "/ops/admin", label: "Admin" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/ops") return pathname === "/ops";
  // /ops/clients permanently redirects to /ops/websites — keep it highlighted.
  if (href === "/ops/websites") return pathname.startsWith("/ops/websites") || pathname.startsWith("/ops/clients");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function OpsSidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 bg-slate-900 text-slate-100 flex-shrink-0 flex flex-col">
      <div className="h-16 flex items-center px-6 font-bold text-lg border-b border-slate-800">
        Footnote Ops
      </div>
      <nav className="flex-1 p-4 space-y-2 text-sm">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`block px-3 py-2 rounded transition-colors ${
                active
                  ? "bg-slate-800 text-white font-medium"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-100"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
