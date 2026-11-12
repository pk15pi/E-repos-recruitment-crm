import { useSyncExternalStore } from "react";

export type ApiError = {
  status: number;
  code: string;
  message: string;
  details: unknown;
};

const ACCESS = "sable.access";
const REFRESH = "sable.refresh";
const ACTIVE_ORG = "sable.activeOrg";

export function getAccess() {
  return sessionStorage.getItem(ACCESS);
}

const activeOrgListeners = new Set<() => void>();

export function getActiveOrg() {
  return localStorage.getItem(ACTIVE_ORG) ?? "";
}

export function setActiveOrg(organizationId: string) {
  const current = localStorage.getItem(ACTIVE_ORG) ?? "";
  if (current === organizationId) return;
  if (organizationId) localStorage.setItem(ACTIVE_ORG, organizationId);
  else localStorage.removeItem(ACTIVE_ORG);
  activeOrgListeners.forEach((listener) => listener());
}

export function useActiveOrg() {
  return useSyncExternalStore(
    (listener) => {
      activeOrgListeners.add(listener);
      return () => activeOrgListeners.delete(listener);
    },
    getActiveOrg,
  );
}

export function setTokens(access: string, refresh: string) {
  sessionStorage.setItem(ACCESS, access);
  sessionStorage.setItem(REFRESH, refresh);
}

export function clearTokens() {
  sessionStorage.removeItem(ACCESS);
  sessionStorage.removeItem(REFRESH);
}

function asError(status: number, data: unknown): ApiError {
  const record = data as { error?: { code?: string; message?: string; details?: unknown } } | null;
  return {
    status,
    code: record?.error?.code || "error",
    message: record?.error?.message || "Request failed.",
    details: record?.error?.details ?? {},
  };
}

async function refreshAccess(): Promise<string | null> {
  const refresh = sessionStorage.getItem(REFRESH);
  if (!refresh) return null;
  const response = await fetch("/api/v1/auth/refresh/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) {
    clearTokens();
    return null;
  }
  const data = (await response.json()) as { access: string; refresh?: string };
  sessionStorage.setItem(ACCESS, data.access);
  if (data.refresh) sessionStorage.setItem(REFRESH, data.refresh);
  return data.access;
}

type Options = RequestInit & { json?: unknown; form?: FormData };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const headers = new Headers(options.headers);
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.json);
  }
  if (options.form) body = options.form;

  const send = (access: string | null) => {
    const next = new Headers(headers);
    if (access) next.set("Authorization", `Bearer ${access}`);
    const organization = getActiveOrg();
    if (organization) next.set("X-Organization-Id", organization);
    return fetch(path, { ...options, headers: next, body });
  };

  let response = await send(getAccess());
  const canRefresh = !path.includes("/auth/login") && !path.includes("/auth/refresh");
  if (response.status === 401 && canRefresh && sessionStorage.getItem(REFRESH)) {
    const access = await refreshAccess();
    if (access) response = await send(access);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) throw asError(response.status, data);
  return data as T;
}

export function uploadFiles(
  files: File[],
  onProgress: (percent: number) => void,
): Promise<{ items: UploadItem[] }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    xhr.open("POST", "/api/v1/resumes/bulk/");
    const token = getAccess();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    const organization = getActiveOrg();
    if (organization) xhr.setRequestHeader("X-Organization-Id", organization);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      const data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(asError(xhr.status, data));
    };
    xhr.onerror = () => reject(asError(0, { error: { code: "network", message: "Upload failed." } }));
    xhr.send(form);
  });
}

export async function downloadAuthorized(path: string, filename: string) {
  const headers = new Headers();
  const access = getAccess();
  if (access) headers.set("Authorization", `Bearer ${access}`);
  const organization = getActiveOrg();
  if (organization) headers.set("X-Organization-Id", organization);
  const response = await fetch(path, { headers });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw asError(response.status, data);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export type UploadItem = {
  filename: string;
  resume_id: string | null;
  status: string;
  scan_status?: string;
  error?: string;
  duplicate_of?: string | null;
  duplicate_warning?: string | null;
};

export type Page<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export const ACTIVE_JOB_KEY = "sable.activeJob";
