"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Eye, Shield, Users, ChevronDown, CheckCircle2 } from "lucide-react";
import { PortalMe, portalApi, getSelectedClientId, setSelectedClientId } from "@/lib/api";
import PortalNav from "./PortalNav";

export default function PortalHeader() {
  const [me, setMe] = useState<PortalMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [pendingCount, setPendingCount] = useState<number>(0);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  useEffect(() => {
    const activeCid = getSelectedClientId() || undefined;
    portalApi.getMe(activeCid)
      .then((data) => {
        setMe(data);
        if (data.active_client_id) {
          setSelectedClientId(data.active_client_id);
          portalApi.listApprovals(data.active_client_id, "pending")
            .then((apps) => setPendingCount(apps.length))
            .catch(() => {});
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const switchClient = (cid: string) => {
    setSelectedClientId(cid);
    setDropdownOpen(false);
    window.location.reload();
  };

  const clientName = me?.active_client_name || (me?.clients?.[0]?.name) || "Client Portal";
  const userRole = me?.role || "client_viewer";
  const isViewer = userRole === "client_viewer";

  return (
    <>
      {/* Operator Preview Banner for agency staff */}
      {me?.is_preview && (
        <aside aria-label="Operator preview mode" className="bg-amber-500 text-slate-950 px-6 py-2 text-xs font-semibold flex items-center justify-between border-b border-amber-600/30">
          <div className="flex items-center gap-2">
            <Eye className="w-4 h-4 text-slate-950 flex-shrink-0" />
            <span>
              Operator Preview Mode — You are previewing the client portal as <strong>{clientName}</strong>.
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/ops/dashboard"
              className="text-xs text-slate-950 underline hover:text-black font-bold"
            >
              Exit to Ops Console &rarr;
            </Link>
          </div>
        </aside>
      )}

      {/* Main Portal Header */}
      <header className="h-16 bg-white border-b border-slate-200 flex items-center px-8 flex-shrink-0 relative z-30">
        <div className="flex items-center gap-4">
          <div className="relative">
            {me?.clients && me.clients.length > 1 ? (
              <div>
                <button
                  onClick={() => setDropdownOpen(!dropdownOpen)}
                  className="font-bold text-xl tracking-tight text-slate-900 flex items-center gap-1.5 hover:text-slate-700"
                >
                  {clientName}
                  <ChevronDown className="w-4 h-4 text-slate-400" />
                </button>
                {dropdownOpen && (
                  <div className="absolute left-0 mt-2 w-56 bg-white rounded-xl shadow-lg border border-slate-200 py-1.5 z-50">
                    <div className="px-3 py-1.5 text-[11px] font-semibold uppercase text-slate-400 tracking-wider">
                      Switch Client Portal
                    </div>
                    {me.clients.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => switchClient(c.id)}
                        className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between hover:bg-slate-50 ${
                          c.id === me.active_client_id ? "font-bold text-slate-900 bg-slate-50" : "text-slate-600"
                        }`}
                      >
                        <span>{c.name}</span>
                        {c.id === me.active_client_id && (
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="font-bold text-xl tracking-tight text-slate-900">
                {clientName}
              </div>
            )}
          </div>

          <span className="text-slate-300">|</span>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 uppercase tracking-wide">
            Portal
          </span>
        </div>

        <PortalNav pendingCount={pendingCount} />

        <div className="ml-auto flex items-center space-x-4 text-sm">
          <div className="flex flex-col items-end">
            <span className="text-xs font-medium text-slate-900">{me?.email || "Signed In"}</span>
            <span
              className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded ${
                isViewer
                  ? "bg-slate-100 text-slate-600"
                  : "bg-emerald-50 text-emerald-700 border border-emerald-200"
              }`}
            >
              {isViewer ? "Viewer (Read Only)" : me?.is_preview ? "Operator Preview" : "Approver"}
            </span>
          </div>
          <div className="w-8 h-8 rounded-full bg-slate-900 text-white flex items-center justify-center font-bold text-xs uppercase shadow-xs">
            {clientName.charAt(0)}
          </div>
        </div>
      </header>
    </>
  );
}
