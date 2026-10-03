"use client";

import { TrendingUp, FileCheck, Target, ArrowUpRight } from "lucide-react";

export default function AnalyticsPage() {
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Analytics & ROI</h1>
          <p className="text-slate-600 mt-1">Measure the impact of published content on AI visibility.</p>
        </div>
        <select className="px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg text-sm font-medium outline-none">
          <option>Last 30 Days</option>
          <option>Last 90 Days</option>
          <option>Year to Date</option>
        </select>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center text-sm font-medium text-slate-500 mb-4">
            <FileCheck className="w-4 h-4 mr-2" /> Content Published
          </div>
          <div className="text-3xl font-semibold text-slate-900">24</div>
          <div className="text-sm text-emerald-600 font-medium mt-2 flex items-center">
            <TrendingUp className="w-3 h-3 mr-1" /> +12% MoM
          </div>
        </div>

        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center text-sm font-medium text-slate-500 mb-4">
            <Target className="w-4 h-4 mr-2" /> Gaps Closed
          </div>
          <div className="text-3xl font-semibold text-slate-900">18</div>
          <div className="text-sm text-slate-400 mt-2">Recovered from competitors</div>
        </div>

        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center text-sm font-medium text-slate-500 mb-4">
            <ArrowUpRight className="w-4 h-4 mr-2" /> AI Mentions Gained
          </div>
          <div className="text-3xl font-semibold text-slate-900">142</div>
          <div className="text-sm text-emerald-600 font-medium mt-2 flex items-center">
            <TrendingUp className="w-3 h-3 mr-1" /> +34% MoM
          </div>
        </div>
        
        <div className="bg-emerald-50 p-6 rounded-xl border border-emerald-100 shadow-sm">
          <div className="flex items-center text-sm font-medium text-emerald-800 mb-4">
            Estimated Traffic ROI
          </div>
          <div className="text-3xl font-semibold text-emerald-900">+4,200</div>
          <div className="text-sm text-emerald-700 mt-2">Visits from AI referrals</div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 mt-8 h-96 flex flex-col justify-center items-center text-slate-400">
        {/* Placeholder for Recharts area chart */}
        <p className="font-medium text-slate-500">Mentions vs Content Output Chart</p>
        <p className="text-sm mt-2">Recharts AreaChart component will render here</p>
      </div>
      
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden mt-8">
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50">
          <h3 className="font-medium text-slate-900">Recently Closed Gaps</h3>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="bg-white border-b border-slate-100 text-slate-500">
            <tr>
              <th className="px-6 py-3 font-medium">Prompt</th>
              <th className="px-6 py-3 font-medium">Published URL</th>
              <th className="px-6 py-3 font-medium">Verified On</th>
              <th className="px-6 py-3 font-medium">Impact</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            <tr className="hover:bg-slate-50/50">
              <td className="px-6 py-4 font-medium text-slate-900">Best AI CRM</td>
              <td className="px-6 py-4 text-blue-600 hover:underline">/blog/best-ai-crm</td>
              <td className="px-6 py-4 text-slate-500">Oct 1, 2026</td>
              <td className="px-6 py-4"><span className="text-emerald-600 font-medium">Rank 1 (ChatGPT)</span></td>
            </tr>
            <tr className="hover:bg-slate-50/50">
              <td className="px-6 py-4 font-medium text-slate-900">Enterprise project management</td>
              <td className="px-6 py-4 text-blue-600 hover:underline">/guides/enterprise-pm</td>
              <td className="px-6 py-4 text-slate-500">Sep 28, 2026</td>
              <td className="px-6 py-4"><span className="text-emerald-600 font-medium">Mention Gained</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
