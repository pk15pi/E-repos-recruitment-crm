import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { Empty, ErrorState, Loading } from "../components/states";
import { Badge, Button, Card, Input, Select, Textarea } from "../components/ui";
import { ACTIVE_JOB_KEY, api, type Page } from "../lib/api";
import { isAgency, useAuth } from "../lib/auth";
import { errorText, labelize, monthsLabel, show, when } from "../lib/format";
import { PRIORITIES, REQUIREMENT_KINDS, type Company, type JobRecord, type MatchRow, type Requirement, type Shortlist } from "../lib/types";

const MAX_JD = 20000;

const jdSchema = z.object({
  description: z.string().trim().min(1, "Paste a job description.").max(MAX_JD, `Job descriptions must be ${MAX_JD} characters or fewer.`),
  title: z.string().optional(),
  location: z.string().optional(),
  work_mode: z.string().optional(),
  min_years: z.string().optional(),
  client_company_id: z.string().optional(),
  interview_levels: z.string().optional(),
  interview_question_count: z.string().optional(),
});

const LEVEL_OPTIONS = ["0", "1", "2", "3", "4", "5"];
const QUESTION_OPTIONS = ["3", "5", "8", "10", "12"];

export function JdPage() {
  const navigate = useNavigate();
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api<Company[]>("/api/v1/clients/") });
  const [error, setError] = useState("");
  const form = useForm({
    resolver: zodResolver(jdSchema),
    defaultValues: { description: "", title: "", location: "", work_mode: "", min_years: "", client_company_id: "", interview_levels: "2", interview_question_count: "5" },
  });
  const description = form.watch("description");
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Find candidates from a job description</h1>
      <p className="text-sm text-muted">Paste a LinkedIn job post. The desk stores the original text and a set of requirements you can edit before anyone is ranked.</p>
      <form
        className="grid gap-3"
        onSubmit={form.handleSubmit(async (values) => {
          setError("");
          const years = values.min_years ? Number(values.min_years) : undefined;
          try {
            const job = await api<JobRecord>("/api/v1/jobs/analyze/", {
              method: "POST",
              json: {
                description: values.description,
                overrides: {
                  title: values.title || undefined,
                  location: values.location || undefined,
                  work_mode: values.work_mode || undefined,
                  client_company_id: values.client_company_id || undefined,
                  min_experience_months: years ? years * 12 : undefined,
                  interview_levels: Number(values.interview_levels || 0),
                  interview_question_count: Number(values.interview_question_count || 5),
                },
              },
            });
            sessionStorage.setItem(ACTIVE_JOB_KEY, job.id);
            navigate(`/jobs/${job.id}`);
          } catch (err) {
            setError(errorText(err));
          }
        })}
      >
        <Textarea aria-label="Job description" className="min-h-64" {...form.register("description")} placeholder="Paste the job description" />
        <p className={`text-xs ${description.length > MAX_JD ? "text-danger" : "text-muted"}`}>{description.length}/{MAX_JD}</p>
        {form.formState.errors.description ? <p className="text-sm text-danger">{form.formState.errors.description.message}</p> : null}
        <div className="grid gap-2 md:grid-cols-2">
          <Input aria-label="Title override" placeholder="Title override" {...form.register("title")} />
          <Input aria-label="Location override" placeholder="Location override" {...form.register("location")} />
          <Select label="Work mode override" value={form.watch("work_mode") || ""} onChange={(value) => form.setValue("work_mode", value)}>
            <option value="">Leave to the description</option>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">On-site</option>
          </Select>
          <Input aria-label="Minimum years" placeholder="Minimum years" {...form.register("min_years")} />
          <Select label="Interview levels after screening" value={form.watch("interview_levels") || "2"} onChange={(value) => form.setValue("interview_levels", value)}>
            {LEVEL_OPTIONS.map((value) => <option key={value} value={value}>{value === "0" ? "Screening only" : `${value} level${value === "1" ? "" : "s"}`}</option>)}
          </Select>
          <Select label="AI interview questions" value={form.watch("interview_question_count") || "5"} onChange={(value) => form.setValue("interview_question_count", value)}>
            {QUESTION_OPTIONS.map((value) => <option key={value} value={value}>{value} question{value === "1" ? "" : "s"}</option>)}
          </Select>
          <Select label="Client" value={form.watch("client_company_id") || ""} onChange={(value) => form.setValue("client_company_id", value)}>
            <option value="">No client yet</option>
            {clients.data?.filter((company) => !company.is_global).map((company) => <option key={company.id} value={company.id}>{company.name}{company.distribution_enabled ? "" : " (no plan)"}</option>)}
          </Select>
        </div>
        {error ? <ErrorState message={error} /> : null}
        <Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? "Analyzing…" : "Analyze job description"}</Button>
      </form>
    </div>
  );
}

