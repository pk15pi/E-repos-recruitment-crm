import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ErrorState, Loading } from "../components/states";
import { Card } from "../components/ui";
import { api, getActiveOrg } from "../lib/api";
import { isAgency, isPlatform, useAuth } from "../lib/auth";
import { errorText, labelize } from "../lib/format";

type AgencyDash = {
  role_scope: "agency";
  candidates_on_file: number;
  awaiting_review: number;
  failed_jobs: number;
  open_vacancies: number;
  matches: number;
  interviews: number;
  pending_feedback: number;
  follow_ups: number;
  pipeline: { stage: string; count: number }[];
};

type ClientDash = {
  role_scope: "client";
  shared_candidates: number;
  open_vacancies: number;
  interviews: number;
  pending_feedback: number;
};

export function DashboardPage() {
  const { user } = useAuth();
  const needsOrganization = isPlatform(user) && !getActiveOrg();
  const query = useQuery({
    queryKey: ["dashboard"],
    enabled: !needsOrganization,
    queryFn: () => api<AgencyDash | ClientDash>("/api/v1/dashboard/"),
  });
  if (needsOrganization) {
    return (
      <Card>
        <h1 className="text-4xl">Today on the desk</h1>
        <p className="mt-2 text-sm text-muted">
          Choose an organization in the header to see its dashboard, or open one from Organizations.
        </p>
      </Card>
    );
  }
  if (query.isLoading) return <Loading label="Loading the desk" />;
  if (query.isError) return <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} />;
  if (!query.data) return <Loading label="Loading the desk" />;
  const data = query.data;
  const agency = isAgency(user) && data.role_scope === "agency";
  const cards = agency
    ? [
        ["People on file", data.candidates_on_file, "/candidates"],
        ["Awaiting review", data.awaiting_review, "/upload"],
        ["Failed processing", data.failed_jobs, "/processing"],
        ["Open vacancies", data.open_vacancies, "/jobs"],
        ["Stored matches", data.matches, "/jobs"],
        ["Upcoming interviews", data.interviews, "/interviews"],
        ["Feedback waiting", data.pending_feedback, "/interviews"],
        ["Follow-ups", data.follow_ups, "/tasks"],
      ]
    : [
        ["Shared with you", (data as ClientDash).shared_candidates, "/candidates"],
        ["Open vacancies", data.open_vacancies, "/jobs"],
        ["Interviews", data.interviews, "/interviews"],
        ["Feedback waiting", data.pending_feedback, "/interviews"],
      ];
  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-4xl">Today on the desk</h1>
        <p className="mt-1 text-sm text-muted">Counts come from this organization’s records. A human still decides who moves forward.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(([label, value, href]) => (
          <Link key={String(label)} to={String(href)}>
            <Card>
              <p className="text-sm text-muted">{label}</p>
              <p className="mt-2 font-serif text-3xl">{value as number}</p>
            </Card>
          </Link>
        ))}
      </div>
      {agency ? (
        <Card>
          <h2 className="text-2xl">Pipeline</h2>
          {data.pipeline.length === 0 ? (
            <p className="mt-2 text-sm text-muted">No submissions yet.</p>
          ) : (
            <ul className="mt-3 grid gap-2 sm:grid-cols-2">
              {data.pipeline.map((row) => (
                <li key={row.stage} className="flex justify-between text-sm">
                  <span className="capitalize">{labelize(row.stage)}</span>
                  <span>{row.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
    </div>
  );
}
