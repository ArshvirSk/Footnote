"use client";

import { FileText, MoreHorizontal, PenTool } from "lucide-react";

export default function PipelinePage() {
  const columns = [
    { name: "Gap Detected", items: [{ title: "Best AI CRM", type: "Gap" }] },
    { name: "Brief Gen (Agent)", items: [] },
    { name: "Ops Review (Brief)", items: [{ title: "Marketing Automation Tools", type: "Brief" }] },
    { name: "Client Review", items: [] },
    { name: "Draft Gen (Agent)", items: [] },
    { name: "Ops Review (Draft)", items: [{ title: "Sales Funnel 101", type: "Draft" }] },
    { name: "Published", items: [] },
  ];

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col">
      <div className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Content Pipeline</h1>
        <p className="text-slate-600 mt-1">Track content progressing through AI generation and human approval gates.</p>
      </div>

      <div className="flex-1 flex space-x-4 overflow-x-auto pb-4">
        {columns.map((col, idx) => (
          <div key={idx} className="w-72 flex-shrink-0 flex flex-col bg-slate-100/50 rounded-xl border border-slate-200/60 p-3">
            <h3 className="font-medium text-slate-700 text-sm mb-3 px-1">{col.name} <span className="text-slate-400 ml-1 font-normal">{col.items.length}</span></h3>
            <div className="flex-1 space-y-3">
              {col.items.map((item, i) => (
                <div key={i} className="bg-white p-4 rounded-lg border border-slate-200 shadow-sm hover:border-slate-300 transition-colors cursor-pointer group">
                  <div className="flex justify-between items-start mb-2">
                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                      item.type === 'Gap' ? 'bg-amber-100 text-amber-700' :
                      item.type === 'Brief' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'
                    }`}>
                      {item.type}
                    </span>
                    <button className="text-slate-300 hover:text-slate-500 opacity-0 group-hover:opacity-100 transition-opacity">
                      <MoreHorizontal className="w-4 h-4" />
                    </button>
                  </div>
                  <h4 className="font-medium text-slate-900 text-sm leading-tight">{item.title}</h4>
                  <div className="mt-3 flex items-center text-xs text-slate-400">
                    <PenTool className="w-3 h-3 mr-1" /> Agent processing
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
