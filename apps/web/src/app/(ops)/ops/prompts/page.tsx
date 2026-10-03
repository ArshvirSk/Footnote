"use client";

import { useState, useEffect } from "react";
import { Plus, Upload, MoreHorizontal, Settings, Target } from "lucide-react";

type EngineType = "chatgpt" | "gemini" | "perplexity" | "claude" | "grok" | "google_aio";

interface Prompt {
  id: string;
  text: string;
  funnel_stage: string | null;
  lead_intent_score: number | null;
  engines: EngineType[];
  is_active: boolean;
}

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // In a real app, fetch from API. 
    // Here we stub for UI demonstration purposes.
    setTimeout(() => {
      setPrompts([
        {
          id: "1",
          text: "What is the best project management tool for startups?",
          funnel_stage: "consideration",
          lead_intent_score: 75,
          engines: ["chatgpt", "gemini", "perplexity"],
          is_active: true,
        },
        {
          id: "2",
          text: "Top AI-powered marketing platforms 2025",
          funnel_stage: "awareness",
          lead_intent_score: 55,
          engines: ["chatgpt", "grok"],
          is_active: true,
        }
      ]);
      setLoading(false);
    }, 500);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Prompts</h1>
          <p className="text-slate-600 mt-1">Manage the set of buyer queries tracked daily for this client. Limit: 125 active.</p>
        </div>
        <div className="flex space-x-3">
          <button className="flex items-center px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition font-medium text-sm shadow-sm">
            <Upload className="w-4 h-4 mr-2" />
            Import CSV
          </button>
          <button className="flex items-center px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition font-medium text-sm shadow-sm">
            <Plus className="w-4 h-4 mr-2" />
            New Prompt
          </button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 text-slate-500">
            <tr>
              <th className="px-6 py-4 font-medium">Prompt Text</th>
              <th className="px-6 py-4 font-medium">Funnel</th>
              <th className="px-6 py-4 font-medium">Intent</th>
              <th className="px-6 py-4 font-medium">Engines</th>
              <th className="px-6 py-4 font-medium">Status</th>
              <th className="px-6 py-4 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-400">Loading prompts...</td>
              </tr>
            ) : prompts.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-8 text-center text-slate-400">No prompts found. Add one to get started.</td>
              </tr>
            ) : (
              prompts.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-6 py-4 font-medium text-slate-900">{p.text}</td>
                  <td className="px-6 py-4 capitalize text-slate-600">{p.funnel_stage || "—"}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center">
                      <Target className="w-4 h-4 text-emerald-500 mr-1.5" />
                      <span className="text-slate-700">{p.lead_intent_score || 0}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex gap-1.5 flex-wrap">
                      {p.engines.map(e => (
                        <span key={e} className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded text-xs capitalize border border-slate-200">
                          {e.replace('_', ' ')}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${p.is_active ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-600 border border-slate-200'}`}>
                      {p.is_active ? 'Active' : 'Retired'}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button className="text-slate-400 hover:text-slate-600 p-1 rounded hover:bg-slate-100 transition-colors">
                      <MoreHorizontal className="w-5 h-5" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
