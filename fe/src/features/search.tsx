import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { Empty, ErrorState, Loading } from "../components/states";
import { Button, Card, Input, Textarea } from "../components/ui";
import { api, type Page } from "../lib/api";
import { errorText, monthsLabel, show } from "../lib/format";
import type { CandidateCard } from "../lib/types";

const MAX = 4000;

export function SearchPage() {
  const [mode, setMode] = useState<"structured" | "boolean" | "hybrid">("structured");
  const [error, setError] = useState("");
  const [page, setPage] = useState<Page<CandidateCard> | null>(null);
  const [name, setName] = useState("");
  const [notify, setNotify] = useState(false);
  const saved = useQuery({
    queryKey: ["saved-searches"],
    queryFn: () => api<Saved[]>("/api/v1/search/saved/"),
  });
  const history = useQuery({
    queryKey: ["search-history"],
    queryFn: () => api<{ id: string; mode: string; query_text: string; created_at: string }[]>("/api/v1/search/history/"),
  });
  const client = useQueryClient();
  const [filters, setFilters] = useState({ location: "", skill: "", title: "", work_mode: "", experience_min_months: "" });
  const [booleanQuery, setBooleanQuery] = useState("");
  const [text, setText] = useState("");

  async function run(extraPage = 1) {
    setError("");
    const payload = {
      filters: Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== "")),
      query: mode === "boolean" ? booleanQuery : text,
      boolean_query: booleanQuery,
      semantic_query: text,
    };
    try {
      const path = mode === "structured" ? "/api/v1/search/structured/" : mode === "boolean" ? "/api/v1/search/boolean/" : "/api/v1/search/hybrid/";
      const data = await api<Page<CandidateCard>>(`${path}?page=${extraPage}`, { method: "POST", json: payload });
      setPage(data);
      client.invalidateQueries({ queryKey: ["search-history"] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Search the file</h1>
      <p className="text-sm text-muted">Boolean search accepts AND, OR, NOT, and quotes. Unknown values do not fail a filter unless you later hide them in a saved search.</p>
      <div className="flex gap-2">
        {(["structured", "boolean", "hybrid"] as const).map((item) => (
          <Button key={item} type="button" variant={mode === item ? "default" : "outline"} size="sm" onClick={() => setMode(item)}>
            {item}
          </Button>
        ))}
      </div>
      <Card className="grid gap-3">
        <div className="grid gap-2 md:grid-cols-3">
          <Input aria-label="Title contains" placeholder="Title" value={filters.title} onChange={(event) => setFilters({ ...filters, title: event.target.value })} />
          <Input aria-label="Location filter" placeholder="Location" value={filters.location} onChange={(event) => setFilters({ ...filters, location: event.target.value })} />
          <Input aria-label="Skill filter" placeholder="Skill" value={filters.skill} onChange={(event) => setFilters({ ...filters, skill: event.target.value })} />
          <Input aria-label="Minimum months" placeholder="Min months" value={filters.experience_min_months} onChange={(event) => setFilters({ ...filters, experience_min_months: event.target.value })} />
          <Input aria-label="Work mode filter" placeholder="remote, hybrid, onsite" value={filters.work_mode} onChange={(event) => setFilters({ ...filters, work_mode: event.target.value })} />
        </div>
        {mode !== "structured" ? (
          <Textarea aria-label="Boolean query" placeholder='"python" AND (django OR flask) NOT intern' value={booleanQuery} onChange={(event) => setBooleanQuery(event.target.value)} />
        ) : null}
        {mode === "hybrid" ? (
          <Textarea aria-label="Semantic text" placeholder="Words to match in the profile text" value={text} onChange={(event) => setText(event.target.value)} />
        ) : null}
        {error ? <ErrorState message={error} /> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={() => run(1)}>Run search</Button>
          <Input aria-label="Saved search name" placeholder="Name this search" value={name} onChange={(event) => setName(event.target.value)} className="max-w-xs" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={notify} onChange={(event) => setNotify(event.target.checked)} />
            Email me about new matches
          </label>
          <Button
            type="button"
            variant="outline"
            onClick={async () => {
              await api("/api/v1/search/saved/", {
                method: "POST",
                json: {
                  name,
                  mode: mode === "structured" ? "structured" : mode === "boolean" ? "boolean" : "hybrid",
                  boolean_query: booleanQuery,
                  semantic_query: text,
                  notify_on_new_match: notify,
                  filters: Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== "")),
                },
              });
              setName("");
              client.invalidateQueries({ queryKey: ["saved-searches"] });
            }}
          >
            Save search
          </Button>
        </div>
      </Card>
      <ResultList page={page} onPage={(next) => run(next)} />
      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <h2 className="text-2xl">Saved</h2>
          {saved.data?.length === 0 ? <p className="mt-2 text-sm text-muted">None yet.</p> : null}
          <ul className="mt-2 grid gap-2 text-sm">
            {saved.data?.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-2">
                <span>{row.name} {row.notify_on_new_match ? "· notifies" : ""}</span>
                <Button size="sm" variant="outline" onClick={async () => {
                  const data = await api<Page<CandidateCard>>(`/api/v1/search/saved/${row.id}/run/`, { method: "POST" });
                  setPage(data);
                }}>Run</Button>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <h2 className="text-2xl">Recent</h2>
          <ul className="mt-2 grid gap-1 text-sm text-muted">
            {history.data?.slice(0, 8).map((row) => <li key={row.id}>{row.mode}: {row.query_text || "filters"}</li>)}
          </ul>
        </Card>
      </div>
    </div>
  );
}

type Saved = {
  id: string;
  name: string;
  mode: string;
  notify_on_new_match: boolean;
};

const nlSchema = z.object({
  text: z.string().trim().min(3, "Describe who you are looking for.").max(MAX, `Keep this under ${MAX} characters.`),
});

export function NaturalSearchPage() {
  const form = useForm({ resolver: zodResolver(nlSchema), defaultValues: { text: "" } });
  const [plan, setPlan] = useState<{ boolean_query?: string; semantic_query?: string; filters?: { field: string; value: string }[]; provider_label?: string } | null>(null);
  const [booleanQuery, setBooleanQuery] = useState("");
  const [semantic, setSemantic] = useState("");
  const [error, setError] = useState("");
  const [page, setPage] = useState<Page<CandidateCard> | null>(null);
  const text = form.watch("text");

  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Describe a search</h1>
      <p className="text-sm text-muted">The desk turns this into an editable plan. It does not run model-written SQL.</p>
      <form
        className="grid gap-2"
        onSubmit={form.handleSubmit(async (values) => {
          setError("");
          try {
            const data = await api<{ plan: { boolean_query?: string; semantic_query?: string; filters?: { field: string; value: string }[] }; provider_label: string; executed: boolean }>("/api/v1/search/interpret/", {
              method: "POST",
              json: values,
            });
            setPlan({ ...data.plan, provider_label: data.provider_label });
            setBooleanQuery(data.plan.boolean_query || "");
            setSemantic(data.plan.semantic_query || values.text);
          } catch (err) {
            setError(errorText(err));
          }
        })}
      >
        <Textarea aria-label="Natural language search" {...form.register("text")} placeholder="Backend engineers in Bengaluru who know Django" />
        <p className="text-xs text-muted">{text.length}/{MAX}</p>
        {form.formState.errors.text ? <p className="text-sm text-danger">{form.formState.errors.text.message}</p> : null}
        {error ? <ErrorState message={error} /> : null}
        <Button type="submit">Interpret</Button>
      </form>
      {plan ? (
        <Card className="grid gap-3">
          <p className="text-sm text-muted">{plan.provider_label}. Edit the plan, then run it.</p>
          <Textarea aria-label="Editable boolean plan" value={booleanQuery} onChange={(event) => setBooleanQuery(event.target.value)} />
          <Textarea aria-label="Editable semantic plan" value={semantic} onChange={(event) => setSemantic(event.target.value)} />
          <ul className="text-sm">{(plan.filters || []).map((item) => <li key={`${item.field}-${item.value}`}>{item.field}: {item.value}</li>)}</ul>
          <Button type="button" onClick={async () => {
            setError("");
            try {
              const filters = Object.fromEntries((plan.filters || []).map((item) => [item.field, item.value]));
              const data = await api<Page<CandidateCard>>("/api/v1/search/hybrid/", {
                method: "POST",
                json: { boolean_query: booleanQuery, semantic_query: semantic, query: semantic, filters },
              });
              setPage(data);
            } catch (err) {
              setError(errorText(err));
            }
          }}>Run this plan</Button>
        </Card>
      ) : null}
      <ResultList page={page} />
    </div>
  );
}

export function ResultList({ page, onPage }: { page: (Page<CandidateCard> & { score_version?: string | null }) | null; onPage?: (page: number) => void }) {
  if (!page) return null;
  if (page.results.length === 0) return <Empty title="No matches" body="Try a broader phrase or drop a filter. Missing data is not treated as a failure." />;
  return (
    <div className="grid gap-2">
      {page.score_version ? <p className="text-xs text-muted">Ranking {page.score_version} is decision support, not a probability.</p> : null}
      {page.results.map((row) => (
        <Card key={row.id} className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <Link className="font-serif text-xl" to={`/candidates/${row.id}`}>{row.full_name || "Unnamed"}</Link>
            <p className="text-sm text-muted">{show(row.current_title)} · {show(row.location)} · {monthsLabel(row.total_experience_months)}</p>
          </div>
          {row.score !== undefined ? <span className="text-sm">Score {row.score}</span> : null}
        </Card>
      ))}
      {onPage ? (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={!page.previous} onClick={() => onPage(1)}>First</Button>
        </div>
      ) : null}
    </div>
  );
}
