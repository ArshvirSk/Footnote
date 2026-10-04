/** Shared presentation helpers (design tokens already used across the console). */

export function statusBadgeClass(status: string): string {
  switch (status) {
    case "active":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "onboarding":
      return "bg-amber-50 text-amber-700 border-amber-200";
    case "paused":
      return "bg-slate-100 text-slate-600 border-slate-200";
    case "churned":
      return "bg-rose-50 text-rose-700 border-rose-200";
    default:
      return "bg-slate-100 text-slate-600 border-slate-200";
  }
}

export function severityBadgeClass(severity: string): string {
  switch (severity) {
    case "critical":
      return "bg-rose-50 text-rose-700 border-rose-200";
    case "high":
      return "bg-orange-50 text-orange-700 border-orange-200";
    case "medium":
      return "bg-amber-50 text-amber-700 border-amber-200";
    default:
      return "bg-slate-50 text-slate-600 border-slate-200";
  }
}

export function severityDotClass(severity: string): string {
  switch (severity) {
    case "critical":
      return "bg-rose-500";
    case "high":
      return "bg-orange-500";
    case "medium":
      return "bg-amber-500";
    default:
      return "bg-slate-400";
  }
}

export function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}