export function JobDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Requirement[] | null>(null);
  const [levels, setLevels] = useState("2");
  const [questionCount, setQuestionCount] = useState("5");
  const [setupError, setSetupError] = useState("");
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["job", id],
    queryFn: () => api<JobRecord>(`/api/v1/jobs/${id}/`),
    refetchInterval: (current) => (current.state.data?.analysis_status === "pending" ? 1200 : false),
  });
  useEffect(() => {
    if (id) sessionStorage.setItem(ACTIVE_JOB_KEY, id);
  }, [id]);
  useEffect(() => {
    if (query.data) setLevels(String(query.data.interview_levels));
  }, [query.data?.interview_levels]);
  useEffect(() => {
    if (query.data) setQuestionCount(String(query.data.interview_question_count));
  }, [query.data?.interview_question_count]);
  if (query.isLoading) return <Loading label="Loading the requisition" />;
  if (query.isError) return <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} />;
  const job = query.data!;
  const global = !!job.is_global;
  const requirements = rows ?? job.requirements ?? [];
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-4xl">{job.title || "Untitled requisition"}</h1>
          <p className="text-sm text-muted">Analysis {job.analysis_status}. {job.provider ? `Provider ${job.provider}.` : ""} Original text is kept.</p>
          <p className="text-sm text-muted">
            {global
              ? `Shared read-only from ${job.owner_organization?.name || "another organization"}`
              : `Posted by ${job.created_by?.full_name || "unknown"} · Assigned to ${job.assigned_recruiter?.full_name || "nobody"}`}
            {" · "}
            {job.interview_levels === 0 ? "screening only" : `${job.interview_levels} interview level${job.interview_levels === 1 ? "" : "s"}`}
            {` · ${job.interview_question_count} AI question${job.interview_question_count === 1 ? "" : "s"}`}
            {job.client_company ? ` · ${job.client_company.name}${job.client_company.distribution_enabled ? "" : " (no distribution plan)"}` : ""}
          </p>
        </div>
        {global ? <Badge tone="warn">Global</Badge> : <Button onClick={() => navigate(`/jobs/${job.id}/matches`)}>Find matching candidates</Button>}
      </div>
      {global ? (
        <p className="rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-warn">
          This requisition belongs to {job.owner_organization?.name || "another organization"}. You can read it, but
          matching, editing, and assignment stay with the owning organization.
        </p>
      ) : null}
      {job.analysis_status === "pending" ? <Loading label="Reading the description" /> : null}
      {job.analysis_status === "failed" ? <ErrorState message={job.analysis_error || "Analysis failed."} /> : null}
      {!global ? (
      <Card className="grid gap-3">
        <h2 className="text-2xl">Delivery setup</h2>
        <p className="text-sm text-muted">Every recruiter can work this requisition. Screening is always an in-app interview; the levels below decide how many L1–L5 rounds follow it.</p>
        <div className="flex flex-wrap items-end gap-2">
          <Select label="Interview levels after screening" value={levels} onChange={setLevels}>
            {LEVEL_OPTIONS.map((value) => <option key={value} value={value}>{value === "0" ? "Screening only" : `${value} level${value === "1" ? "" : "s"}`}</option>)}
          </Select>
          <Select label="AI interview questions" value={questionCount} onChange={setQuestionCount}>
            {QUESTION_OPTIONS.map((value) => <option key={value} value={value}>{value} question{value === "1" ? "" : "s"}</option>)}
          </Select>
          <Button variant="outline" onClick={async () => {
            setSetupError("");
            try {
              await api(`/api/v1/jobs/${job.id}/`, {
                method: "PATCH",
                json: { interview_levels: Number(levels), interview_question_count: Number(questionCount) },
              });
              await query.refetch();
            } catch (err) {
              setSetupError(errorText(err));
            }
          }}>Save interview setup</Button>
          <Button variant="outline" onClick={async () => {
            setSetupError("");
            try {
              await api(`/api/v1/jobs/${job.id}/`, { method: "PATCH", json: { assigned_recruiter_id: user?.id } });
              await query.refetch();
            } catch (err) {
              setSetupError(errorText(err));
            }
          }}>Assign to me</Button>
        </div>
        {setupError ? <ErrorState message={setupError} /> : null}
      </Card>
      ) : null}
      <Card>
        <h2 className="text-2xl">Original description</h2>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-sans text-sm">{job.original_description || "Not provided"}</pre>
      </Card>
      {global ? (
        <Card className="grid gap-2">
          <h2 className="text-2xl">Requirements</h2>
          {requirements.length === 0 ? (
            <p className="text-sm text-muted">No requirements were parsed.</p>
          ) : (
            requirements.map((row, index) => (
              <p key={index} className="text-sm">
                <Badge>{labelize(row.kind)}</Badge> {row.value}
                <span className="text-muted"> · {labelize(row.priority)}</span>
              </p>
            ))
          )}
        </Card>
      ) : (
      <Card className="grid gap-3">
        <h2 className="text-2xl">Requirements</h2>
        <p className="text-sm text-muted">Mark each line Must have, Preferred, or Informational. Must-have filters drop known mismatches. Unknown data does not fail.</p>
        {requirements.map((row, index) => (
          <div key={index} className="grid gap-2 md:grid-cols-[160px_1fr_160px]">
            <Select label="Kind" value={row.kind} onChange={(value) => setRows(requirements.map((item, i) => (i === index ? { ...item, kind: value } : item)))}>
              {REQUIREMENT_KINDS.map((kind) => <option key={kind} value={kind}>{labelize(kind)}</option>)}
            </Select>
            <Input aria-label={`Requirement ${index + 1}`} value={row.value} onChange={(event) => setRows(requirements.map((item, i) => (i === index ? { ...item, value: event.target.value, label: event.target.value } : item)))} />
            <Select label="Priority" value={row.priority} onChange={(value) => setRows(requirements.map((item, i) => (i === index ? { ...item, priority: value } : item)))}>
              {PRIORITIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </Select>
          </div>
        ))}
        <Button variant="outline" type="button" onClick={() => setRows([...requirements, { kind: "other", label: "", value: "", priority: "preferred" }])}>Add criterion</Button>
        {error ? <ErrorState message={error} /> : null}
        <Button type="button" onClick={async () => {
          setError("");
          try {
            const next = await api<JobRecord>(`/api/v1/jobs/${id}/requirements/`, { method: "PUT", json: { requirements } });
            setRows(next.requirements || []);
          } catch (err) {
            setError(errorText(err));
          }
        }}>Save requirements</Button>
      </Card>
      )}
    </div>
  );
}

