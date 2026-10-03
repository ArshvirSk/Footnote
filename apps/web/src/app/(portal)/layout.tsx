import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Client Portal | Footnote",
  description: "View your brand visibility and approve content.",
};

export default function PortalLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="min-h-screen bg-[#FAFAFA] flex flex-col font-sans">
      <header className="h-16 bg-white border-b border-slate-200 flex items-center px-8 flex-shrink-0">
        <div className="font-bold text-xl tracking-tight text-slate-900">Acme Corp</div>
        <nav className="ml-8 flex space-x-6 text-sm font-medium">
          <a href="/portal" className="text-slate-500 hover:text-slate-900 py-5">Overview</a>
          <a href="#" className="text-slate-500 hover:text-slate-900 py-5">Visibility</a>
          <a href="#" className="text-slate-500 hover:text-slate-900 py-5">Content</a>
          <a href="/portal/approvals" className="text-slate-500 hover:text-slate-900 py-5">Approvals <span className="ml-1 bg-blue-100 text-blue-700 py-0.5 px-2 rounded-full text-xs">2</span></a>
          <a href="/portal/settings" className="text-slate-900 border-b-2 border-slate-900 py-5">Settings</a>
        </nav>
        <div className="ml-auto flex items-center space-x-4 text-sm">
          <span className="text-slate-500">client@example.com</span>
          <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center text-slate-600 font-bold">C</div>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto p-8">
        {children}
      </main>
    </div>
  );
}
