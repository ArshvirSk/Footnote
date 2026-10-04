"use client";

import { useEffect, useState } from "react";
import { Globe } from "lucide-react";
import {
  CLIENT_CHANGED_EVENT,
  getSelectedClientId,
  me,
  setSelectedClientId,
  websites,
  type ClientSummary,
} from "../../lib/api";

/**
 * Site-wide website switcher: every ops page reads the selected website from
 * localStorage, so this header is the single place to change it.
 */
export default function OpsHeader() {
  const [list, setList] = useState<ClientSummary[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        // Include demo websites so they stay selectable; they carry a badge.
        const data = await websites.list(true);
        setList(data);
        const stored = getSelectedClientId();
        const resolved = data.find((c) => c.id === stored)?.id ?? data[0]?.id ?? "";
        setSelected(resolved);
        // Only write when it actually changes: setSelectedClientId dispatches
        // CLIENT_CHANGED_EVENT, which this same effect listens to.
        if (resolved && resolved !== stored) setSelectedClientId(resolved);
      } catch {
        setList([]);
      }
    }
    void load();
    window.addEventListener(CLIENT_CHANGED_EVENT, load);
    return () => window.removeEventListener(CLIENT_CHANGED_EVENT, load);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setEmail((await me()).email);
      } catch {
        setEmail(null);
      }
    })();
  }, []);

  function onChange(value: string) {
    setSelected(value);
    setSelectedClientId(value);
  }

  const current = list.find((c) => c.id === selected);

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center gap-3 px-8 shadow-sm">
      <Globe className="w-4 h-4 text-slate-400" />
      <label htmlFor="website-switcher" className="text-sm text-slate-500 whitespace-nowrap">
        Website
      </label>
      <select
        id="website-switcher"
        value={selected}
        onChange={(e) => onChange(e.target.value)}
        disabled={list.length === 0}
        className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm font-medium text-slate-800 bg-white focus:outline-none focus:ring-2 focus:ring-slate-900 disabled:opacity-60 max-w-xs"
      >
        {list.length === 0 && <option value="">No websites yet</option>}
        {list.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} ({c.primary_domain}){c.is_demo ? " — demo" : ""}
          </option>
        ))}
      </select>
      {current?.is_demo && (
        <span className="px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-full text-xs font-medium">
          Demo data
        </span>
      )}
      {current && (
        <span className="text-xs text-slate-400 hidden lg:inline">
          {current.setup_progress}/{current.setup_total} setup complete
        </span>
      )}
      <div className="ml-auto text-sm text-slate-500">{email ?? ""}</div>
    </header>
  );
}
