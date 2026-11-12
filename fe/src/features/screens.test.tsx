import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ErrorState } from "../components/states";
import { AuthProvider } from "../lib/auth";
import { LoginPage } from "./auth-pages";
import { JdPage, MatchCard } from "./jobs";
import { ProfileForm } from "./profile-form";
import { UploadRow } from "./resumes";
import { NaturalSearchPage } from "./search";
import { ShortlistPage } from "./pipeline";
import { ComparePage } from "./candidates";
import type { MatchRow } from "../lib/types";

function desk(ui: React.ReactNode, userJson?: unknown, path = "/") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo) => {
      const url = String(input);
      if (url.includes("/auth/me/")) {
        return new Response(JSON.stringify(userJson ?? { error: { message: "Sign in." } }), { status: userJson ? 200 : 401 });
      }
      if (url.includes("/clients/")) return new Response("[]", { status: 200 });
      if (url.includes("/shortlists/")) return new Response("[]", { status: 200 });
      if (url.includes("/settings/")) return new Response(JSON.stringify({ ai_provider: "deterministic", ai_provider_label: "dev", name: "Northwind" }), { status: 200 });
      if (url.includes("/candidates/compare/")) {
        return new Response(
          JSON.stringify([
            { id: "a", full_name: "Asha Rao", current_title: "Engineer", current_employer: "Northwind", location: "Bengaluru", total_experience_months: 24, skills: [{ name: "Python" }], verification_status: "verified", contact_visible: true, emails: [{ email: "asha@example.com" }] },
            { id: "b", full_name: "Lata Menon", current_title: null, current_employer: null, location: null, total_experience_months: null, skills: [], verification_status: "unverified", contact_visible: false, emails: [] },
          ]),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ error: { code: "error", message: "Request failed.", details: {} } }), { status: 500 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const recruiter = {
  id: "u",
  email: "ravi@sable.test",
  full_name: "Ravi Iyer",
  is_platform_admin: false,
  membership: {
    role: "recruiter",
    organization: {
      id: "o",
      name: "Northwind Search",
      status: "active",
      read_only: false,
      status_reason: "",
    },
  },
  client_companies: [],
};

describe("login form", () => {
  it("asks for a real email before calling the API", async () => {
    desk(<LoginPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email.")).toBeInTheDocument();
  });
});

describe("upload status", () => {
  it("shows a rejection and a retry for a failed file", async () => {
    const retry = vi.fn();
    render(
      <MemoryRouter>
        <UploadRow row={{ filename: "scan.pdf", resume_id: "1", status: "failed", error: "Could not read this file.", progress: 100 }} onRetry={retry} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Could not read this file.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();
  });
});

describe("extraction review", () => {
  it("highlights a low-confidence field", () => {
    render(
      <ProfileForm
        value={{ full_name: "Asha" }}
        onChange={() => undefined}
        fields={[{ path: "full_name", label: "Full name", value: "Asha", status: "needs_review", confidence: 0.4, quote: "Asha Rao", page: 1, low_confidence: true }]}
      />,
    );
    expect(screen.getByText("needs review")).toBeInTheDocument();
    expect(screen.getByText("From the resume: “Asha Rao”")).toBeInTheDocument();
  });
});

describe("search and job description", () => {
  it("rejects an over-long natural language request", async () => {
    render(
      <MemoryRouter>
        <NaturalSearchPage />
      </MemoryRouter>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Natural language search"));
    await user.paste("x".repeat(4001));
    await user.click(screen.getByRole("button", { name: "Interpret" }));
    expect(await screen.findByText(/Keep this under 4000 characters/)).toBeInTheDocument();
  });

  it("rejects an over-long job description before sending it", async () => {
    desk(<JdPage />, recruiter);
    const user = userEvent.setup();
    await screen.findByLabelText("Job description");
    await user.click(screen.getByLabelText("Job description"));
    await user.paste("Role ".repeat(4100));
    await user.click(screen.getByRole("button", { name: "Analyze job description" }));
    expect(await screen.findByText(/20000 characters or fewer/)).toBeInTheDocument();
  });
});

describe("match results", () => {
  it("shows the score, mandatory counts, and actions", () => {
    const row: MatchRow = {
      id: "c1",
      match_id: "m1",
      full_name: "Asha Rao",
      current_title: "Backend Engineer",
      current_employer: "Northwind",
      location: "Bengaluru",
      total_experience_months: 60,
      work_mode: "hybrid",
      employment_type: "full_time",
      status: "active",
      verification_status: "verified",
      notice_period_days: 30,
      availability_date: null,
      expected_salary_amount: null,
      expected_salary_currency: null,
      compensation_visible: false,
      primary_email: null,
      skills: [{ name: "Python", source: "verified" }, { name: "Django", source: "extracted" }],
      tags: [],
      updated_at: "2026-10-17T00:00:00Z",
      assigned_recruiter: null,
      is_global: false,
      owner_organization: null,
      score: 82,
      score_version: "sable-score-v1",
      mandatory_met: 2,
      mandatory_unknown: 1,
      mandatory_unmet: 0,
      preferred_matched: 1,
      preferred_total: 2,
      explanation: "Python and Django are on the profile.",
      evidence: [{ kind: "skill", status: "met", detail: "Python", quote: "Python" }],
      employers: ["Northwind Payments"],
    };
    render(
      <MemoryRouter>
        <ul>
          <MatchCard row={row} jobId="job-1" />
        </ul>
      </MemoryRouter>,
    );
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText(/Must-have met 2/)).toBeInTheDocument();
    expect(screen.getByText(/Compensation:.*Not shared/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shortlist" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeInTheDocument();
  });
});

describe("comparison and shortlist", () => {
  it("shows missing data as not provided and hides contact", async () => {
    desk(<ComparePage />, recruiter, "/compare?ids=a,b");
    expect(await screen.findByText("Asha Rao")).toBeInTheDocument();
    expect(screen.getByText("Lata Menon")).toBeInTheDocument();
    expect(screen.getAllByText("Not provided").length).toBeGreaterThan(0);
    expect(screen.getByText("Not shared")).toBeInTheDocument();
  });

  it("requires a shortlist name", async () => {
    desk(<ShortlistPage />, recruiter);
    await screen.findByRole("button", { name: "Create shortlist" });
    await userEvent.click(screen.getByRole("button", { name: "Create shortlist" }));
    expect(await screen.findByText("Name the shortlist.")).toBeInTheDocument();
  });
});

describe("error state", () => {
  it("shows the message and retries", async () => {
    const retry = vi.fn();
    render(<ErrorState message="The desk could not load candidates." onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The desk could not load candidates.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });
});
