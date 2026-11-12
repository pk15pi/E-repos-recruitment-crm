import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ErrorState, Loading } from "../components/states";
import { Badge, Button, Card } from "../components/ui";
import { ProfileForm } from "./profile-form";
import { api, uploadFiles, type UploadItem } from "../lib/api";
import { errorText, labelize } from "../lib/format";
import type { Draft, DuplicateHit, Profile } from "../lib/types";

type Row = UploadItem & { progress: number; polling?: boolean };

export function UploadPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState("");

  async function send(files: File[]) {
    setError("");
    if (!files.length) return;
    setRows((current) => [
      ...current,
      ...files.map((file) => ({ filename: file.name, resume_id: null, status: "uploading", progress: 0 })),
    ]);
    try {
      const result = await uploadFiles(files, (percent) => {
        setRows((current) => current.map((row) => (row.status === "uploading" ? { ...row, progress: percent } : row)));
      });
      setRows((current) => {
        const pending = current.filter((row) => row.status !== "uploading");
        return [...pending, ...result.items.map((item) => ({ ...item, progress: 100 }))];
      });
    } catch (err) {
      setError(errorText(err));
      setRows((current) => current.map((row) => (row.status === "uploading" ? { ...row, status: "rejected", error: errorText(err) } : row)));
    }
  }

  useEffect(() => {
    const active = rows.filter((row) => row.resume_id && !["needs_review", "confirmed", "failed", "rejected"].includes(row.status));
    if (!active.length) return;
    const timer = window.setTimeout(async () => {
      const updates = await Promise.all(
        active.map(async (row) => {
          const status = await api<{ status: string; error_message: string }>(`/api/v1/resumes/${row.resume_id}/status/`);
          return { id: row.resume_id, status: status.status, error: status.error_message };
        }),
      );
      setRows((current) =>
        current.map((row) => {
          const update = updates.find((item) => item.id === row.resume_id);
          return update ? { ...row, status: update.status, error: update.error || row.error } : row;
        }),
      );
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [rows]);

  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-4xl">Upload resumes</h1>
        <p className="text-sm text-muted">PDF, DOCX, TXT, or a ZIP of those. Files stay private. Nothing is written to a candidate until you confirm the draft.</p>
      </div>
      <label
        data-testid="dropzone"
        onDragOver={(event) => {
          event.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDrag(false);
          send(Array.from(event.dataTransfer.files));
        }}
        className={`grid cursor-pointer place-items-center rounded-lg border border-dashed px-4 py-12 text-center ${drag ? "border-accent bg-accent-soft" : "border-line bg-card"}`}
      >
        <input
          aria-label="Resume files"
          className="sr-only"
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.txt,.zip,application/pdf,text/plain"
          onChange={(event) => {
            send(Array.from(event.target.files || []));
            event.target.value = "";
          }}
        />
        <span className="text-sm">Drop files here, or choose them. A ZIP is unpacked on the server with size limits.</span>
      </label>
      {error ? <ErrorState message={error} /> : null}
      <ul className="grid gap-2">
        {rows.map((row, index) => (
          <li key={`${row.filename}-${index}`}>
            <UploadRow row={row} onRetry={() => row.resume_id && retry(row.resume_id, setRows)} />
          </li>
        ))}
      </ul>
    </div>
  );
}

async function retry(id: string, setRows: React.Dispatch<React.SetStateAction<Row[]>>) {
  await api(`/api/v1/resumes/${id}/retry/`, { method: "POST" });
  setRows((current) => current.map((row) => (row.resume_id === id ? { ...row, status: "stored", error: "" } : row)));
}

export function UploadRow({ row, onRetry }: { row: Row; onRetry: () => void }) {
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="font-medium">{row.filename}</p>
        <p className="text-sm text-muted">{labelize(row.status)}{row.progress && row.status === "uploading" ? ` · ${row.progress}%` : ""}</p>
        {row.duplicate_warning ? <p className="text-sm text-warn">{row.duplicate_warning}</p> : null}
        {row.error ? <p className="text-sm text-danger">{row.error}</p> : null}
      </div>
      <div className="flex gap-2">
        {row.status === "failed" ? <Button size="sm" variant="outline" onClick={onRetry}>Retry</Button> : null}
        {row.resume_id && ["needs_review", "confirmed"].includes(row.status) ? (
          <Button size="sm" asChild><Link to={`/resumes/${row.resume_id}/review`}>Review</Link></Button>
        ) : null}
      </div>
    </Card>
  );
}

