import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Empty, ErrorState, Loading, Missing } from "../components/states";
import { Badge, Button, Card, Input, Select, Textarea } from "../components/ui";
import { detailToProfile, ProfileForm } from "./profile-form";
import { api, downloadAuthorized, type Page } from "../lib/api";
import { isAdmin, isAgency, useAuth } from "../lib/auth";
import { day, errorText, labelize, monthsLabel, show, when } from "../lib/format";
import type { CandidateCard, CandidateDetail, Note, Profile, Submission } from "../lib/types";

export function CandidateListPage() {
  const { user } = useAuth();
  const agency = isAgency(user);
  const [params, setParams] = useSearchParams();
  const [picked, setPicked] = useState<string[]>([]);
  const navigate = useNavigate();
  const queryString = params.toString();
  const query = useQuery({
    queryKey: ["candidates", queryString],
    queryFn: () => api<Page<CandidateCard>>(`/api/v1/candidates/${queryString ? `?${queryString}` : ""}`),
  });

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    Object.entries(next).forEach(([key, value]) => {
      if (value) merged.set(key, value);
      else merged.delete(key);
    });
    if (!("page" in next)) merged.delete("page");
    setParams(merged);
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-4xl">Candidates</h1>
          <p className="text-sm text-muted">Search, sort, and filters run on the server. Blank fields stay blank.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {agency ? (
            <Button variant="outline" onClick={() => downloadAuthorized("/api/v1/candidates/export/", "candidates.csv")}>
              Export CSV
            </Button>
          ) : null}
          {agency ? (
            <Button onClick={() => navigate("/candidates/new")}>Add a person</Button>
          ) : null}
          <Button
            variant="outline"
            disabled={picked.length < 2 || picked.length > 3}
            onClick={() => navigate(`/compare?ids=${picked.join(",")}`)}
          >
            Compare
          </Button>
        </div>
      </div>
      <Card className="grid gap-3 md:grid-cols-4">
        <Input aria-label="Search name or text" placeholder="Name or words" defaultValue={params.get("q") || ""} onBlur={(event) => update({ q: event.target.value })} />
        <Input aria-label="Location" placeholder="Location" defaultValue={params.get("location") || ""} onBlur={(event) => update({ location: event.target.value })} />
        <Input aria-label="Skill" placeholder="Skill" defaultValue={params.get("skill") || ""} onBlur={(event) => update({ skill: event.target.value })} />
        <Select label="Status" value={params.get("status") || ""} onChange={(value) => update({ status: value })}>
          <option value="">Any status</option>
          {["new", "active", "passive", "placed", "do_not_contact", "archived"].map((status) => (
            <option key={status} value={status}>{labelize(status)}</option>
          ))}
        </Select>
        <Select label="Sort" value={params.get("ordering") || "-updated_at"} onChange={(value) => update({ ordering: value })}>
          <option value="-updated_at">Recently updated</option>
          <option value="full_name">Name</option>
          <option value="-total_experience_months">Experience</option>
        </Select>
      </Card>
      {query.isLoading ? <Loading /> : null}
      {query.isError ? <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} /> : null}
      {query.data && query.data.results.length === 0 ? (
        <Empty title="No one matches" body="Widen the filters, or upload a resume and confirm the draft." action={agency ? <Link className="text-accent" to="/upload">Upload resumes</Link> : undefined} />
      ) : null}
      <ul className="grid gap-3">
        {query.data?.results.map((row) => (
          <li key={row.id}>
            <Card className="grid gap-2 md:grid-cols-[auto_1fr_auto] md:items-center">
              <input
                type="checkbox"
                aria-label={`Select ${row.full_name || "candidate"}`}
                checked={picked.includes(row.id)}
                onChange={(event) =>
                  setPicked((current) => (event.target.checked ? [...current, row.id].slice(-3) : current.filter((id) => id !== row.id)))
                }
              />
              <div>
                <Link className="font-serif text-2xl" to={`/candidates/${row.id}`}>{row.full_name || "Unnamed candidate"}</Link>
                <p className="text-sm text-muted">
                  {show(row.current_title)} · {show(row.current_employer)} · {show(row.location)}
                </p>
                <p className="text-sm">{monthsLabel(row.total_experience_months)} · {row.skills.map((skill) => skill.name).join(", ") || "No skills recorded"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {row.is_global ? <Badge tone="warn">Global · {row.owner_organization?.name || "another organization"}</Badge> : null}
                <Badge>{labelize(row.verification_status)}</Badge>
                <Badge tone="neutral">{labelize(row.status)}</Badge>
              </div>
            </Card>
          </li>
        ))}
      </ul>
      {query.data ? (
        <div className="flex items-center justify-between text-sm">
          <span>{query.data.count} on file</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={!query.data.previous} onClick={() => update({ page: String(Math.max(1, Number(params.get("page") || 1) - 1)) })}>
              Previous
            </Button>
            <Button variant="outline" size="sm" disabled={!query.data.next} onClick={() => update({ page: String(Number(params.get("page") || 1) + 1) })}>
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function CandidateEditPage() {
  const { id } = useParams();
  const creating = !id || id === "new";
  const navigate = useNavigate();
  const client = useQueryClient();
  const existing = useQuery({
    queryKey: ["candidate", id],
    enabled: !creating,
    queryFn: () => api<CandidateDetail>(`/api/v1/candidates/${id}/`),
  });
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const current = profile ?? (existing.data ? detailToProfile(existing.data) : creating ? { status: "active", emails: [], skills: [] } : null);

  const save = useMutation({
    mutationFn: async () => {
      if (!current) return;
      if (creating) return api<CandidateDetail>("/api/v1/candidates/", { method: "POST", json: current });
      return api<CandidateDetail>(`/api/v1/candidates/${id}/`, { method: "PATCH", json: current });
    },
    onSuccess: (row) => {
      if (!row) return;
      client.invalidateQueries({ queryKey: ["candidates"] });
      navigate(`/candidates/${row.id}`);
    },
    onError: (err) => setError(errorText(err)),
  });

  if (!creating && existing.isLoading) return <Loading />;
  if (!creating && existing.isError) return <ErrorState message={errorText(existing.error)} onRetry={() => existing.refetch()} />;
  if (!creating && existing.data?.is_global) {
    return (
      <div className="grid gap-3">
        <h1 className="text-4xl">Edit profile</h1>
        <p className="text-sm text-muted">
          This profile belongs to {existing.data.owner_organization?.name || "another organization"} and is shared with
          your desk read-only.
        </p>
        <Link className="text-accent" to={`/candidates/${id}`}>Back to the profile</Link>
      </div>
    );
  }
  if (!current) return null;
  return (
    <form
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <h1 className="text-4xl">{creating ? "Add a person" : "Edit profile"}</h1>
      <p className="text-sm text-muted">Saving here is an explicit edit. Verified extraction fields are replaced because you are editing them yourself.</p>
      {error ? <ErrorState message={error} /> : null}
      <ProfileForm value={current} onChange={setProfile} />
      <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save profile"}</Button>
    </form>
  );
}

export function CandidateDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const agency = isAgency(user);
  const admin = isAdmin(user);
  const client = useQueryClient();
  const [tab, setTab] = useState("overview");
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["candidate", id],
    queryFn: () => api<CandidateDetail>(`/api/v1/candidates/${id}/`),
  });
  const resumes = useQuery({
    queryKey: ["candidate-resumes", id],
    queryFn: () => api<{ id: string; filename: string; status: string; created_at: string }[]>(`/api/v1/candidates/${id}/resumes/`),
  });
  const history = useQuery({
    queryKey: ["candidate-history", id],
    enabled: tab === "audit" && agency,
    queryFn: () => api<{ id: string; action: string; detail: string; actor: string | null; created_at: string }[]>(`/api/v1/candidates/${id}/history/`),
  });
  const similar = useQuery({
    queryKey: ["similar", id],
    enabled: tab === "overview" && agency,
    queryFn: () => api<CandidateCard[]>(`/api/v1/candidates/${id}/similar/`),
  });
  const submissions = useQuery({
    queryKey: ["submissions"],
    enabled: tab === "pipeline",
    queryFn: () => api<Submission[]>("/api/v1/submissions/"),
  });

  if (query.isLoading) return <Loading label="Loading profile" />;
  if (query.isError) return <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} />;
  const person = query.data!;
  const global = person.is_global;
  const tabs = ["overview", "contact", "employment", "skills", "education", "projects", "resume", "evidence", "notes", "pipeline", "audit"];

  async function act(path: string, json?: unknown, method = "POST") {
    setError("");
    try {
      await api(path, { method, json });
      client.invalidateQueries({ queryKey: ["candidate", id] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-4xl">{person.full_name || "Unnamed candidate"}</h1>
          <p className="text-sm text-muted">{show(person.current_title)} at {show(person.current_employer)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {global ? <Badge tone="warn">Global · {person.owner_organization?.name || "another organization"}</Badge> : null}
          <Badge tone={person.verification_status === "verified" ? "good" : "warn"}>{labelize(person.verification_status)}</Badge>
          {agency && !global ? <Button variant="outline" onClick={() => { window.location.href = `/candidates/${id}/edit`; }}>Edit</Button> : null}
          {agency && !global ? <Button variant="outline" onClick={() => act(`/api/v1/candidates/${id}/archive/`)}>Archive</Button> : null}
          {admin && !global ? <Button variant="danger" onClick={() => act(`/api/v1/candidates/${id}/deletion-request/`)}>Request deletion</Button> : null}
        </div>
      </div>
      {global ? (
        <p className="rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-warn">
          Shared read-only from {person.owner_organization?.name || "another organization"}. You can review and compare
          this profile, but not edit, archive, or add notes to it.
        </p>
      ) : null}
      {error ? <ErrorState message={error} /> : null}
      <div className="flex gap-2 overflow-auto" role="tablist">
        {tabs.filter((item) => {
          if (global && ["notes", "pipeline", "audit"].includes(item)) return false;
          return agency || !["audit", "evidence"].includes(item) || item === "evidence";
        }).map((item) => (
          <button key={item} role="tab" aria-selected={tab === item} className={`rounded-full px-3 py-1 text-sm capitalize ${tab === item ? "bg-ink text-white" : "bg-card"}`} onClick={() => setTab(item)}>
            {item === "pipeline" ? "Submissions" : item}
          </button>
        ))}
      </div>
      {tab === "overview" ? (
        <Card className="grid gap-2 text-sm">
          <p>{person.summary || "Not provided"}</p>
          <p>Location: <Missing value={person.location} /></p>
          <p>Experience: {monthsLabel(person.total_experience_months)} total, {monthsLabel(person.relevant_experience_months)} relevant</p>
          <p>Work mode: <Missing value={person.work_mode} /> · Employment: <Missing value={person.employment_type} /></p>
          <p>Notice: <Missing value={person.notice_period_days} /> days · Available: {day(person.availability_date)}</p>
          <p>Expected compensation: {person.compensation_visible ? show(person.expected_salary_amount) : "Not shared"} {person.compensation_visible ? person.expected_salary_currency || "" : ""}</p>
          <p>Updated {when(person.updated_at)}</p>
          {agency && similar.data ? (
            <div>
              <h2 className="text-xl">Similar people</h2>
              {similar.data.length === 0 ? <p className="text-muted">No similar profiles yet.</p> : similar.data.map((row) => (
                <Link key={row.id} className="block text-accent" to={`/candidates/${row.id}`}>{row.full_name || "Unnamed"}</Link>
              ))}
            </div>
          ) : null}
          {agency && !global ? <SummaryDraft id={person.id} /> : null}
        </Card>
      ) : null}
      {tab === "contact" ? (
        <Card className="grid gap-2 text-sm">
          {person.contact_visible ? (
            <>
              <p>Emails: {person.emails.length ? person.emails.map((row) => row.email).join(", ") : "Not provided"}</p>
              <p>Phones: {person.phones.length ? person.phones.map((row) => row.raw).join(", ") : "Not provided"}</p>
              <p>LinkedIn: <Missing value={person.linkedin_url} /></p>
              <p>GitHub: <Missing value={person.github_url} /></p>
              <p>Portfolio: <Missing value={person.portfolio_url} /></p>
            </>
          ) : (
            <p>Contact details were not included in this share.</p>
          )}
          <p>Preferred locations: {person.preferred_locations.join(", ") || "Not provided"}</p>
          <p>Relocation: <Missing value={person.willing_to_relocate} /></p>
        </Card>
      ) : null}
      {tab === "employment" ? (
        <Card className="grid gap-3">
          {person.experiences.length === 0 ? <p className="text-sm text-muted">Not provided</p> : person.experiences.map((row) => (
            <div key={row.id || row.title || ""}>
              <p className="font-medium">{show(row.title)} · {show(row.employer)}</p>
              <p className="text-sm text-muted">{day(row.start_date)} – {row.is_current ? "Present" : day(row.end_date)}</p>
              <p className="text-sm">{row.description || ""}</p>
            </div>
          ))}
        </Card>
      ) : null}
      {tab === "skills" ? (
        <Card className="flex flex-wrap gap-2">
          {person.skills.length === 0 ? <p className="text-sm text-muted">Not provided</p> : person.skills.map((skill) => (
            <Badge key={skill.name} tone={skill.source === "verified" ? "good" : skill.source === "extracted" ? "warn" : "neutral"}>
              {skill.name} · {skill.source || "recorded"}
            </Badge>
          ))}
        </Card>
      ) : null}
      {tab === "education" ? (
        <Card className="grid gap-3 text-sm">
          <div>
            <h2 className="text-xl">Education</h2>
            {person.education.length === 0 ? <p className="text-muted">Not provided</p> : person.education.map((row) => (
              <p key={row.id}>{show(row.degree)} · {show(row.institution)} · {show(row.field_of_study)}</p>
            ))}
          </div>
          <div>
            <h2 className="text-xl">Certifications</h2>
            {person.certifications.length === 0 ? <p className="text-muted">Not provided</p> : person.certifications.map((row) => (
              <p key={row.id}>{row.name} · {show(row.issuer)}</p>
            ))}
          </div>
          <div>
            <h2 className="text-xl">Languages</h2>
            {person.languages.length === 0 ? <p className="text-muted">Not provided</p> : person.languages.map((row) => (
              <p key={row.id}>{row.language} · {show(row.proficiency)}</p>
            ))}
          </div>
        </Card>
      ) : null}
      {tab === "projects" ? (
        <Card className="grid gap-2">
          {person.projects.length === 0 ? <p className="text-sm text-muted">Not provided</p> : person.projects.map((row) => (
            <div key={row.id}><p className="font-medium">{row.name}</p><p className="text-sm">{row.description || "Not provided"}</p></div>
          ))}
        </Card>
      ) : null}
      {tab === "resume" ? (
        <Card className="grid gap-2">
          {resumes.isLoading ? <Loading /> : null}
          {resumes.data?.length === 0 ? <p className="text-sm text-muted">No resume is attached, or this share does not include the file.</p> : null}
          {resumes.data?.map((row) => (
            <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>{row.filename} · {labelize(row.status)}</span>
              {global ? (
                <span className="text-xs text-muted">Owned by {person.owner_organization?.name || "another organization"}</span>
              ) : (
                <Button size="sm" variant="outline" onClick={async () => {
                  const link = await api<{ url: string }>(`/api/v1/resumes/${row.id}/download/`, { method: "POST" });
                  window.open(link.url, "_blank", "noopener");
                }}>Download</Button>
              )}
            </div>
          ))}
        </Card>
      ) : null}
      {tab === "evidence" ? (
        <Card className="text-sm">
          <p>Skill badges mark verified, extracted, or recruiter-entered values. Extraction quotes live on the review screen for each resume version.</p>
          <p className="mt-2">Verification: {labelize(person.verification_status)}. Source: {show(person.source)}</p>
          {agency && !global ? <p className="mt-2">Consents: {person.consents.length ? person.consents.map((row) => `${row.purpose} (${row.granted ? "granted" : "refused"})`).join("; ") : "Not provided"}</p> : null}
          {agency && !global ? <ConsentForm id={person.id} /> : null}
        </Card>
      ) : null}
      {tab === "notes" ? <NotesPanel id={person.id} notes={person.notes} agency={agency && !global} /> : null}
      {tab === "pipeline" ? (
        <Card className="grid gap-2 text-sm">
          {(submissions.data || []).filter((row) => row.candidate_id === id).length === 0 ? <p className="text-muted">No submissions yet.</p> : null}
          {(submissions.data || []).filter((row) => row.candidate_id === id).map((row) => (
            <p key={row.id}>{row.job_title || "Untitled role"} · {row.client_name} · {labelize(row.stage)}</p>
          ))}
        </Card>
      ) : null}
      {tab === "audit" && agency ? (
        <Card className="grid gap-2 text-sm">
          {history.isLoading ? <Loading /> : null}
          {history.data?.length === 0 ? <p className="text-muted">No audit events yet.</p> : null}
          {history.data?.map((row) => (
            <p key={row.id}>{when(row.created_at)} · {labelize(row.action)} · {row.actor || "system"} · {row.detail || "Not provided"}</p>
          ))}
          {admin ? <MergeBox id={person.id} /> : null}
        </Card>
      ) : null}
    </div>
  );
}

function SummaryDraft({ id }: { id: string }) {
  const [text, setText] = useState("");
  const [label, setLabel] = useState("");
  return (
    <div className="mt-3 grid gap-2">
      <Button variant="outline" size="sm" onClick={async () => {
        const data = await api<{ summary: string; provider_label: string; saved: boolean }>(`/api/v1/candidates/${id}/summary/`, { method: "POST" });
        setText(data.summary || "");
        setLabel(`${data.provider_label}. Not saved until you edit the profile.`);
      }}>Draft a summary</Button>
      {label ? <p className="text-xs text-muted">{label}</p> : null}
      {text ? <p>{text}</p> : null}
    </div>
  );
}

function NotesPanel({ id, notes, agency }: { id: string; notes: Note[]; agency: boolean }) {
  const client = useQueryClient();
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState("private");
  const [error, setError] = useState("");
  return (
    <Card className="grid gap-3">
      {notes.length === 0 ? <p className="text-sm text-muted">No notes yet.</p> : notes.map((note) => (
        <article key={note.id} className="text-sm">
          <p>{note.body}</p>
          <p className="text-xs text-muted">{note.visibility === "private" ? "Recruiter only" : "Visible to the client"} · {note.author || "Unknown"} · {when(note.created_at)}</p>
        </article>
      ))}
      {agency ? (
        <form className="grid gap-2" onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          try {
            await api(`/api/v1/candidates/${id}/notes/`, { method: "POST", json: { body, visibility } });
            setBody("");
            client.invalidateQueries({ queryKey: ["candidate", id] });
          } catch (err) {
            setError(errorText(err));
          }
        }}>
          <Textarea aria-label="Note" value={body} onChange={(event) => setBody(event.target.value)} placeholder="Private notes stay off the client view." />
          <Select label="Visibility" value={visibility} onChange={setVisibility}>
            <option value="private">Recruiter only</option>
            <option value="client">Client can read this</option>
          </Select>
          {error ? <ErrorState message={error} /> : null}
          <Button type="submit">Save note</Button>
        </form>
      ) : null}
    </Card>
  );
}

function ConsentForm({ id }: { id: string }) {
  const client = useQueryClient();
  const [purpose, setPurpose] = useState("Consider for client roles");
  return (
    <form className="mt-3 grid gap-2" onSubmit={async (event) => {
      event.preventDefault();
      await api(`/api/v1/candidates/${id}/consents/`, { method: "POST", json: { purpose, lawful_basis: "consent", granted: true, source: "recruiter" } });
      client.invalidateQueries({ queryKey: ["candidate", id] });
    }}>
      <Input aria-label="Consent purpose" value={purpose} onChange={(event) => setPurpose(event.target.value)} />
      <Button type="submit" size="sm">Record consent</Button>
    </form>
  );
}

function MergeBox({ id }: { id: string }) {
  const [source, setSource] = useState("");
  const [ack, setAck] = useState(false);
  const [message, setMessage] = useState("");
  return (
    <form className="mt-4 grid gap-2" onSubmit={async (event) => {
      event.preventDefault();
      setMessage("");
      try {
        await api(`/api/v1/candidates/${id}/merge/`, { method: "POST", json: { source_id: source, acknowledge: ack } });
        setMessage("Merged. The source profile is archived.");
      } catch (err) {
        setMessage(errorText(err));
      }
    }}>
      <h2 className="text-xl">Merge another profile into this one</h2>
      <p className="text-xs text-muted">Name matches are never merged on their own. Confirm you reviewed both records.</p>
      <Input aria-label="Source candidate id" value={source} onChange={(event) => setSource(event.target.value)} placeholder="Source candidate id" />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />
        I reviewed both profiles
      </label>
      <Button type="submit" variant="danger" size="sm">Merge</Button>
      {message ? <p className="text-sm">{message}</p> : null}
    </form>
  );
}

export function ComparePage() {
  const [params] = useSearchParams();
  const ids = useMemo(() => (params.get("ids") || "").split(",").filter(Boolean), [params]);
  const query = useQuery({
    queryKey: ["compare", ids.join(",")],
    enabled: ids.length >= 2,
    queryFn: () => api<CandidateDetail[]>(`/api/v1/candidates/compare/?${ids.map((id) => `id=${id}`).join("&")}`),
  });
  if (ids.length < 2) return <Empty title="Pick two or three people" body="Select them from the candidate list, then compare." />;
  if (query.isLoading) return <Loading />;
  if (query.isError) return <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} />;
  const rows = query.data || [];
  const fields: [string, (row: CandidateDetail) => string][] = [
    ["Title", (row) => show(row.current_title)],
    ["Employer", (row) => show(row.current_employer)],
    ["Location", (row) => show(row.location)],
    ["Experience", (row) => monthsLabel(row.total_experience_months)],
    ["Skills", (row) => row.skills.map((skill) => skill.name).join(", ") || "Not provided"],
    ["Verification", (row) => labelize(row.verification_status)],
    ["Email", (row) => (row.contact_visible ? row.emails[0]?.email || "Not provided" : "Not shared")],
  ];
  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Comparison</h1>
      <div className="overflow-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr>
              <th className="p-2 text-left">Field</th>
              {rows.map((row) => (
                <th key={row.id} className="p-2 text-left">
                  <Link to={`/candidates/${row.id}`}>{row.full_name || "Unnamed"}</Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fields.map(([label, read]) => (
              <tr key={label} className="border-t border-line">
                <td className="p-2 text-muted">{label}</td>
                {rows.map((row) => <td key={row.id} className="p-2">{read(row)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
