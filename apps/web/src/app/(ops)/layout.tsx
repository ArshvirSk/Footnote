import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Footnote Ops Console",
  description: "Internal operations and agency dashboard",
};

export default function OpsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* Sidebar placeholder */}
      <aside className="w-64 bg-slate-900 text-slate-100 flex-shrink-0 flex flex-col">
        <div className="h-16 flex items-center px-6 font-bold text-lg border-b border-slate-800">
          Footnote Ops
        </div>
        <nav className="flex-1 p-4 space-y-2 text-sm">
          <a href="/ops" className="block px-3 py-2 rounded hover:bg-slate-800 transition-colors text-slate-400">Dashboard</a>
          <a href="/ops/analytics" className="block px-3 py-2 rounded hover:bg-slate-800 transition-colors text-slate-400">Analytics</a>
          <a href="#" className="block px-3 py-2 rounded hover:bg-slate-800 transition-colors text-slate-400">Clients</a>
          <a href="/ops/prompts" className="block px-3 py-2 rounded hover:bg-slate-800 transition-colors text-slate-400">Prompts</a>
          <a href="/ops/gaps" className="block px-3 py-2 rounded hover:bg-slate-800 transition-colors text-slate-400">Gaps & Slips</a>
          <a href="/ops/pipeline" className="block px-3 py-2 rounded hover:bg-slate-800 transition-colors text-slate-400">Content Pipeline</a>
          <a href="/ops/admin" className="block px-3 py-2 rounded bg-slate-800 text-white">Admin</a>
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col">
        <header className="h-16 bg-white border-b border-slate-200 flex items-center px-8 shadow-sm">
          <div className="font-semibold text-slate-700">Acme Corp</div>
          <div className="ml-auto text-sm text-slate-500">operator@footnote.dev</div>
        </header>
        <div className="flex-1 p-8 overflow-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
