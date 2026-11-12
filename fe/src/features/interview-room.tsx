import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { ErrorState, Loading } from "../components/states";
import { Button, Card, Textarea } from "../components/ui";
import { api } from "../lib/api";
import { errorText, when } from "../lib/format";
import type { InterviewRoom as Room } from "../lib/types";

export function InterviewRoomPage() {
  const { token = "" } = useParams();
  const query = useQuery({
    queryKey: ["interview-room", token],
    queryFn: () => api<Room>(`/api/v1/interviews/join/${token}/`),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  if (query.isLoading) {
    return <main className="mx-auto grid max-w-3xl gap-4 p-6"><Loading label="Opening your interview" /></main>;
  }
  if (query.isError) {
    return (
      <main className="mx-auto grid max-w-3xl gap-4 p-6">
        <h1 className="text-3xl">Interview link</h1>
        <ErrorState message={errorText(query.error)} />
        <p className="text-sm text-muted">Ask the recruiter who invited you for a fresh link.</p>
      </main>
    );
  }
  const room = query.data!;
  const done = submitted || room.submitted;
  const complete = room.questions.length > 0 && room.questions.every((question) => (answers[question.id] || "").trim());
  return (
    <main className="mx-auto grid max-w-3xl gap-4 p-6">
      <header className="grid gap-1">
        <p className="text-sm uppercase tracking-wide text-muted">AI interview</p>
        <h1 className="text-3xl">{room.job_title}</h1>
        <p className="text-sm text-muted">
          {room.scheduled_at ? `${when(room.scheduled_at)} · ` : ""}
          {room.duration_minutes ? `${room.duration_minutes} minutes · ` : ""}
          {room.questions.length} question(s)
        </p>
        {room.meeting_url ? (
          <p className="text-sm"><a className="underline" href={room.meeting_url} target="_blank" rel="noreferrer">Open the video room</a></p>
        ) : null}
      </header>
      {done ? (
        <Card className="grid gap-2">
          <h2 className="text-2xl">Answers received</h2>
          <p className="text-sm text-muted">
            Thank you, {room.candidate_name}. Your answers are with the recruiter, who will follow up with the next step.
          </p>
        </Card>
      ) : (
        <form className="grid gap-4" onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          setSubmitting(true);
          try {
            await api(`/api/v1/interviews/join/${token}/`, {
              method: "POST",
              json: {
                answers: room.questions.map((question) => ({ question_id: question.id, answer: answers[question.id] || "" })),
              },
            });
            setSubmitted(true);
          } catch (err) {
            setError(errorText(err));
          } finally {
            setSubmitting(false);
          }
        }}>
          <p className="text-sm text-muted">
            Answer each question in your own words. Your answers go to the recruiter with an AI-written summary; a person
            still makes the hiring decision.
          </p>
          {room.questions.map((question, index) => (
            <Card key={question.id} className="grid gap-2">
              <label className="text-sm font-medium" htmlFor={`question-${question.id}`}>
                {index + 1}. {question.prompt}
              </label>
              <Textarea
                id={`question-${question.id}`}
                aria-label={`Answer ${index + 1}`}
                value={answers[question.id] || ""}
                onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })}
                placeholder="Your answer"
                className="min-h-28"
              />
            </Card>
          ))}
          {error ? <ErrorState message={error} /> : null}
          <Button type="submit" disabled={!complete || submitting}>
            {submitting ? "Submitting…" : "Submit answers"}
          </Button>
          {!complete ? <p className="text-sm text-muted">Answer every question to submit.</p> : null}
        </form>
      )}
    </main>
  );
}
