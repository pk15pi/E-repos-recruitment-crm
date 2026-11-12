import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useParams } from "react-router-dom";

import { Empty, ErrorState, Loading } from "../components/states";
import { Badge, Button, Card, Input, Select, Textarea } from "../components/ui";
import { api } from "../lib/api";
import { isAdmin, isAgency, useAuth } from "../lib/auth";
import { STAGES, errorText, labelize, when } from "../lib/format";
import type { Company, Contact, Interview, Shortlist, Submission, Task } from "../lib/types";

const PLAN_LABELS: Record<string, string> = {
  none: "No plan",
  paid: "Paid plan",
  free: "Free access",
};

export function levelLabel(level: string) {
  return level === "screening" ? "Screening" : level.toUpperCase();
}

function outcomeTone(status: string) {
  if (status === "passed" || status === "completed") return "good" as const;
  if (status === "failed") return "bad" as const;
  return "warn" as const;
}

export function ClientListPage() {
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [error, setError] = useState("");
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["clients"], queryFn: () => api<Company[]>("/api/v1/clients/") });
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Clients</h1>
      <Card className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
        <Input aria-label="Company name" placeholder="Company" value={name} onChange={(event) => setName(event.target.value)} />
        <Input aria-label="Industry" placeholder="Industry" value={industry} onChange={(event) => setIndustry(event.target.value)} />
        <Button onClick={async () => {
          setError("");
          try {
            await api("/api/v1/clients/", { method: "POST", json: { name, industry } });
            setName("");
            client.invalidateQueries({ queryKey: ["clients"] });
          } catch (err) {
            setError(errorText(err));
          }
        }}>Add client</Button>
        {error ? <ErrorState message={error} /> : null}
      </Card>
      {query.isLoading ? <Loading /> : null}
      {query.isError ? <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} /> : null}
      {query.data?.length === 0 ? <Empty title="No clients yet" body="Add the company before you submit anyone." /> : null}
      <ul className="grid gap-2">
        {query.data?.map((company) => (
          <li key={company.id}>
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link className="font-serif text-2xl" to={`/clients/${company.id}`}>{company.name}</Link>
                {company.is_global ? (
                  <Badge tone="warn">Global · {company.owner_organization?.name || "another organization"}</Badge>
                ) : (
                  <Badge tone={company.distribution_enabled ? "good" : "warn"}>{PLAN_LABELS[company.plan || ""] || company.plan}</Badge>
                )}
              </div>
              <p className="text-sm text-muted">{company.industry || "Industry not provided"}</p>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ClientDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const admin = isAdmin(user);
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["client", id], queryFn: () => api<Company>(`/api/v1/clients/${id}/`) });
  const [contact, setContact] = useState({ name: "", email: "", title: "" });
  const [error, setError] = useState("");
  const [plan, setPlan] = useState("none");
  const [planRef, setPlanRef] = useState("");
  const [reason, setReason] = useState("");
  const [planError, setPlanError] = useState("");
  useEffect(() => {
    if (!query.data) return;
    setPlan(query.data.plan || "none");
    setPlanRef(query.data.plan_reference || "");
    setReason(query.data.free_access_reason || "");
  }, [query.data?.plan, query.data?.plan_reference, query.data?.free_access_reason]);
  if (query.isLoading) return <Loading />;
  if (query.isError) return <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} />;
  const company = query.data!;
  const global = company.is_global;
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">{company.name}</h1>
      <p className="text-sm text-muted">
        {company.website || "Website not provided"}
        {global ? "" : ` · ${company.notes || "No notes"}`}
      </p>
      {global ? (
        <p className="rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-warn">
          Shared read-only from {company.owner_organization?.name || "another organization"}. Plan, notes, and team
          membership stay inside the owning organization.
        </p>
      ) : null}
      {!global ? (
      <Card className="grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-2xl">Distribution plan</h2>
          <Badge tone={company.distribution_enabled ? "good" : "warn"}>{PLAN_LABELS[company.plan || ""] || company.plan}</Badge>
        </div>
        <p className="text-sm text-muted">
          Candidates can be submitted and shared only while a paid plan or an admin-granted free plan is active.
          {company.free_access_granted_at ? ` Free access granted ${when(company.free_access_granted_at)}.` : ""}
        </p>
        {admin ? (
          <div className="grid gap-2 md:grid-cols-3">
            <Select label="Plan" value={plan} onChange={setPlan}>
              <option value="none">No plan</option>
              <option value="paid">Paid plan</option>
              <option value="free">Free access (admin grant)</option>
            </Select>
            <Input aria-label="Plan reference" placeholder="Invoice or contract reference" value={planRef} onChange={(event) => setPlanRef(event.target.value)} />
            <Input aria-label="Free access reason" placeholder="Why this client is free" value={reason} onChange={(event) => setReason(event.target.value)} />
            <Button onClick={async () => {
              setPlanError("");
              try {
                await api(`/api/v1/clients/${id}/`, {
                  method: "PATCH",
                  json: { plan, plan_reference: planRef, free_access_reason: reason },
                });
                client.invalidateQueries({ queryKey: ["client", id] });
                client.invalidateQueries({ queryKey: ["clients"] });
              } catch (err) {
                setPlanError(errorText(err));
              }
            }}>Save plan</Button>
            {planError ? <ErrorState message={planError} /> : null}
          </div>
        ) : <p className="text-sm text-muted">An agency admin controls this client's plan.</p>}
      </Card>
      ) : null}
      <Card className="grid gap-2">
        <h2 className="text-2xl">Contacts</h2>
        {(company.contacts || []).length === 0 ? (
          <p className="text-sm text-muted">
            {global ? "No contacts are shared with your organization." : "No contacts yet."}
          </p>
        ) : null}
        {(company.contacts || []).map((row: Contact) => (
          <div key={row.id} className="flex items-center justify-between text-sm">
            <span>{row.name} · {row.title || "Not provided"} · {row.email || "Not provided"}</span>
            {!global ? (
              <Button size="sm" variant="ghost" onClick={async () => {
                await api(`/api/v1/clients/${id}/contacts/${row.id}/`, { method: "DELETE" });
                client.invalidateQueries({ queryKey: ["client", id] });
              }}>Remove</Button>
            ) : null}
          </div>
        ))}
        {!global ? (
          <form className="grid gap-2 md:grid-cols-3" onSubmit={async (event) => {
            event.preventDefault();
            setError("");
            try {
              await api(`/api/v1/clients/${id}/contacts/`, { method: "POST", json: contact });
              setContact({ name: "", email: "", title: "" });
              client.invalidateQueries({ queryKey: ["client", id] });
            } catch (err) {
              setError(errorText(err));
            }
          }}>
            <Input aria-label="Contact name" placeholder="Name" value={contact.name} onChange={(event) => setContact({ ...contact, name: event.target.value })} />
            <Input aria-label="Contact email" placeholder="Email" value={contact.email} onChange={(event) => setContact({ ...contact, email: event.target.value })} />
            <Input aria-label="Contact title" placeholder="Title" value={contact.title} onChange={(event) => setContact({ ...contact, title: event.target.value })} />
            <Button type="submit">Add contact</Button>
          </form>
        ) : null}
        {error ? <ErrorState message={error} /> : null}
      </Card>
      {!global ? (
        <Card>
          <h2 className="text-2xl">Members</h2>
          {(company.members || []).length === 0 ? <p className="mt-2 text-sm text-muted">No client users yet. Add one from People and roles.</p> : null}
          <ul className="mt-2 text-sm">{company.members?.map((member) => <li key={member.user_id}>{member.email} · {labelize(member.role)}</li>)}</ul>
        </Card>
      ) : null}
    </div>
  );
}

