export default function OpsDashboard() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Ops Dashboard</h1>
      <p className="text-slate-600">
        Welcome to the Footnote internal operator console. 
        Select a client from the sidebar to manage their visibility, content, and audits.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <h3 className="font-medium text-slate-900 mb-2">Pending Approvals</h3>
          <div className="text-3xl font-semibold">12</div>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <h3 className="font-medium text-slate-900 mb-2">Active Clients</h3>
          <div className="text-3xl font-semibold">4</div>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <h3 className="font-medium text-slate-900 mb-2">Collection Health</h3>
          <div className="text-3xl font-semibold text-emerald-600">99.8%</div>
        </div>
      </div>
    </div>
  );
}
