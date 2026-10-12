"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  Eye,
  FileCode,
  FileText,
  GitCompare,
  History,
  Layers,
  Loader2,
  MessageSquare,
  PenTool,
  Save,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import {
  contentApi,
  ContentItem,
  ContentVersion,
  getDefaultClientId,
  VersionDiffResponse,
} from "@/lib/api";

export default function ContentWorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const itemId = resolvedParams.id;

  const [clientId, setClientId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const [item, setItem] = useState<ContentItem | null>(null);
  const [activeTab, setActiveTab] = useState<"editor" | "claims" | "diff" | "brief">("editor");

  // Editor state
  const [editorTitle, setEditorTitle] = useState("");
  const [editorMd, setEditorMd] = useState("");
  const [editorPreview, setEditorPreview] = useState<"split" | "edit" | "preview">("split");

  // Diff state
  const [diffV1, setDiffV1] = useState<number>(1);
  const [diffV2, setDiffV2] = useState<number>(2);
  const [diffData, setDiffData] = useState<VersionDiffResponse | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  // Approval modal
  const [showApprovalModal, setShowApprovalModal] = useState(false);
  const [approvalAction, setApprovalAction] = useState<"approve" | "reject" | "request_changes">("approve");
  const [approvalComment, setApprovalComment] = useState("");

  const loadItem = async (cid: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await contentApi.getItem(cid, itemId);
      setItem(data);
      if (data.current_version) {
        setEditorTitle(data.current_version.title || data.title || "");
        setEditorMd(data.current_version.body_md || "");
      }
      if (data.versions && data.versions.length >= 2) {
        setDiffV1(data.versions[1].version_no);
        setDiffV2(data.versions[0].version_no);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load content workspace");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    getDefaultClientId()
      .then((cid) => {
        setClientId(cid);
        return loadItem(cid);
      })
      .catch((err) => {
        setError(err.message || "Failed to resolve active client");
        setLoading(false);
      });
  }, [itemId]);

  const handleSaveRevision = async () => {
    if (!clientId) return;
    try {
      setActionLoading("save-version");
      await contentApi.createVersion(clientId, itemId, {
        title: editorTitle,
        body_md: editorMd,
        claims: item?.current_version?.claims || [],
      });
      setNotice("Revision saved as new version! Reset to in-review for signoff.");
      await loadItem(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to save revision");
    } finally {
      setActionLoading(null);
    }
  };

  const handleLoadDiff = async () => {
    if (!clientId) return;
    try {
      setDiffLoading(true);
      const res = await contentApi.diffVersions(clientId, itemId, diffV1, diffV2);
      setDiffData(res);
    } catch (err: any) {
      setError(err?.message || "Failed to compute version diff");
    } finally {
      setDiffLoading(false);
    }
  };

  const handleDecideApproval = async () => {
    if (!clientId || !item?.current_version?.approval_id) return;
    try {
      setActionLoading("approval-action");
      await contentApi.actionApproval(
        clientId,
        item.current_version.approval_id,
        approvalAction,
        approvalComment || undefined
      );
      setShowApprovalModal(false);
      setApprovalComment("");
      setNotice(`Approval decided: ${approvalAction}`);
      await loadItem(clientId);
    } catch (err: any) {
      setError(err?.message || "Failed to decide approval");
    } finally {
      setActionLoading(null);
    }
  };

  const handlePublish = async () => {
    if (!clientId) return;
    try {
      setActionLoading("publish");
      await contentApi.updateItem(clientId, itemId, { status: "published" });
      setNotice("Content published successfully!");
      await loadItem(clientId);
    } catch (err: any) {
      setError(err?.message || "Publish blocked: Ensure version approval gate is signed off.");
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && !item) {
    return (
      <div className="h-96 flex flex-col items-center justify-center text-slate-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin text-slate-600" />
        <span className="text-sm font-medium">Loading content item & versions...</span>
      </div>
    );
  }

  const currentVer = item?.current_version;
  const isApproved = item?.status === "approved";
  const isPublished = item?.status === "published";
  const pendingApproval = currentVer?.approval_status === "pending";

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* Top Breadcrumb & Status Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <Link
            href="/ops/pipeline"
            className="p-1.5 rounded-lg border border-slate-200 text-slate-500 hover:text-slate-900 hover:bg-slate-50 transition"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-slate-900 leading-tight">
                {item?.title || "Content Item"}
              </h1>
              <span
                className={`text-xs font-semibold px-2 py-0.5 rounded capitalize ${
                  item?.status === "approved"
                    ? "bg-emerald-100 text-emerald-800"
                    : item?.status === "published"
                    ? "bg-blue-100 text-blue-800"
                    : item?.status === "in_review"
                    ? "bg-amber-100 text-amber-800"
                    : "bg-slate-100 text-slate-700"
                }`}
              >
                {item?.status?.replace("_", " ")}
              </span>
              {currentVer && (
                <span className="text-xs font-mono bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded border border-slate-200">
                  v{currentVer.version_no} ({currentVer.author_kind})
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Type: <span className="font-medium text-slate-700 uppercase">{item?.type}</span> &bull; Slug:{" "}
              <code className="text-slate-600">/{item?.slug || "pending"}</code>
            </p>
          </div>
        </div>

        {/* Action button bar */}
        <div className="flex items-center gap-2">
          {pendingApproval && (
            <button
              onClick={() => {
                setApprovalAction("approve");
                setShowApprovalModal(true);
              }}
              className="inline-flex items-center px-3.5 py-1.5 bg-emerald-600 text-white rounded-lg text-xs font-medium hover:bg-emerald-700 shadow-sm transition"
            >
              <ShieldCheck className="w-3.5 h-3.5 mr-1.5" />
              Signoff Gate
            </button>
          )}

          {isApproved && (
            <button
              onClick={handlePublish}
              disabled={actionLoading === "publish"}
              className="inline-flex items-center px-3.5 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 shadow-sm transition disabled:opacity-50"
            >
              {actionLoading === "publish" ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
              ) : (
                <Send className="w-3.5 h-3.5 mr-1.5" />
              )}
              Publish Content
            </button>
          )}

          {isPublished && item?.published_url && (
            <a
              href={item.published_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center px-3.5 py-1.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-lg text-xs font-medium hover:bg-blue-100 shadow-2xs transition"
            >
              <ExternalLink className="w-3.5 h-3.5 mr-1.5" />
              View Live URL
            </a>
          )}
        </div>
      </div>

      {/* Alerts */}
      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-2.5 rounded-xl text-xs flex items-center justify-between shadow-2xs animate-in fade-in">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span>{notice}</span>
          </div>
          <button onClick={() => setNotice(null)} className="text-emerald-600 hover:text-emerald-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 px-4 py-2.5 rounded-xl text-xs flex items-center justify-between shadow-2xs animate-in fade-in">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex items-center space-x-1 border-b border-slate-200 text-xs font-medium">
        <button
          onClick={() => setActiveTab("editor")}
          className={`px-4 py-2.5 border-b-2 transition flex items-center gap-1.5 ${
            activeTab === "editor"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <PenTool className="w-3.5 h-3.5" />
          Draft Editor & Preview
        </button>

        <button
          onClick={() => setActiveTab("claims")}
          className={`px-4 py-2.5 border-b-2 transition flex items-center gap-1.5 ${
            activeTab === "claims"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <ShieldCheck className="w-3.5 h-3.5" />
          Claims & Grounding ({currentVer?.claims?.length || 0})
        </button>

        <button
          onClick={() => {
            setActiveTab("diff");
            if (!diffData && item?.versions && item.versions.length >= 2) {
              handleLoadDiff();
            }
          }}
          className={`px-4 py-2.5 border-b-2 transition flex items-center gap-1.5 ${
            activeTab === "diff"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <GitCompare className="w-3.5 h-3.5" />
          Version Diff ({item?.versions?.length || 1} versions)
        </button>

        <button
          onClick={() => setActiveTab("brief")}
          className={`px-4 py-2.5 border-b-2 transition flex items-center gap-1.5 ${
            activeTab === "brief"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Layers className="w-3.5 h-3.5" />
          Grounding Brief
        </button>
      </div>

      {/* TAB 1: DRAFT EDITOR */}
      {activeTab === "editor" && (
        <div className="space-y-4">
          {/* Metadata bar */}
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-3 flex flex-wrap items-center justify-between gap-4 text-xs text-slate-600">
            <div className="flex items-center gap-4">
              <span>
                <strong>Words:</strong> {currentVer?.word_count || 0}
              </span>
              <span>
                <strong>Est. Read:</strong> {currentVer?.reading_time_min || 0} min
              </span>
              <span>
                <strong>Author:</strong>{" "}
                <span className="capitalize">{currentVer?.author_kind || "agent"}</span>
              </span>
              <span>
                <strong>Gate Status:</strong>{" "}
                <span
                  className={`font-semibold capitalize ${
                    currentVer?.approval_status === "approved"
                      ? "text-emerald-700"
                      : "text-amber-700"
                  }`}
                >
                  {currentVer?.approval_status || "pending"}
                </span>
              </span>
            </div>

            <div className="flex items-center gap-2">
              <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
                <button
                  onClick={() => setEditorPreview("edit")}
                  className={`px-2.5 py-1 rounded text-xs font-medium ${
                    editorPreview === "edit" ? "bg-slate-900 text-white" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  Edit
                </button>
                <button
                  onClick={() => setEditorPreview("split")}
                  className={`px-2.5 py-1 rounded text-xs font-medium ${
                    editorPreview === "split" ? "bg-slate-900 text-white" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  Split
                </button>
                <button
                  onClick={() => setEditorPreview("preview")}
                  className={`px-2.5 py-1 rounded text-xs font-medium ${
                    editorPreview === "preview" ? "bg-slate-900 text-white" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  Preview
                </button>
              </div>

              <button
                onClick={handleSaveRevision}
                disabled={actionLoading === "save-version"}
                className="inline-flex items-center px-3.5 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 shadow-sm transition disabled:opacity-50"
              >
                {actionLoading === "save-version" ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                ) : (
                  <Save className="w-3.5 h-3.5 mr-1.5" />
                )}
                Save Revision (New Version)
              </button>
            </div>
          </div>

          {/* Title editor */}
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Article Title</label>
            <input
              type="text"
              value={editorTitle}
              onChange={(e) => setEditorTitle(e.target.value)}
              className="w-full px-3.5 py-2 border border-slate-200 rounded-xl text-base font-semibold focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
            />
          </div>

          {/* Editor split/single pane */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {(editorPreview === "split" || editorPreview === "edit") && (
              <div className="flex flex-col">
                <div className="text-xs font-semibold text-slate-500 mb-1 flex items-center justify-between">
                  <span>MARKDOWN SOURCE</span>
                  <span>{editorMd.length} characters</span>
                </div>
                <textarea
                  rows={26}
                  value={editorMd}
                  onChange={(e) => setEditorMd(e.target.value)}
                  className="w-full p-4 border border-slate-200 rounded-xl font-mono text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900 resize-y shadow-2xs"
                />
              </div>
            )}

            {(editorPreview === "split" || editorPreview === "preview") && (
              <div className="flex flex-col">
                <div className="text-xs font-semibold text-slate-500 mb-1 flex items-center justify-between">
                  <span>FORMATTED PREVIEW</span>
                  <span>HTML rendering</span>
                </div>
                <div className="p-6 border border-slate-200 rounded-xl bg-white overflow-y-auto max-h-[600px] shadow-2xs prose prose-sm max-w-none text-slate-800">
                  <h1 className="text-2xl font-bold mb-4 text-slate-900">{editorTitle}</h1>
                  <div className="whitespace-pre-wrap font-sans text-sm leading-relaxed space-y-4">
                    {editorMd.split("\n\n").map((para, i) => {
                      if (para.startsWith("# ")) {
                        return (
                          <h1 key={i} className="text-xl font-bold text-slate-900 border-b pb-1">
                            {para.replace("# ", "")}
                          </h1>
                        );
                      }
                      if (para.startsWith("## ")) {
                        return (
                          <h2 key={i} className="text-lg font-bold text-slate-800 mt-4">
                            {para.replace("## ", "")}
                          </h2>
                        );
                      }
                      if (para.startsWith("- ") || para.startsWith("* ")) {
                        return (
                          <ul key={i} className="list-disc pl-5 space-y-1 text-slate-700">
                            {para.split("\n").map((li, j) => (
                              <li key={j}>{li.replace(/^[-*]\s+/, "")}</li>
                            ))}
                          </ul>
                        );
                      }
                      return <p key={i}>{para}</p>;
                    })}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: CLAIMS & CITATIONS */}
      {activeTab === "claims" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold text-slate-900">Extracted Claims & Sources</h3>
              <p className="text-xs text-slate-500">
                AEO algorithms favor content where every specific claim has an attributable source.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {(!currentVer?.claims || currentVer.claims.length === 0) ? (
              <div className="col-span-2 p-8 border border-dashed border-slate-200 rounded-2xl text-center text-slate-400 text-sm">
                No claims extracted yet for this version.
              </div>
            ) : (
              currentVer.claims.map((claim, idx) => (
                <div
                  key={idx}
                  className="bg-white p-4 border border-slate-200 rounded-xl shadow-2xs flex flex-col justify-between space-y-3"
                >
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        Claim #{idx + 1}
                      </span>
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                          claim.status === "verified"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {claim.status || "unsourced"}
                      </span>
                    </div>
                    <p className="text-sm font-medium text-slate-800">
                      "{claim.text || claim.claim}"
                    </p>
                  </div>

                  <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
                    <span className="truncate max-w-[200px]">
                      Source: <strong>{claim.source || "Client proof points"}</strong>
                    </span>
                    <button
                      onClick={() => setNotice(`Claim #${idx + 1} marked verified in session.`)}
                      className="text-xs text-emerald-700 font-medium hover:underline flex items-center gap-1"
                    >
                      <Check className="w-3 h-3" /> Verify
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* TAB 3: VERSION DIFF */}
      {activeTab === "diff" && (
        <div className="space-y-4">
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="text-xs font-semibold text-slate-700">Compare Versions:</span>
              <div className="flex items-center gap-2 text-xs">
                <span>Base (v1):</span>
                <select
                  value={diffV1}
                  onChange={(e) => setDiffV1(Number(e.target.value))}
                  className="px-2.5 py-1 border border-slate-300 rounded-lg bg-white"
                >
                  {item?.versions?.map((v) => (
                    <option key={v.version_no} value={v.version_no}>
                      v{v.version_no} - {v.title.slice(0, 30)}
                    </option>
                  ))}
                </select>

                <span>Target (v2):</span>
                <select
                  value={diffV2}
                  onChange={(e) => setDiffV2(Number(e.target.value))}
                  className="px-2.5 py-1 border border-slate-300 rounded-lg bg-white"
                >
                  {item?.versions?.map((v) => (
                    <option key={v.version_no} value={v.version_no}>
                      v{v.version_no} - {v.title.slice(0, 30)}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <button
              onClick={handleLoadDiff}
              disabled={diffLoading}
              className="inline-flex items-center px-3.5 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 shadow-sm transition disabled:opacity-50"
            >
              {diffLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <GitCompare className="w-3.5 h-3.5 mr-1.5" />}
              Generate Diff
            </button>
          </div>

          {diffData && (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-2xs">
              <div className="px-4 py-2.5 bg-slate-100/70 border-b border-slate-200 flex items-center justify-between text-xs text-slate-600">
                <span>
                  Diff between <strong>v{diffData.v1}</strong> and <strong>v{diffData.v2}</strong>
                </span>
                <span>
                  Word count change:{" "}
                  <strong
                    className={
                      diffData.word_count_change >= 0 ? "text-emerald-700" : "text-rose-700"
                    }
                  >
                    {diffData.word_count_change >= 0 ? `+${diffData.word_count_change}` : diffData.word_count_change}
                  </strong>
                </span>
              </div>

              <div className="p-4 font-mono text-xs overflow-x-auto max-h-[500px] space-y-0.5 bg-slate-950 text-slate-100">
                {diffData.diff.length === 0 ? (
                  <div className="text-slate-400 py-4 text-center font-sans">
                    No textual differences between selected versions.
                  </div>
                ) : (
                  diffData.diff.map((line, idx) => {
                    const isAdd = line.startsWith("+") && !line.startsWith("+++");
                    const isRem = line.startsWith("-") && !line.startsWith("---");
                    const isHdr = line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++");

                    return (
                      <div
                        key={idx}
                        className={`px-2 py-0.5 rounded-xs ${
                          isAdd
                            ? "bg-emerald-950/80 text-emerald-300 font-semibold"
                            : isRem
                            ? "bg-rose-950/80 text-rose-300 line-through font-semibold"
                            : isHdr
                            ? "text-blue-400 font-bold"
                            : "text-slate-400"
                        }`}
                      >
                        {line}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 4: GROUNDING BRIEF */}
      {activeTab === "brief" && (
        <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-2xs space-y-6">
          <div>
            <h3 className="text-lg font-bold text-slate-900">
              {item?.brief?.title || "Associated Brief"}
            </h3>
            {item?.brief?.angle && (
              <p className="text-sm text-slate-600 mt-1 italic">
                "{item.brief.angle}"
              </p>
            )}
          </div>

          {/* Outline section */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
              Strategic Outline
            </h4>
            <div className="space-y-3">
              {item?.brief?.outline?.map((section: any, idx: number) => (
                <div key={idx} className="p-3 bg-slate-50 border border-slate-200 rounded-xl">
                  <h5 className="font-semibold text-slate-800 text-sm mb-1.5">
                    {section.heading || `Section ${idx + 1}`}
                  </h5>
                  <ul className="list-disc pl-5 text-xs text-slate-600 space-y-1">
                    {section.points?.map((pt: string, j: number) => (
                      <li key={j}>{pt}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          {/* Target Prompts */}
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
              Target Prompts & Queries
            </h4>
            <div className="flex flex-wrap gap-2">
              {item?.prompts?.map((p) => (
                <span
                  key={p.id}
                  className="px-3 py-1 bg-blue-50 text-blue-800 border border-blue-200 rounded-lg text-xs font-medium"
                >
                  {p.text}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Approval Decision Modal */}
      {showApprovalModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-xl overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-slate-900">Approval Gate Signoff</h3>
                <p className="text-xs text-slate-500">
                  Enforces strict human verification before content can be published.
                </p>
              </div>
              <button
                onClick={() => setShowApprovalModal(false)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-2">
                  Review Decision *
                </label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setApprovalAction("approve")}
                    className={`py-2 px-3 rounded-lg text-xs font-medium border flex items-center justify-center gap-1 transition ${
                      approvalAction === "approve"
                        ? "bg-emerald-600 text-white border-emerald-600"
                        : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <Check className="w-3.5 h-3.5" /> Approve
                  </button>
                  <button
                    type="button"
                    onClick={() => setApprovalAction("request_changes")}
                    className={`py-2 px-3 rounded-lg text-xs font-medium border flex items-center justify-center gap-1 transition ${
                      approvalAction === "request_changes"
                        ? "bg-amber-600 text-white border-amber-600"
                        : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <MessageSquare className="w-3.5 h-3.5" /> Revisions
                  </button>
                  <button
                    type="button"
                    onClick={() => setApprovalAction("reject")}
                    className={`py-2 px-3 rounded-lg text-xs font-medium border flex items-center justify-center gap-1 transition ${
                      approvalAction === "reject"
                        ? "bg-rose-600 text-white border-rose-600"
                        : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                    }`}
                  >
                    <X className="w-3.5 h-3.5" /> Reject
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Reviewer Notes / Feedback
                </label>
                <textarea
                  rows={3}
                  value={approvalComment}
                  onChange={(e) => setApprovalComment(e.target.value)}
                  placeholder="e.g. All facts verified against customer benchmark. Ready for client review."
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-900/10 focus:border-slate-900"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowApprovalModal(false)}
                  className="px-4 py-2 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleDecideApproval}
                  disabled={actionLoading === "approval-action"}
                  className="px-4 py-2 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 shadow-sm flex items-center gap-1.5 disabled:opacity-50"
                >
                  {actionLoading === "approval-action" ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Check className="w-3.5 h-3.5" />
                  )}
                  Confirm Decision
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
