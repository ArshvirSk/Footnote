import type { Metadata } from "next";
import PortalNav from "./PortalNav";

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
        <PortalNav />
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
