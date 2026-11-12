import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Empty, ErrorState, Loading } from "../components/states";
import { Badge, Button, Card, Input, Select, Textarea } from "../components/ui";
import { api, type Page } from "../lib/api";
import { isAdmin, useAuth } from "../lib/auth";
import { errorText, labelize, when } from "../lib/format";
import type { Company } from "../lib/types";

type Member = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
};

export function UsersPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["users"], queryFn: () => api<Member[]>("/api/v1/admin/users/") });
  const companies = useQuery({ queryKey: ["clients"], queryFn: () => api<Company[]>("/api/v1/clients/") });
  const [form, setForm] = useState({ email: "", full_name: "", role: "recruiter", password: "", client_company_id: "" });
  const [error, setError] = useState("");
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">People and roles</h1>
      <p className="text-sm text-muted">Roles are enforced on the server for every list, file, and search result.</p>
      <Card className="grid gap-2 md:grid-cols-2">
        <Input aria-label="Full name" placeholder="Full name" value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} />
        <Input aria-label="Email" placeholder="Email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
        <Input aria-label="Temporary password" type="password" placeholder="Temporary password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
        <Select label="Role" value={form.role} onChange={(value) => setForm({ ...form, role: value })}>
          <option value="agency_admin">Agency admin</option>
          <option value="recruiter">Recruiter</option>
          <option value="client_admin">Client admin</option>
          <option value="client_hiring_manager">Client hiring manager</option>
        </Select>
        {form.role.startsWith("client") ? (
          <Select label="Client company" value={form.client_company_id} onChange={(value) => setForm({ ...form, client_company_id: value })}>
            <option value="">Choose</option>
            {companies.data?.filter((company) => !company.is_global).map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
          </Select>
        ) : null}
        {error ? <ErrorState message={error} /> : null}
        <Button onClick={async () => {
          setError("");
          try {
            await api("/api/v1/admin/users/", { method: "POST", json: form });
            setForm({ email: "", full_name: "", role: "recruiter", password: "", client_company_id: "" });
            client.invalidateQueries({ queryKey: ["users"] });
          } catch (err) {
            setError(errorText(err));
          }
        }}>Create user</Button>
      </Card>
      {query.isLoading ? <Loading /> : null}
      {query.isError ? <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} /> : null}
      <ul className="grid gap-2">
        {query.data?.map((member) => (
          <li key={member.id}>
            <Card className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p>{member.full_name}</p>
                <p className="text-sm text-muted">{member.email}</p>
              </div>
              <Select label="Role" value={member.role} onChange={async (role) => {
                await api(`/api/v1/admin/users/${member.id}/`, { method: "PATCH", json: { role } });
                client.invalidateQueries({ queryKey: ["users"] });
              }}>
                <option value="agency_admin">Agency admin</option>
                <option value="recruiter">Recruiter</option>
                <option value="client_admin">Client admin</option>
                <option value="client_hiring_manager">Client hiring manager</option>
              </Select>
              <Button size="sm" variant="outline" onClick={async () => {
                await api(`/api/v1/admin/users/${member.id}/`, { method: "PATCH", json: { is_active: !member.is_active } });
                client.invalidateQueries({ queryKey: ["users"] });
              }}>{member.is_active ? "Deactivate" : "Activate"}</Button>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Proc = {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string;
  provider: string;
  created_at: string;
};

export function ProcessingPage() {
  const client = useQueryClient();
  const [status, setStatus] = useState("");
  const query = useQuery({
    queryKey: ["processing", status],
    queryFn: () => api<Page<Proc>>(`/api/v1/admin/processing-jobs/${status ? `?status=${status}` : ""}`),
    refetchInterval: 4000,
  });
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Processing queue</h1>
      <p className="text-sm text-muted">Parsing, embeddings, and matching run in the background. Failed jobs can be retried. This list refreshes on its own.</p>
      <Select label="Status" value={status} onChange={setStatus}>
        <option value="">All</option>
        {["queued", "running", "succeeded", "failed"].map((item) => <option key={item} value={item}>{item}</option>)}
      </Select>
      {query.isLoading ? <Loading /> : null}
      {query.isError ? <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} /> : null}
      {query.data?.results.length === 0 ? <Empty title="Queue is clear" body="Uploads and job-description analysis show up here." /> : null}
      <ul className="grid gap-2">
        {query.data?.results.map((job) => (
          <li key={job.id}>
            <Card className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p>{labelize(job.kind)} · {job.provider || "provider not recorded"}</p>
                <p className="text-sm text-muted">{when(job.created_at)} · attempt {job.attempts}/{job.max_attempts}</p>
                {job.last_error ? <p className="text-sm text-danger">{job.last_error}</p> : null}
              </div>
              <Badge tone={job.status === "failed" ? "bad" : job.status === "succeeded" ? "good" : "warn"}>{job.status}</Badge>
              {job.status === "failed" ? <Button size="sm" onClick={async () => {
                await api(`/api/v1/admin/processing-jobs/${job.id}/retry/`, { method: "POST" });
                client.invalidateQueries({ queryKey: ["processing"] });
              }}>Retry</Button> : null}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReportsPage() {
  const query = useQuery({
    queryKey: ["reports"],
    queryFn: () => api<{ pipeline: { stage: string; count: number }[]; sources?: { source: string; count: number }[]; verification?: { verification_status: string; count: number }[]; open_jobs?: number; shared_candidates?: number }>("/api/v1/reports/"),
  });
  if (query.isLoading) return <Loading />;
  if (query.isError) return <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} />;
  const data = query.data!;
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Reports</h1>
      <div className="grid gap-3 md:grid-cols-3">
        <Card><h2 className="text-xl">Pipeline</h2><ul className="mt-2 text-sm">{data.pipeline.map((row) => <li key={row.stage} className="flex justify-between"><span className="capitalize">{labelize(row.stage)}</span><span>{row.count}</span></li>)}</ul>{data.pipeline.length === 0 ? <p className="text-sm text-muted">No submissions.</p> : null}</Card>
        <Card><h2 className="text-xl">Sources</h2><ul className="mt-2 text-sm">{(data.sources || []).map((row) => <li key={row.source} className="flex justify-between"><span>{row.source}</span><span>{row.count}</span></li>)}</ul>{!data.sources ? <p className="text-sm">Shared candidates: {data.shared_candidates ?? 0}</p> : null}</Card>
        <Card><h2 className="text-xl">Verification</h2><ul className="mt-2 text-sm">{(data.verification || []).map((row) => <li key={row.verification_status} className="flex justify-between"><span>{labelize(row.verification_status)}</span><span>{row.count}</span></li>)}</ul>{data.open_jobs !== undefined ? <p className="mt-2 text-sm">Open requisitions: {data.open_jobs}</p> : null}</Card>
      </div>
    </div>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const admin = isAdmin(user);
  const client = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<{ retention_days: number; privacy_notice: string; allow_client_see_compensation: boolean; ai_provider_label: string; ai_live_calls_tested: boolean; ai_live_tested_at: string | null; ai_provider: string; scan_status_policy: string }>("/api/v1/settings/organization/"),
  });
  const usage = useQuery({
    queryKey: ["ai-usage"],
    enabled: admin,
    queryFn: () => api<{ totals: { input_tokens: number | null; output_tokens: number | null; cost: string | null }; results: { id: string; operation: string; provider: string; status: string; created_at: string }[]; live_provider_tested: boolean }>("/api/v1/admin/ai-usage/"),
  });
  const audit = useQuery({
    queryKey: ["audit"],
    enabled: admin,
    queryFn: () => api<Page<{ id: string; action: string; detail: string; actor: string | null; created_at: string }>>("/api/v1/admin/audit/"),
  });
  const [notice, setNotice] = useState<string | null>(null);
  const [days, setDays] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [aiTest, setAiTest] = useState("");
  const [error, setError] = useState("");
  if (settings.isLoading) return <Loading />;
  if (settings.isError) return <ErrorState message={errorText(settings.error)} onRetry={() => settings.refetch()} />;
  const current = settings.data!;
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Privacy and retention</h1>
      <Card className="grid gap-2 text-sm">
        <p>Provider: {current.ai_provider_label}. Live hosted calls tested: {current.ai_live_calls_tested ? "yes" : "no"}.</p>
        {admin ? (
          <div>
            <Button variant="outline" onClick={async () => {
              try {
                const result = await api<{ status: string; live: boolean; provider?: string; model?: string; message?: string }>("/api/v1/admin/ai-test/", { method: "POST" });
                setAiTest(result.message || (result.live ? `Live ${result.provider} ${result.model} responded.` : `Status: ${result.status}.`));
                settings.refetch();
                usage.refetch();
              } catch (err) {
                setAiTest(errorText(err));
              }
            }}>Test hosted model</Button>
            {aiTest ? <p className="mt-2">{aiTest}</p> : null}
          </div>
        ) : null}
        <p>Malware scan: {current.scan_status_policy}.</p>
        <p>Ranking does not use protected characteristics. A score is decision support. People make the hiring decision.</p>
        <p>Under the DPDP Act, keep a purpose, record consent, share only what a client needs, and delete when the retention clock and a deletion request both say so.</p>
        <a className="text-accent" href="/api/docs/" target="_blank" rel="noreferrer">API reference</a>
      </Card>
      <Card className="grid gap-2">
        <label className="grid gap-1 text-sm">Retention days
          <Input value={days ?? String(current.retention_days)} onChange={(event) => setDays(event.target.value)} disabled={!admin} />
        </label>
        <label className="grid gap-1 text-sm">Privacy notice
          <Textarea value={notice ?? current.privacy_notice} onChange={(event) => setNotice(event.target.value)} disabled={!admin} />
        </label>
        {admin ? (
          <Button onClick={async () => {
            setError("");
            try {
              await api("/api/v1/settings/organization/", {
                method: "PATCH",
                json: { retention_days: Number(days ?? current.retention_days), privacy_notice: notice ?? current.privacy_notice },
              });
              setMessage("Settings saved.");
              client.invalidateQueries({ queryKey: ["settings"] });
            } catch (err) {
              setError(errorText(err));
            }
          }}>Save settings</Button>
        ) : <p className="text-sm text-muted">An agency admin changes these settings.</p>}
        {admin ? (
          <Button variant="outline" onClick={async () => {
            const result = await api<{ dry_run: boolean; count: number }>("/api/v1/admin/retention/", { method: "POST", json: { dry_run: true } });
            setMessage(`${result.count} profiles are past retention and already marked for deletion.`);
          }}>Preview retention deletions</Button>
        ) : null}
        {message ? <p className="text-sm">{message}</p> : null}
        {error ? <ErrorState message={error} /> : null}
      </Card>
      {admin && usage.data ? (
        <Card>
          <h2 className="text-2xl">Model usage</h2>
          <p className="text-sm text-muted">Live provider tested: {usage.data.live_provider_tested ? "yes" : "no"}. Tokens in {usage.data.totals.input_tokens ?? 0}, out {usage.data.totals.output_tokens ?? 0}.</p>
          <ul className="mt-2 text-sm">{usage.data.results.slice(0, 10).map((row) => <li key={row.id}>{row.operation} · {row.provider} · {row.status}</li>)}</ul>
        </Card>
      ) : null}
      {admin ? (
        <Card>
          <h2 className="text-2xl">Audit</h2>
          {audit.isLoading ? <Loading /> : null}
          {audit.data?.results.length === 0 ? <Empty title="No events" body="Uploads, shares, and downloads are recorded here." /> : null}
          <ul className="mt-2 grid gap-1 text-sm">
            {audit.data?.results.map((row) => <li key={row.id}>{when(row.created_at)} · {labelize(row.action)} · {row.actor || "system"} · {row.detail || ""}</li>)}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