export function ReviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [ack, setAck] = useState(false);
  const [overwrite, setOverwrite] = useState<string[]>([]);
  const [target, setTarget] = useState("");
  const [pages, setPages] = useState<{ page: number | null; text: string }[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stop = false;
    async function load() {
      const status = await api<{ status: string; error_message: string }>(`/api/v1/resumes/${id}/status/`);
      if (stop) return;
      if (["needs_review", "confirmed", "failed"].includes(status.status)) {
        const next = await api<Draft>(`/api/v1/resumes/${id}/draft/`);
        if (stop) return;
        setDraft(next);
        setProfile((current) => current ?? next.profile);
        const text = await api<{ pages: { page: number | null; text: string }[] }>(`/api/v1/resumes/${id}/text/`);
        if (!stop) setPages(text.pages);
        return;
      }
      window.setTimeout(load, 1200);
    }
    load().catch((err) => setError(errorText(err)));
    return () => {
      stop = true;
    };
  }, [id]);

  if (error && !draft) return <ErrorState message={error} />;
  if (!draft || !profile) return <Loading label="Reading the resume" />;
  const blocking = (draft.duplicates || []).filter((item) => item.blocking);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ candidate_id: string; skipped_verified: string[] }>(`/api/v1/resumes/${id}/confirm/`, {
        method: "POST",
        json: {
          profile,
          acknowledge_duplicates: ack,
          overwrite_verified: overwrite,
          candidate_id: target || undefined,
        },
      });
      navigate(`/candidates/${result.candidate_id}`);
    } catch (err) {
      const details = (err as { details?: { duplicates?: DuplicateHit[] } }).details;
      if (details?.duplicates) setDraft((current) => (current ? { ...current, duplicates: details.duplicates || [] } : current));
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-4xl">Review extraction</h1>
        <p className="text-sm text-muted">
          {draft.provider_label}. Schema {draft.schema_version || "n/a"}. Nothing is saved until you confirm. Low-confidence and conflicting fields are highlighted.
        </p>
      </div>
      {draft.warnings?.length ? (
        <Card>
          <h2 className="text-xl">Warnings</h2>
          <ul className="mt-2 list-disc pl-5 text-sm">{draft.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
        </Card>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="max-h-[80vh] overflow-auto">
          <h2 className="text-xl">{draft.resume.filename}</h2>
          <p className="text-xs text-muted">Text extracted for review. The original file stays in private storage.</p>
          {pages.length === 0 ? <p className="mt-3 text-sm">Not provided</p> : pages.map((page, index) => (
            <article key={index} className="mt-4">
              <p className="text-xs text-muted">Page {page.page ?? index + 1}</p>
              <pre className="mt-1 whitespace-pre-wrap font-sans text-sm">{page.text}</pre>
            </article>
          ))}
        </Card>
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            confirm();
          }}
        >
          <ProfileForm value={profile} onChange={setProfile} fields={draft.fields} />
          <div className="grid gap-2">
            {draft.duplicates?.map((item) => (
              <p key={`${item.kind}-${item.candidate_id}`} className="text-sm text-warn">
                <Badge tone={item.blocking ? "bad" : "warn"}>{item.blocking ? "Needs review" : "Warning"}</Badge> {item.kind}: {item.name} — {item.detail}{" "}
                <Link className="text-accent" to={`/candidates/${item.candidate_id}`}>Open</Link>
              </p>
            ))}
          </div>
          {blocking.length ? (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />
              I reviewed the duplicate and still want a separate record. Names are never merged automatically.
            </label>
          ) : null}
          <label className="grid gap-1 text-sm">
            Update this existing candidate instead
            <input className="h-10 rounded-md border border-line px-3" value={target} onChange={(event) => setTarget(event.target.value)} placeholder="Candidate id, optional" />
          </label>
          <fieldset className="grid gap-1 text-sm">
            <legend>Overwrite verified fields</legend>
            {["full_name", "summary", "skills", "emails", "experiences"].map((field) => (
              <label key={field} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={overwrite.includes(field)}
                  onChange={(event) =>
                    setOverwrite((current) => (event.target.checked ? [...current, field] : current.filter((item) => item !== field)))
                  }
                />
                {labelize(field)}
              </label>
            ))}
            <p className="text-xs text-muted">Verified values already on a candidate stay put unless you check them here.</p>
          </fieldset>
          {error ? <ErrorState message={error} /> : null}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={async () => {
              const next = await api<Draft>(`/api/v1/resumes/${id}/correct/`, { method: "PATCH", json: { profile } });
              setDraft(next);
              setProfile(next.profile);
            }}>Save corrections</Button>
            <Button type="submit" disabled={busy || (blocking.length > 0 && !ack)}>{busy ? "Saving…" : "Verify and save candidate"}</Button>
            <Button type="button" variant="ghost" onClick={() => api(`/api/v1/resumes/${id}/retry/`, { method: "POST" }).then(() => window.location.reload())}>Retry parse</Button>
          </div>
        </form>
      </div>
    </div>
  );
}
