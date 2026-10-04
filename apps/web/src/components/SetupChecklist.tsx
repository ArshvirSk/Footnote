"use client";

import Link from "next/link";
import { CheckCircle2, Circle } from "lucide-react";
import type { ChecklistItem } from "../lib/api";

interface SetupChecklistProps {
  items: ChecklistItem[];
  progress: number;
  total: number;
}

/** The 7-item setup checklist that the website status is derived from. */
export default function SetupChecklist({ items, progress, total }: SetupChecklistProps) {
  const pctDone = total > 0 ? Math.round((progress / total) * 100) : 0;

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <h2 className="font-medium text-slate-900">Setup checklist</h2>
        <span className="text-sm text-slate-500 font-medium">
          {progress}/{total} complete
        </span>
      </div>
      <div className="h-1.5 bg-slate-100">
        <div className="h-1.5 bg-emerald-500 transition-all" style={{ width: `${pctDone}%` }} />
      </div>
      <ul className="divide-y divide-slate-100">
        {items.map((item) => (
          <li key={item.key} className="px-6 py-3 flex items-start gap-3">
            {item.done ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
            ) : (
              <Circle className="w-5 h-5 text-slate-300 shrink-0 mt-0.5" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-sm font-medium ${item.done ? "text-slate-900" : "text-slate-700"}`}>
                  {item.label}
                </span>
                <span className="text-xs text-slate-400">{item.detail}</span>
              </div>
              <div className="text-xs text-slate-500 mt-0.5">{item.why}</div>
            </div>
            {!item.done && (
              <Link
                href={item.href}
                className="text-xs font-medium text-blue-600 hover:text-blue-800 hover:underline shrink-0 mt-0.5"
              >
                Fix →
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
