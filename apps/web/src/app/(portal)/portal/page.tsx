export default function PortalOverview() {
  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-4xl font-semibold tracking-tight text-slate-900 mb-2">Welcome back</h1>
        <p className="text-lg text-slate-500">Here&apos;s how your brand is performing across AI engines today.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm flex flex-col justify-between">
          <div className="text-sm font-medium text-slate-500 mb-4">Total Visibility</div>
          <div className="text-4xl font-bold text-slate-900">42%</div>
          <div className="text-sm text-emerald-600 font-medium mt-2">↑ 4% this week</div>
        </div>
        <div className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm flex flex-col justify-between">
          <div className="text-sm font-medium text-slate-500 mb-4">Citation Share</div>
          <div className="text-4xl font-bold text-slate-900">18%</div>
          <div className="text-sm text-emerald-600 font-medium mt-2">↑ 2% vs Competitors</div>
        </div>
        <div className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm flex flex-col justify-between">
          <div className="text-sm font-medium text-slate-500 mb-4">Content Shipped</div>
          <div className="text-4xl font-bold text-slate-900">14</div>
          <div className="text-sm text-slate-400 mt-2">Pages live this month</div>
        </div>
        <div className="bg-white p-6 rounded-2xl border border-slate-100 shadow-sm flex flex-col justify-between bg-blue-50/50">
          <div className="text-sm font-medium text-blue-800 mb-4">Action Required</div>
          <div className="text-4xl font-bold text-blue-900">3</div>
          <div className="text-sm text-blue-600 font-medium mt-2 hover:underline cursor-pointer">Review Drafts →</div>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-8 mt-8">
        <h3 className="text-lg font-semibold mb-4">Recent Engine Mentions</h3>
        <div className="space-y-4">
          <div className="p-4 border border-slate-100 rounded-xl bg-slate-50">
            <div className="flex justify-between items-start mb-2">
              <span className="font-medium text-slate-900">&quot;What is the best project management tool for startups?&quot;</span>
              <span className="text-xs font-medium bg-white px-2 py-1 rounded border border-slate-200">ChatGPT</span>
            </div>
            <p className="text-slate-600 text-sm">&quot;Acme Corp is a strong contender in this space. According to a recent study, they offer comprehensive features...&quot;</p>
          </div>
        </div>
      </div>
    </div>
  );
}