export function ShortlistPage() {
  const { user } = useAuth();
  const agency = isAgency(user);
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["shortlists"], queryFn: () => api<Shortlist[]>("/api/v1/shortlists/") });
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Shortlists</h1>
      {agency ? (
        <form className="flex flex-wrap gap-2" onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          if (!name.trim()) {
            setError("Name the shortlist.");
            return;
          }
          try {
            await api("/api/v1/shortlists/", { method: "POST", json: { name } });
            setName("");
            client.invalidateQueries({ queryKey: ["shortlists"] });
          } catch (err) {
            setError(errorText(err));
          }
        }}>
          <Input aria-label="Shortlist name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Harbour backend shortlist" />
          <Button type="submit">Create shortlist</Button>
        </form>
      ) : null}
      {error ? <ErrorState message={error} /> : null}
      {query.isLoading ? <Loading /> : null}
      {query.data?.length === 0 ? <Empty title="No shortlists" body="Create one here, or add someone from a match." /> : null}
      <ul className="grid gap-3">
        {query.data?.map((list) => (
          <li key={list.id}>
            <Card>
              <h2 className="text-2xl">{list.name}</h2>
              {list.items.length === 0 ? <p className="text-sm text-muted">Empty.</p> : (
                <ul className="mt-2 grid gap-1 text-sm">
                  {list.items.map((item) => (
                    <li key={item.candidate_id} className="flex items-center justify-between">
                      <Link to={`/candidates/${item.candidate_id}`}>{item.name || "Unnamed"}</Link>
                      {agency ? <Button size="sm" variant="ghost" onClick={async () => {
                        await api(`/api/v1/shortlists/${list.id}/items/${item.candidate_id}/`, { method: "DELETE" });
                        client.invalidateQueries({ queryKey: ["shortlists"] });
                      }}>Remove</Button> : null}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SubmissionPage() {
  const { user } = useAuth();
  const agency = isAgency(user);
  const client = useQueryClient();
  const [stage, setStage] = useState("");
  const query = useQuery({
    queryKey: ["submissions", stage],
    queryFn: () => api<Submission[]>(`/api/v1/submissions/${stage ? `?stage=${stage}` : ""}`),
  });
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Submissions</h1>
      <Select label="Stage" value={stage} onChange={setStage}>
        <option value="">All stages</option>
        {STAGES.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
      </Select>
      {query.isLoading ? <Loading /> : null}
      {query.isError ? <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} /> : null}
      {query.data?.length === 0 ? <Empty title="Nothing in the pipeline" body="Submit someone from a match once the requisition has a client." /> : null}
      <ul className="grid gap-2">
        {query.data?.map((row) => (
          <li key={row.id}>
            <Card className="grid gap-2 md:grid-cols-[1fr_auto] md:items-center">
              <div>
                <Link className="font-medium" to={`/candidates/${row.candidate_id}`}>{row.candidate_name || "Unnamed"}</Link>
                <p className="text-sm text-muted">
                  {row.job_title || "Untitled"} · {row.client_name} ({PLAN_LABELS[row.client_plan] || row.client_plan}) · updated {when(row.updated_at)}
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {row.interview_progress.map((item) => (
                    <Badge key={item.level} tone={outcomeTone(item.status)}>
                      {levelLabel(item.level)}: {labelize(item.status)}
                    </Badge>
                  ))}
                </div>
                <p className="mt-1 text-xs text-muted">
                  Screening is always an in-app interview and must pass before L1.
                  <Link className="ml-2 text-accent" to={`/interviews?submission=${row.id}&level=${row.interview_progress.find((item) => item.outcome !== "passed")?.level || "screening"}`}>
                    Open interview
                  </Link>
                </p>
              </div>
              <Select label="Move stage" value={row.stage} onChange={async (value) => {
                await api(`/api/v1/submissions/${row.id}/`, { method: "PATCH", json: { stage: value } });
                client.invalidateQueries({ queryKey: ["submissions"] });
              }}>
                {(agency ? STAGES : ["rejected", "on_hold"]).map((item) => <option key={item} value={item}>{labelize(item)}</option>)}
              </Select>
              {agency && row.stage === "offer" ? <OfferFields row={row} /> : null}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

function OfferFields({ row }: { row: Submission }) {
  const client = useQueryClient();
  const [amount, setAmount] = useState(String(row.offer_amount ?? ""));
  const [joining, setJoining] = useState(row.joining_date || "");
  const [notes, setNotes] = useState(row.placement_notes || "");
  return (
    <form className="grid gap-2 md:col-span-2 md:grid-cols-4" onSubmit={async (event) => {
      event.preventDefault();
      await api(`/api/v1/submissions/${row.id}/`, { method: "PATCH", json: { offer_amount: amount || null, joining_date: joining || null, placement_notes: notes } });
      client.invalidateQueries({ queryKey: ["submissions"] });
    }}>
      <Input aria-label="Offer amount" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="Offer amount" />
      <Input aria-label="Joining date" type="date" value={joining} onChange={(event) => setJoining(event.target.value)} />
      <Input aria-label="Placement notes" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Placement notes" />
      <Button type="submit" size="sm">Save offer</Button>
    </form>
  );
}

export function InterviewPage() {
  const { user } = useAuth();
  const agency = isAgency(user);
  const client = useQueryClient();
  const [params] = useSearchParams();
  const submissionParam = params.get("submission") || "";
  const levelParam = params.get("level") || "screening";
  const query = useQuery({ queryKey: ["interviews"], queryFn: () => api<Interview[]>("/api/v1/interviews/") });
  const submissions = useQuery({ queryKey: ["submissions", ""], enabled: agency, queryFn: () => api<Submission[]>("/api/v1/submissions/") });
  const [form, setForm] = useState({
    submission_id: submissionParam,
    level: levelParam,
    scheduled_at: "",
    interviewer_name: "",
    mode: "ui",
    kind: "manual",
    question_source: "random",
    question_count: "5",
    questions: "",
    meeting_url: "",
    duration_minutes: "",
  });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (submissionParam) setForm((current) => ({ ...current, submission_id: submissionParam, level: levelParam }));
  }, [submissionParam, levelParam]);
  const selected = submissions.data?.find((row) => row.id === form.submission_id);
  useEffect(() => {
    if (selected) setForm((current) => ({ ...current, question_count: String(selected.interview_question_count || 5) }));
  }, [selected?.interview_question_count]);
  const levels = ["screening", ...Array.from({ length: selected?.interview_levels || 0 }, (_, index) => `l${index + 1}`)];
  const screening = form.level === "screening";
  const ai = form.kind === "ai";
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Interviews</h1>
      <p className="text-sm text-muted">
        Screening is always run in this desk and must pass before L1. Each level unlocks the next; a requisition only accepts
        as many levels as it declares. An AI interview asks the candidate in the browser and emails the recruiter the AI
        feedback; a recruiter still records pass or fail.
      </p>
      {agency ? (
        <Card className="grid gap-2 md:grid-cols-2">
          <Select label="Submission" value={form.submission_id} onChange={(value) => setForm({ ...form, submission_id: value })}>
            <option value="">Choose</option>
            {submissions.data?.map((row) => <option key={row.id} value={row.id}>{row.candidate_name} · {row.job_title} · {row.interview_levels} level{row.interview_levels === 1 ? "" : "s"}</option>)}
          </Select>
          <Select label="Level" value={form.level} onChange={(value) => setForm({ ...form, level: value })}>
            {levels.map((level) => <option key={level} value={level}>{levelLabel(level)}</option>)}
          </Select>
          <Select label="Interview type" value={form.kind} onChange={(value) => setForm({ ...form, kind: value })}>
            <option value="manual">Manual interview</option>
            <option value="ai">AI interview (candidate answers in the browser)</option>
          </Select>
          <Input aria-label="When" type="datetime-local" value={form.scheduled_at} onChange={(event) => setForm({ ...form, scheduled_at: event.target.value })} />
          <Input aria-label="Duration" placeholder="Duration in minutes" value={form.duration_minutes} onChange={(event) => setForm({ ...form, duration_minutes: event.target.value })} />
          <Input aria-label="Interviewer" placeholder="Interviewer" value={form.interviewer_name} onChange={(event) => setForm({ ...form, interviewer_name: event.target.value })} />
          <Select label="Mode" value={screening ? "ui" : form.mode} onChange={(value) => setForm({ ...form, mode: value })}>
            <option value="ui">In-app (this desk)</option>
            {screening ? null : <option value="video">Video call</option>}
            {screening ? null : <option value="phone">Phone</option>}
            {screening ? null : <option value="onsite">On-site</option>}
          </Select>
          {ai ? (
            <Select label="Question source" value={form.question_source} onChange={(value) => setForm({ ...form, question_source: value })}>
              <option value="random">Generate from the requisition</option>
              <option value="manual">Write the questions myself</option>
            </Select>
          ) : null}
          {ai && form.question_source === "random" ? (
            <Input aria-label="Question count" placeholder="Number of questions" value={form.question_count} onChange={(event) => setForm({ ...form, question_count: event.target.value })} />
          ) : null}
          {ai ? (
            <Input aria-label="Meeting link" placeholder="Optional Google Meet or Teams link" value={form.meeting_url} onChange={(event) => setForm({ ...form, meeting_url: event.target.value })} />
          ) : null}
          {ai && form.question_source === "manual" ? (
            <Textarea aria-label="Questions" className="md:col-span-2" value={form.questions} onChange={(event) => setForm({ ...form, questions: event.target.value })} placeholder={"One question per line\nTell us about a payment system you built.\nHow do you review a database migration?"} />
          ) : null}
          <Button onClick={async () => {
            setError("");
            setNotice("");
            try {
              const payload: Record<string, unknown> = {
                submission_id: form.submission_id,
                level: form.level,
                scheduled_at: form.scheduled_at ? new Date(form.scheduled_at).toISOString() : null,
                duration_minutes: form.duration_minutes || null,
                interviewer_name: form.interviewer_name,
                mode: screening ? "ui" : form.mode,
                kind: form.kind,
              };
              if (ai) {
                payload.meeting_url = form.meeting_url || undefined;
                payload.question_source = form.question_source;
                if (form.question_source === "manual") {
                  payload.questions = form.questions.split("\n").map((line) => line.trim()).filter(Boolean);
                } else {
                  payload.question_count = Number(form.question_count || 0);
                }
              }
              const created = await api<Interview>("/api/v1/interviews/", { method: "POST", json: payload });
              if (created.invitation?.sent) {
                setNotice("Scheduled and the invitation was emailed to the candidate.");
              } else if (created.invitation?.error) {
                setNotice(`Scheduled. Invitation not sent: ${created.invitation.error}`);
              } else if (created.warning) {
                setNotice(created.warning);
              }
              client.invalidateQueries({ queryKey: ["interviews"] });
              client.invalidateQueries({ queryKey: ["submissions"] });
            } catch (err) {
              setError(errorText(err));
            }
          }}>Schedule</Button>
          {error ? <ErrorState message={error} /> : null}
          {notice ? <p className="text-sm text-muted md:col-span-2">{notice}</p> : null}
        </Card>
      ) : null}
      {query.isLoading ? <Loading /> : null}
      {query.data?.length === 0 ? <Empty title="No interviews" body="Schedule screening first, then the interview levels the requisition declares." /> : null}
      <ul className="grid gap-2">
        {query.data?.map((row) => <InterviewCard key={row.id} row={row} />)}
      </ul>
    </div>
  );
}

function InterviewCard({ row }: { row: Interview }) {
  const client = useQueryClient();
  const [feedback, setFeedback] = useState(row.feedback || "");
  const [rating, setRating] = useState(String(row.rating ?? ""));
  const [outcome, setOutcome] = useState(row.outcome === "failed" ? "failed" : "passed");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const ai = row.kind === "ai";
  const report = row.ai_report;
  const answered = row.questions.filter((question) => question.answered_at).length;
  return (
    <li>
      <Card className="grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <Link to={`/candidates/${row.candidate_id}`}>{row.candidate_name || "Unnamed"}</Link>
            <p className="text-sm text-muted">
              {row.job_title || "Untitled"} · {levelLabel(row.level)} · {ai ? "AI interview" : "Manual interview"} · {when(row.scheduled_at)} · {row.interviewer_name || "Interviewer not provided"} · {labelize(row.status)}
            </p>
          </div>
          <Badge tone={outcomeTone(row.status === "completed" ? row.outcome : row.status)}>
            {row.status === "completed"
              ? `Outcome: ${labelize(row.outcome)}`
              : ai && report?.summary
                ? "AI feedback ready"
                : row.feedback
                  ? "Feedback in"
                  : "Feedback waiting"}
          </Badge>
        </div>
        {ai ? (
          <div className="grid gap-2 rounded-md border border-line/60 p-3">
            <p className="text-sm text-muted">
              {row.question_source === "manual" ? "Recruiter-written" : "Generated from the requisition"} · {row.question_count} question(s) · {answered} answered
              {row.invited_at ? ` · Invitation sent ${when(row.invited_at)}` : " · Not invited yet"}
            </p>
            {row.join_url ? (
              <div className="flex flex-wrap items-center gap-2">
                <a className="text-sm underline" href={row.join_url} target="_blank" rel="noreferrer">Candidate interview link</a>
                <Button size="sm" variant="outline" onClick={async () => {
                  await navigator.clipboard.writeText(row.join_url || "");
                  setNotice("Join link copied.");
                }}>Copy link</Button>
                {row.meeting_url ? <a className="text-sm underline" href={row.meeting_url} target="_blank" rel="noreferrer">{row.meeting_provider === "teams" ? "Teams room" : "Google Meet room"}</a> : null}
                <Button size="sm" variant="outline" onClick={async () => {
                  setError("");
                  setNotice("");
                  try {
                    await api(`/api/v1/interviews/${row.id}/invite/`, { method: "POST", json: {} });
                    setNotice("Invitation emailed to the candidate.");
                    client.invalidateQueries({ queryKey: ["interviews"] });
                  } catch (err) {
                    setError(errorText(err));
                  }
                }}>{row.invited_at ? "Re-send invitation" : "Email invitation"}</Button>
              </div>
            ) : null}
            {report?.summary ? (
              <div className="grid gap-1 rounded-md bg-surface-muted p-3">
                <p className="text-sm font-medium">AI feedback · {labelize(report.recommendation || "pending")}{report.score === null ? "" : ` · ${report.score}/100`}</p>
                <p className="text-sm">{report.summary}</p>
                <p className="text-xs text-muted">This is decision support. The AI does not pass or fail the candidate.</p>
              </div>
            ) : answered ? (
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm text-muted">Answers are in; the AI feedback is not ready.</p>
                <Button size="sm" variant="outline" onClick={async () => {
                  setError("");
                  setNotice("");
                  try {
                    await api(`/api/v1/interviews/${row.id}/ai-report/`, { method: "POST", json: {} });
                    setNotice("AI feedback generated and emailed to the recruiter.");
                    client.invalidateQueries({ queryKey: ["interviews"] });
                  } catch (err) {
                    setError(errorText(err));
                  }
                }}>Generate and email feedback</Button>
              </div>
            ) : (
              <p className="text-sm text-muted">Waiting for the candidate to answer.</p>
            )}
            {row.questions.length ? (
              <details>
                <summary className="cursor-pointer text-sm">Questions and answers</summary>
                <ol className="mt-2 grid list-decimal gap-2 pl-5">
                  {row.questions.map((question) => (
                    <li key={question.id} className="text-sm">
                      <p>{question.prompt}</p>
                      <p className="text-muted">{question.answer || "Not answered yet."}</p>
                    </li>
                  ))}
                </ol>
              </details>
            ) : null}
          </div>
        ) : null}
        <form className="grid gap-2 md:grid-cols-[1fr_120px_140px]" onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          try {
            await api(`/api/v1/interviews/${row.id}/feedback/`, { method: "POST", json: { feedback, rating: rating || null, outcome } });
            client.invalidateQueries({ queryKey: ["interviews"] });
            client.invalidateQueries({ queryKey: ["submissions"] });
          } catch (err) {
            setError(errorText(err));
          }
        }}>
          <Textarea aria-label="Feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder={ai ? "Review the AI feedback and answers, then record your decision." : "What should the hiring team know?"} />
          <Input aria-label="Rating" value={rating} onChange={(event) => setRating(event.target.value)} placeholder="Rating 1–5" />
          <Select label="Outcome" value={outcome} onChange={setOutcome}>
            <option value="passed">Passed</option>
            <option value="failed">Failed</option>
          </Select>
          {error ? <ErrorState message={error} /> : null}
          {notice ? <p className="text-sm text-muted md:col-span-3">{notice}</p> : null}
          <Button type="submit" size="sm">Save feedback</Button>
        </form>
      </Card>
    </li>
  );
}

export function TaskPage() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api<{ count: number; results: Task[] }>("/api/v1/tasks/?page_size=50"),
  });
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [error, setError] = useState("");
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Follow-ups</h1>
      <form className="flex flex-wrap gap-2" onSubmit={async (event) => {
        event.preventDefault();
        setError("");
        try {
          await api("/api/v1/tasks/", { method: "POST", json: { title, due_at: due ? new Date(due).toISOString() : null } });
          setTitle("");
          client.invalidateQueries({ queryKey: ["tasks"] });
        } catch (err) {
          setError(errorText(err));
        }
      }}>
        <Input aria-label="Follow-up" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Call back about notice period" />
        <Input aria-label="Due" type="date" value={due} onChange={(event) => setDue(event.target.value)} />
        <Button type="submit">Add follow-up</Button>
      </form>
      {error ? <ErrorState message={error} /> : null}
      {query.isLoading ? <Loading /> : null}
      {query.data?.results.length === 0 ? <Empty title="Nothing due" body="Add a follow-up so it shows on the desk." /> : null}
      <ul className="grid gap-2">
        {query.data?.results.map((task) => (
          <li key={task.id}>
            <Card className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p>{task.title}</p>
                <p className="text-sm text-muted">{task.candidate_name || "No candidate"} · {task.due_at ? when(task.due_at) : "No due date"} · {labelize(task.status)}</p>
              </div>
              <Button size="sm" variant="outline" onClick={async () => {
                await api(`/api/v1/tasks/${task.id}/`, { method: "PATCH", json: { status: task.status === "open" ? "done" : "open" } });
                client.invalidateQueries({ queryKey: ["tasks"] });
              }}>{task.status === "open" ? "Mark done" : "Reopen"}</Button>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
