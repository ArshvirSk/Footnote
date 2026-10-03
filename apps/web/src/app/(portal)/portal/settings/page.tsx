"use client";

import { Key, Copy, Check, RefreshCw } from "lucide-react";
import { useState } from "react";

export default function ClientSettingsPage() {
  const [copied, setCopied] = useState(false);

  const copyKey = () => {
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 max-w-4xl">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 mb-2">Settings</h1>
        <p className="text-slate-500">Manage your brand's preferences and realtime data feeds.</p>
      </div>

      <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900 mb-4">Realtime Edge Feeds</h3>
        <p className="text-sm text-slate-600 mb-6">
          Provide this API endpoint and key to ChatGPT Plugins, custom GPTs, or internal AI agents to grant them secure, realtime access to your approved brand content.
        </p>
        
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Endpoint URL</label>
            <div className="flex bg-slate-50 border border-slate-200 rounded-lg p-3 text-sm text-slate-700 font-mono">
              https://feeds.footnote.dev/search
            </div>
          </div>
          
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">Bearer API Key</label>
            <div className="flex items-center">
              <div className="flex-1 flex bg-slate-50 border border-slate-200 rounded-l-lg p-3 text-sm text-slate-700 font-mono overflow-hidden whitespace-nowrap overflow-ellipsis">
                fn_edge_98f828a2b37c4e518c991a0b5a
              </div>
              <button 
                onClick={copyKey}
                className="flex items-center justify-center px-4 py-3 bg-white border border-y-slate-200 border-r-slate-200 rounded-r-lg text-slate-600 hover:bg-slate-50 transition"
              >
                {copied ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center text-sm text-blue-600 font-medium hover:underline cursor-pointer">
          <RefreshCw className="w-4 h-4 mr-2" /> Rotate API Key
        </div>
      </div>
    </div>
  );
}
