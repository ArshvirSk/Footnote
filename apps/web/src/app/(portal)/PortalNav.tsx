"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface PortalNavProps {
  pendingCount?: number;
}

export default function PortalNav({ pendingCount = 0 }: PortalNavProps) {
  const pathname = usePathname();

  const NAV_ITEMS = [
    { href: "/portal", label: "Overview" },
    { href: "/portal/approvals", label: "Approvals", badge: pendingCount > 0 ? pendingCount : undefined },
    { href: "/portal/content", label: "Shipped Content" },
    { href: "/portal/settings", label: "Settings" },
  ];

  return (
    <nav className="ml-8 flex space-x-6 text-sm font-medium">
      {NAV_ITEMS.map((item) => {
        const active =
          item.href === "/portal" ? pathname === "/portal" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`py-5 border-b-2 transition-colors ${
              active
                ? "text-slate-900 border-slate-900"
                : "text-slate-500 border-transparent hover:text-slate-900"
            }`}
          >
            {item.label}
            {item.badge !== undefined && (
              <span className="ml-1.5 bg-amber-100 text-amber-800 font-bold py-0.5 px-2 rounded-full text-xs">
                {item.badge}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

