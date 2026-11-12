export function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not provided";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function monthsLabel(months: number | null | undefined): string {
  if (months === null || months === undefined) return "Not provided";
  const years = Math.floor(months / 12);
  const rest = months % 12;
  if (years && rest) return `${years} yr ${rest} mo`;
  if (years) return `${years} yr`;
  return `${rest} mo`;
}

export function when(value: string | null | undefined): string {
  if (!value) return "Not provided";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function day(value: string | null | undefined): string {
  if (!value) return "Not provided";
  return value.slice(0, 10);
}

export function errorText(err: unknown): string {
  if (!err || typeof err !== "object") return "Something went wrong.";
  const record = err as { message?: string; details?: unknown };
  const message = record.message || "Request failed.";
  const details = record.details;
  if (details && typeof details === "object" && !Array.isArray(details)) {
    const parts = Object.entries(details as Record<string, unknown>)
      .map(([key, value]) => {
        if (value && typeof value === "object" && !Array.isArray(value)) return "";
        const text = Array.isArray(value) ? value.map(String).join(" ") : String(value ?? "");
        return text ? `${key.replaceAll("_", " ")}: ${text}` : "";
      })
      .filter(Boolean);
    if (parts.length) return `${message} ${parts.join(" ")}`;
  }
  return message;
}

export const STAGES = [
  "sourced",
  "screened",
  "shortlisted",
  "submitted",
  "interview",
  "offer",
  "hired",
  "rejected",
  "withdrawn",
  "on_hold",
  "closed",
] as const;

export const WORK_MODES = ["remote", "hybrid", "onsite"] as const;
export const EMPLOYMENT = ["full_time", "part_time", "contract", "internship", "temporary"] as const;
export const CANDIDATE_STATUSES = ["new", "active", "passive", "placed", "do_not_contact", "archived"] as const;

export function labelize(value: string): string {
  return value.replaceAll("_", " ");
}
