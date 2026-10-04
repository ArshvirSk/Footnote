import type { Metadata } from "next";
import OpsHeader from "./OpsHeader";
import OpsSidebar from "./OpsSidebar";

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
      <OpsSidebar />

      {/* Main content */}
      <main className="flex-1 flex flex-col">
        <OpsHeader />
        <div className="flex-1 p-8 overflow-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
