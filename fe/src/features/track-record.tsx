import { useQuery } from "@tanstack/react-query";

import { Empty, ErrorState, Loading } from "../components/states";
import { Card } from "../components/ui";
import { api } from "../lib/api";
import { isAdmin, useAuth } from "../lib/auth";
import { errorText, labelize, when } from "../lib/format";
import type { TrackRecord } from "../lib/types";

type Response = { scope: "team" | "self"; results: TrackRecord[] };

function Metric({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="rounded-md bg-paper p-3">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className="font-serif text-2xl">{value ?? "—"}</p>
    </div>
  );
}

export function TrackRecordPage() {
  const { user } = useAuth();
  const admin = isAdmin(user);
  const query = useQuery({ queryKey: ["track-record"], queryFn: () => api<Response>("/api/v1/track-record/") });
  if (query.isLoading) return <Loading label="Reading the track record" />;
  if (query.isError) return <ErrorState message={errorText(query.error)} onRetry={() => query.refetch()} />;
  const data = query.data!;
  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-4xl">Track record</h1>
        <p className="text-sm text-muted">
          {admin
            ? "Effort and achievement for every recruiter on this desk. The activity log is the audit trail behind the numbers."
            : "Your effort, achievement, and recent activity on this desk."}
        </p>
      </div>
      {data.results.length === 0 ? <Empty title="No recruiters yet" body="An agency admin adds recruiters from People and roles." /> : null}
      {data.results.map((row) => (
        <Card key={row.user.id} className="grid gap-3">
          <div>
            <h2 className="text-2xl">{row.user.full_name}</h2>
            <p className="text-sm text-muted">{row.user.email}</p>
          </div>
          <div className="grid gap-2 md:grid-cols-4">
            <Metric label="Effort points" value={row.effort.effort_points} />
            <Metric label="JDs posted" value={row.effort.jobs_posted} />
            <Metric label="Resumes uploaded" value={row.effort.resumes_uploaded} />
            <Metric label="Submissions" value={row.effort.submissions} />
            <Metric label="Screening passed" value={row.achievement.screening_passed} />
            <Metric label="Interview levels passed" value={row.achievement.levels_passed} />
            <Metric label="Offers" value={row.achievement.offers} />
            <Metric label="Placements" value={row.achievement.placements} />
            <Metric label="Average rating" value={row.achievement.average_interview_rating} />
            <Metric label="Pass rate" value={row.achievement.pass_rate === null ? null : `${row.achievement.pass_rate}%`} />
            <Metric label="Interviews completed" value={row.effort.interviews_completed} />
            <Metric label="Active shares" value={row.effort.shares} />
          </div>
          <div>
            <h3 className="text-xl">Recent activity</h3>
            {row.activity.length === 0 ? <p className="text-sm text-muted">No activity recorded yet.</p> : (
              <ul className="mt-2 grid gap-1 text-sm">
                {row.activity.map((item, index) => (
                  <li key={`${item.action}-${item.object_id}-${index}`}>
                    <span className="text-muted">{when(item.created_at)}</span> · {labelize(item.action)}
                    {item.detail ? ` · ${item.detail}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      ))}
    </div>
  );
}