export function MatchPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [disclaimer, setDisclaimer] = useState("");
  const [processing, setProcessing] = useState("");
  const [error, setError] = useState("");
  const ordering = params.get("ordering") || "-score";
  const page = params.get("page") || "1";
  const query = useQuery({
    queryKey: ["matches", id, ordering, page],
    queryFn: () => api<Page<MatchRow> & { disclaimer?: string }>(`/api/v1/jobs/${id}/matches/?ordering=${ordering}&page=${page}`),
    refetchInterval: processing && processing !== "succeeded" && processing !== "failed" ? 1500 : false,
  });
  useEffect(() => {
    if (query.data?.disclaimer) setDisclaimer(query.data.disclaimer);
  }, [query.data]);

  async function match() {
    setError("");
    try {
      const data = await api<{ processing: { status: string; last_error: string }; disclaimer: string }>(`/api/v1/jobs/${id}/match/`, { method: "POST" });
      setProcessing(data.processing.status);
      setDisclaimer(data.disclaimer);
      if (data.processing.last_error) setError(data.processing.last_error);
      query.refetch();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-4xl">Matches</h1>
          <p className="text-sm text-muted">{disclaimer || "Scores support a recruiter. They are not probabilities and they are not hiring decisions."}</p>
        </div>
        <div className="flex gap-2">
          <Select label="Sort" value={ordering} onChange={(value) => setParams({ ordering: value, page: "1" })}>
            <option value="-score">Score</option>
            <option value="experience">Experience</option>
            <option value="updated_at">Recently updated</option>
          </Select>
          <Button onClick={match}>Find matching candidates</Button>
        </div>
      </div>
      {error ? <ErrorState message={error} /> : null}
      {query.isLoading ? <Loading /> : null}
      {query.data && query.data.results.length === 0 ? <Empty title="No ranked people yet" body="Save the requirements, then run matching. Only candidates this account can see are included." /> : null}
      <ul className="grid gap-3">
        {query.data?.results.map((row) => <MatchCard key={row.match_id} row={row} jobId={id!} />)}
      </ul>
      {query.data ? (
        <div className="flex justify-between text-sm">
          <span>{query.data.count} ranked</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={!query.data.previous} onClick={() => setParams({ ordering, page: String(Math.max(1, Number(page) - 1)) })}>Previous</Button>
            <Button size="sm" variant="outline" disabled={!query.data.next} onClick={() => setParams({ ordering, page: String(Number(page) + 1) })}>Next</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function MatchCard({ row, jobId }: { row: MatchRow; jobId: string }) {
  const [open, setOpen] = useState<"shortlist" | "submit" | null>(null);
  const [message, setMessage] = useState("");
  return (
    <li>
      <Card className="grid gap-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <Link className="font-serif text-2xl" to={`/candidates/${row.id}`}>{row.full_name || "Unnamed candidate"}</Link>
            <p className="text-sm text-muted">{show(row.current_title)} · {show(row.location)} · {monthsLabel(row.total_experience_months)}</p>
            <p className="text-sm">Skills: {row.skills.map((skill) => `${skill.name}${skill.source === "verified" ? " (verified)" : skill.source === "extracted" ? " (extracted)" : ""}`).join(", ") || "Not provided"}</p>
            <p className="text-sm">Employers: {row.employers.join(", ") || "Not provided"}</p>
            <p className="text-sm">Availability: {row.availability_date || "Not provided"} · Notice: {row.notice_period_days ?? "Not provided"}</p>
            <p className="text-sm">Compensation: {row.compensation_visible ? show(row.expected_salary_amount) : "Not shared"}</p>
            <p className="text-xs text-muted">Updated {when(row.updated_at)}</p>
          </div>
          <div className="text-right">
            <p className="font-serif text-3xl">{row.score}</p>
            <p className="text-xs text-muted">{row.score_version}</p>
            <p className="text-sm">Must-have met {row.mandatory_met} · unknown {row.mandatory_unknown} · unmet {row.mandatory_unmet}</p>
            <p className="text-sm">Preferred {row.preferred_matched}/{row.preferred_total}</p>
          </div>
        </div>
        <p className="text-sm">{row.explanation || "Not provided"}</p>
        <ul className="grid gap-1 text-xs text-muted">
          {row.evidence.map((item, index) => (
            <li key={index}><Badge tone={item.status === "met" ? "good" : item.status === "unmet" ? "bad" : "warn"}>{item.status}</Badge> {item.detail}{item.quote ? ` “${item.quote}”` : ""}</li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" asChild><Link to={`/candidates/${row.id}`}>View</Link></Button>
          <Button size="sm" variant="outline" asChild><Link to={`/compare?ids=${row.id}`}>Compare</Link></Button>
          <Button size="sm" variant="outline" onClick={() => setOpen("shortlist")}>Shortlist</Button>
          <Button size="sm" onClick={() => setOpen("submit")}>Submit</Button>
        </div>
        {open === "shortlist" ? <ShortlistPicker candidateId={row.id} jobId={jobId} onDone={(text) => { setMessage(text); setOpen(null); }} /> : null}
        {open === "submit" ? <SubmitForm candidateId={row.id} jobId={jobId} onDone={(text) => { setMessage(text); setOpen(null); }} /> : null}
        {message ? <p className="text-sm">{message}</p> : null}
      </Card>
    </li>
  );
}

function ShortlistPicker({ candidateId, jobId, onDone }: { candidateId: string; jobId: string; onDone: (message: string) => void }) {
  const lists = useQuery({ queryKey: ["shortlists"], queryFn: () => api<Shortlist[]>("/api/v1/shortlists/") });
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  return (
    <div className="grid gap-2 rounded-md bg-paper p-3">
      {lists.data?.map((list) => (
        <Button key={list.id} size="sm" variant="outline" onClick={async () => {
          await api(`/api/v1/shortlists/${list.id}/items/`, { method: "POST", json: { candidate_id: candidateId } });
          onDone(`Added to ${list.name}.`);
        }}>{list.name}</Button>
      ))}
      <Input aria-label="New shortlist name" value={name} onChange={(event) => setName(event.target.value)} placeholder="New shortlist" />
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      <Button size="sm" onClick={async () => {
        if (!name.trim()) {
          setError("Name the shortlist.");
          return;
        }
        const created = await api<Shortlist>("/api/v1/shortlists/", { method: "POST", json: { name, job_id: jobId } });
        await api(`/api/v1/shortlists/${created.id}/items/`, { method: "POST", json: { candidate_id: candidateId } });
        onDone(`Added to ${created.name}.`);
      }}>Create and add</Button>
    </div>
  );
}

function SubmitForm({ candidateId, jobId, onDone }: { candidateId: string; jobId: string; onDone: (message: string) => void }) {
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api<Company[]>("/api/v1/clients/") });
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api<JobRecord>(`/api/v1/jobs/${jobId}/`) });
  const [clientId, setClientId] = useState("");
  const [resume, setResume] = useState(true);
  const [contact, setContact] = useState(false);
  const [money, setMoney] = useState(false);
  const [error, setError] = useState("");
  const selectedClient = clients.data?.find((company) => company.id === clientId);
  const blocked = job.data?.client_company
    ? job.data.client_company.distribution_enabled === false
    : selectedClient
      ? selectedClient.distribution_enabled === false
      : false;
  return (
    <form className="grid gap-2 rounded-md bg-paper p-3" onSubmit={async (event) => {
      event.preventDefault();
      setError("");
      try {
        if (!job.data?.client_company && clientId) {
          await api(`/api/v1/jobs/${jobId}/`, { method: "PATCH", json: { client_company_id: clientId, status: "open" } });
        }
        await api("/api/v1/submissions/", {
          method: "POST",
          json: { candidate_id: candidateId, job_id: jobId, include_resume: resume, include_contact: contact, include_compensation: money },
        });
        onDone("Submitted. The client can see only what you included.");
      } catch (err) {
        setError(errorText(err));
      }
    }}>
      {job.data?.client_company ? <p className="text-sm">Client: {job.data.client_company.name}</p> : (
        <Select label="Attach a client" value={clientId} onChange={setClientId}>
          <option value="">Choose</option>
          {clients.data?.filter((company) => !company.is_global).map((company) => <option key={company.id} value={company.id}>{company.name}{company.distribution_enabled ? "" : " (no plan)"}</option>)}
        </Select>
      )}
      {blocked ? <p className="text-sm text-danger">This client has no distribution plan. An agency admin can enable a paid plan or grant free access.</p> : null}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={resume} onChange={(event) => setResume(event.target.checked)} /> Include resume</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={contact} onChange={(event) => setContact(event.target.checked)} /> Include contact details</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={money} onChange={(event) => setMoney(event.target.checked)} /> Include compensation</label>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      <Button type="submit" size="sm" disabled={blocked}>Submit to client</Button>
    </form>
  );
}

export function RequisitionListPage() {
  const { user } = useAuth();
  const agency = isAgency(user);
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [title, setTitle] = useState("");
  const [clientId, setClientId] = useState("");
  const [levels, setLevels] = useState("2");
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["jobs", page],
    queryFn: () => api<Page<JobRecord>>(`/api/v1/jobs/?page=${page}`),
  });
  const clients = useQuery({ queryKey: ["clients"], enabled: agency, queryFn: () => api<Company[]>("/api/v1/clients/") });
  const remembered = sessionStorage.getItem(ACTIVE_JOB_KEY);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-4xl">Requisitions</h1>
        {agency ? <Button asChild><Link to="/jobs/from-description">From a job description</Link></Button> : null}
      </div>
      {remembered ? <p className="text-sm">Last description you worked on: <Link className="text-accent" to={`/jobs/${remembered}`}>open it</Link></p> : null}
      {agency ? (
        <Card className="grid gap-2 md:grid-cols-[1fr_1fr_160px_auto]">
          <Input aria-label="Requisition title" placeholder="Title" value={title} onChange={(event) => setTitle(event.target.value)} />
          <Select label="Client" value={clientId} onChange={setClientId}>
            <option value="">No client yet</option>
            {clients.data?.filter((company) => !company.is_global).map((company) => <option key={company.id} value={company.id}>{company.name}{company.distribution_enabled ? "" : " (no plan)"}</option>)}
          </Select>
          <Select label="Interview levels" value={levels} onChange={setLevels}>
            {LEVEL_OPTIONS.map((value) => <option key={value} value={value}>{value === "0" ? "Screening only" : `${value} level${value === "1" ? "" : "s"}`}</option>)}
          </Select>
          <Button onClick={async () => {
            setError("");
            try {
              await api("/api/v1/jobs/", { method: "POST", json: { title, client_company_id: clientId || undefined, interview_levels: Number(levels), status: "open" } });
              setTitle("");
              client.invalidateQueries({ queryKey: ["jobs"] });
            } catch (err) {
              setError(errorText(err));
            }
          }}>Open requisition</Button>
          {error ? <ErrorState message={error} /> : null}
        </Card>
      ) : null}
      {query.isLoading ? <Loading /> : null}
      {query.isError ? <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} /> : null}
      {query.data?.results.length === 0 ? <Empty title="No requisitions" body="Paste a job description or open one by title." /> : null}
      <ul className="grid gap-2">
        {query.data?.results.map((job) => (
          <li key={job.id}>
            <Card className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <Link className="font-serif text-2xl" to={`/jobs/${job.id}`}>{job.title || "Untitled"}</Link>
                <p className="text-sm text-muted">{job.client_company?.name || "No client"} · {labelize(job.status)} · {job.interview_levels === 0 ? "screening only" : `${job.interview_levels} interview level${job.interview_levels === 1 ? "" : "s"}`} · {job.location || "Location not provided"}</p>
                <p className="text-xs text-muted">
                  {job.is_global
                    ? `Shared read-only from ${job.owner_organization?.name || "another organization"}`
                    : `Posted by ${job.created_by?.full_name || "unknown"} · assigned to ${job.assigned_recruiter?.full_name || "nobody"}`}
                </p>
              </div>
              <div className="flex gap-2">
                {job.is_global ? <Badge tone="warn">Global</Badge> : null}
                {agency && !job.is_global ? <Button size="sm" variant="outline" onClick={async () => {
                  const next = job.status === "open" ? "closed" : "open";
                  await api(`/api/v1/jobs/${job.id}/`, { method: "PATCH", json: { status: next } });
                  client.invalidateQueries({ queryKey: ["jobs"] });
                }}>{job.status === "open" ? "Close" : "Reopen"}</Button> : null}
                {agency && !job.is_global ? <Button size="sm" asChild><Link to={`/jobs/${job.id}/matches`}>Matches</Link></Button> : null}
              </div>
            </Card>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</Button>
        <Button size="sm" variant="outline" disabled={!query.data?.next} onClick={() => setPage((value) => value + 1)}>Next</Button>
      </div>
    </div>
  );
}
