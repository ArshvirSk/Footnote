"use client";

import { Key, HardDrive } from "lucide-react";

export default function AdminSettingsPage() {
  return (
    <div className="space-y-6 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Admin Settings</h1>
        <p className="text-slate-600 mt-1">Configure global application settings and platform API keys.</p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center">
          <Key className="w-5 h-5 text-slate-500 mr-2" />
          <h3 className="font-semibold text-slate-900">Engine API Keys</h3>
        </div>
        <div className="p-6 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
            <div className="md:col-span-1">
              <label className="font-medium text-slate-700 text-sm">OpenAI API Key</label>
              <p className="text-xs text-slate-500 mt-0.5">Used for ChatGPT search tracking.</p>
            </div>
            <div className="md:col-span-2 flex space-x-2">
              <input type="password" value="sk-proj-**********************" readOnly className="flex-1 px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-500 outline-none focus:border-blue-500" />
              <button className="px-4 py-2 bg-white border border-slate-200 text-slate-700 rounded-lg hover:bg-slate-50 transition text-sm font-medium">Update</button>
            </div>
          </div>
          
          <hr className="border-slate-100" />
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
            <div className="md:col-span-1">
              <label className="font-medium text-slate-700 text-sm">Perplexity API Key</label>
            </div>
            <div className="md:col-span-2 flex space-x-2">
              <input type="password" placeholder="Enter pplx-... key" className="flex-1 px-3 py-2 bg-white border border-slate-300 rounded-lg text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500" />
              <button className="px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition text-sm font-medium">Save</button>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center">
          <HardDrive className="w-5 h-5 text-slate-500 mr-2" />
          <h3 className="font-semibold text-slate-900">Edge Search Proxies</h3>
        </div>
        <div className="p-6">
          <p className="text-sm text-slate-600 mb-4">Manage Cloudflare KV bindings for the realtime AI feed proxy.</p>
          <div className="p-4 border border-emerald-200 bg-emerald-50 rounded-lg flex justify-between items-center">
            <div>
              <div className="font-medium text-emerald-900">Worker Status: Active</div>
              <div className="text-xs text-emerald-700 mt-1">Version: 1.0.4 • Route: feeds.footnote.dev/*</div>
            </div>
            <button className="text-emerald-700 font-medium text-sm hover:underline">Deploy Update</button>
          </div>
        </div>
      </div>
    </div>
  );
}
