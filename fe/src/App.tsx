import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { Shell } from "./components/shell";
import { AuthProvider } from "./lib/auth";
import { LoginPage, RecoverPage, ResetPage } from "./features/auth-pages";
import { DashboardPage } from "./features/dashboard";
import { CandidateDetailPage, CandidateEditPage, CandidateListPage, ComparePage } from "./features/candidates";
import { ReviewPage, UploadPage } from "./features/resumes";
import { NaturalSearchPage, SearchPage } from "./features/search";
import { JdPage, JobDetailPage, MatchPage, RequisitionListPage } from "./features/jobs";
import { ClientDetailPage, ClientListPage, InterviewPage, ShortlistPage, SubmissionPage, TaskPage } from "./features/pipeline";
import { InterviewRoomPage } from "./features/interview-room";
import { ProcessingPage, ReportsPage, SettingsPage, UsersPage } from "./features/admin";
import { BillingPage } from "./features/billing";
import { CatalogPage, OrganizationsPage } from "./features/platform";
import { TrackRecordPage } from "./features/track-record";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/recover" element={<RecoverPage />} />
            <Route path="/reset-password" element={<ResetPage />} />
            <Route path="/interview/:token" element={<InterviewRoomPage />} />
            <Route element={<Shell />}>
              <Route index element={<DashboardPage />} />
              <Route path="candidates" element={<CandidateListPage />} />
              <Route path="candidates/new" element={<CandidateEditPage />} />
              <Route path="candidates/:id" element={<CandidateDetailPage />} />
              <Route path="candidates/:id/edit" element={<CandidateEditPage />} />
              <Route path="compare" element={<ComparePage />} />
              <Route path="upload" element={<UploadPage />} />
              <Route path="resumes/:id/review" element={<ReviewPage />} />
              <Route path="search" element={<SearchPage />} />
              <Route path="search/natural" element={<NaturalSearchPage />} />
              <Route path="jobs/from-description" element={<JdPage />} />
              <Route path="jobs" element={<RequisitionListPage />} />
              <Route path="jobs/:id" element={<JobDetailPage />} />
              <Route path="jobs/:id/matches" element={<MatchPage />} />
              <Route path="shortlists" element={<ShortlistPage />} />
              <Route path="clients" element={<ClientListPage />} />
              <Route path="clients/:id" element={<ClientDetailPage />} />
              <Route path="submissions" element={<SubmissionPage />} />
              <Route path="interviews" element={<InterviewPage />} />
              <Route path="tasks" element={<TaskPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="track-record" element={<TrackRecordPage />} />
              <Route path="processing" element={<ProcessingPage />} />
              <Route path="admin/users" element={<UsersPage />} />
              <Route path="admin/catalog" element={<CatalogPage />} />
              <Route path="admin/organizations" element={<OrganizationsPage />} />
              <Route path="admin/billing" element={<BillingPage />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
