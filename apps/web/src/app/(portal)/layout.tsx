import type { Metadata } from "next";
import PortalHeader from "./PortalHeader";

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
      <PortalHeader />
      <main className="flex-1 max-w-7xl w-full mx-auto p-8">
        {children}
      </main>
    </div>
  );
}
