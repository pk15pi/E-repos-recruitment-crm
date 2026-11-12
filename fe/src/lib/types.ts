export type OwnerOrganization = { id: string; name: string };

export type OrganizationSummary = {
  id: string;
  name: string;
  status: "active" | "past_due" | "inactive";
  read_only: boolean;
  status_reason: string;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  is_platform_admin: boolean;
  membership: null | { role: string; organization: OrganizationSummary };
  client_companies: { id: string; name: string; role: string }[];
};

export type CandidateCard = {
  id: string;
  full_name: string | null;
  current_title: string | null;
  current_employer: string | null;
  location: string | null;
  total_experience_months: number | null;
  work_mode: string | null;
  employment_type: string | null;
  status: string;
  verification_status: string;
  notice_period_days: number | null;
  availability_date: string | null;
  expected_salary_amount: string | number | null;
  expected_salary_currency: string | null;
  compensation_visible: boolean;
  primary_email: string | null;
  skills: { name: string; source?: string; confidence?: number | null }[];
  tags: string[];
  updated_at: string;
  assigned_recruiter: { id: string; full_name: string } | null;
  is_global: boolean;
  owner_organization: OwnerOrganization | null;
  score?: number;
  score_version?: string;
};

export type CandidateDetail = CandidateCard & {
  summary: string | null;
  normalized_title: string | null;
  linkedin_url: string | null;
  github_url: string | null;
  portfolio_url: string | null;
  industry: string | null;
  relevant_experience_months: number | null;
  willing_to_relocate: boolean | null;
  source: string | null;
  emails: { email: string; label?: string; is_primary?: boolean }[];
  phones: { raw: string; label?: string; is_primary?: boolean }[];
  contact_visible: boolean;
  preferred_locations: string[];
  current_salary_amount: string | number | null;
  current_salary_currency: string | null;
  current_salary_period: string | null;
  expected_salary_period: string | null;
  experiences: Experience[];
  education: Education[];
  certifications: Certification[];
  projects: Project[];
  languages: { id?: string; language: string; proficiency: string | null }[];
  notes: Note[];
  consents: { id: string; purpose: string; lawful_basis: string; granted: boolean; created_at: string }[];
  deletion_requested_at: string | null;
};

export type Experience = {
  id?: string;
  employer: string | null;
  title: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current?: boolean;
  location?: string | null;
  description?: string | null;
};

export type Education = {
  id?: string;
  institution: string | null;
  degree: string | null;
  field_of_study: string | null;
  start_date: string | null;
  end_date: string | null;
};

export type Certification = {
  id?: string;
  name: string;
  issuer: string | null;
  issued_on: string | null;
  expires_on: string | null;
};

export type Project = {
  id?: string;
  name: string;
  description: string | null;
  url: string | null;
  technologies: string | null;
};

export type Note = {
  id: string;
  body: string;
  visibility: string;
  author: string | null;
  created_at: string;
};

export type Profile = {
  full_name?: string;
  summary?: string;
  current_title?: string;
  normalized_title?: string;
  current_employer?: string;
  location?: string;
  linkedin_url?: string;
  github_url?: string;
  portfolio_url?: string;
  industry?: string;
  total_experience_months?: number | null;
  relevant_experience_months?: number | null;
  notice_period_days?: number | null;
  availability_date?: string | null;
  work_mode?: string;
  employment_type?: string;
  willing_to_relocate?: boolean | null;
  current_salary_amount?: string | number | null;
  current_salary_currency?: string;
  current_salary_period?: string;
  expected_salary_amount?: string | number | null;
  expected_salary_currency?: string;
  expected_salary_period?: string;
  source?: string;
  status?: string;
  emails?: { email: string; label?: string; is_primary?: boolean }[];
  phones?: { raw: string; label?: string; is_primary?: boolean }[];
  skills?: { name: string; confidence?: number | null }[];
  experiences?: Experience[];
  education?: Education[];
  certifications?: Certification[];
  projects?: Project[];
  languages?: { language: string; proficiency?: string | null }[];
  preferred_locations?: string[];
  tags?: string[];
};

export type EvidenceField = {
  path: string;
  label: string;
  value: string;
  status: string;
  confidence: number | null;
  quote: string;
  page: number | null;
  low_confidence: boolean;
};

export type Draft = {
  resume: {
    id: string;
    filename: string;
    detected_type: string;
    status: string;
    scan_status: string;
    error_message: string;
    page_count: number | null;
    candidate_id: string | null;
  };
  ready: boolean;
  provider: string;
  provider_label: string;
  model: string;
  prompt_version: string;
  schema_version: string;
  warnings: string[];
  duplicates: DuplicateHit[];
  profile: Profile | null;
  fields: EvidenceField[];
};

export type DuplicateHit = {
  kind: string;
  candidate_id: string;
  name: string;
  detail: string;
  blocking: boolean;
};

export type JobRecord = {
  id: string;
  title: string | null;
  original_description: string;
  location: string | null;
  work_mode: string | null;
  employment_type: string | null;
  seniority: string | null;
  domain: string | null;
  min_experience_months: number | null;
  max_experience_months: number | null;
  salary_min: string | number | null;
  salary_max: string | number | null;
  salary_currency: string | null;
  salary_period: string | null;
  notice_period_days: number | null;
  interview_levels: number;
  interview_question_count: number;
  status: string;
  analysis_status: string;
  analysis_error: string;
  client_company: { id: string; name: string; plan?: string; distribution_enabled?: boolean } | null;
  created_by: { id: string; full_name: string; email: string } | null;
  assigned_recruiter: { id: string; full_name: string; email: string } | null;
  provider: string;
  model: string;
  prompt_version: string;
  schema_version: string;
  score_version: string;
  updated_at: string;
  is_global?: boolean;
  owner_organization: OwnerOrganization | null;
  requirements?: Requirement[];
  processing?: { id: string; status: string; last_error: string };
};

export type Requirement = {
  id?: string;
  kind: string;
  label: string;
  value: string;
  priority: string;
  source?: string;
};

export type MatchRow = CandidateCard & {
  match_id: string;
  score: number;
  score_version: string;
  mandatory_met: number;
  mandatory_unknown: number;
  mandatory_unmet: number;
  preferred_matched: number;
  preferred_total: number;
  explanation: string;
  evidence: { kind: string; status: string; detail: string; quote: string }[];
  employers: string[];
};

export type Company = {
  id: string;
  name: string;
  industry: string | null;
  website: string | null;
  notes: string | null;
  plan: string | null;
  plan_reference: string | null;
  free_access_reason: string | null;
  free_access_granted_at: string | null;
  distribution_enabled: boolean;
  is_global: boolean;
  owner_organization: OwnerOrganization | null;
  contacts?: Contact[];
  members?: { user_id: string; email: string; role: string }[];
};

export type Contact = {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  title: string | null;
  is_primary: boolean;
};

export type InterviewProgress = {
  level: string;
  status: string;
  outcome: string;
  interview_id: string | null;
};

export type Submission = {
  id: string;
  stage: string;
  candidate_id: string;
  candidate_name: string | null;
  job_id: string;
  job_title: string | null;
  interview_levels: number;
  interview_question_count: number;
  interview_progress: InterviewProgress[];
  screening_passed: boolean;
  client_company_id: string;
  client_name: string;
  client_plan: string;
  offer_amount: string | number | null;
  offer_currency: string | null;
  joining_date: string | null;
  placement_notes: string | null;
  updated_at: string;
};

export type Shortlist = {
  id: string;
  name: string;
  job_id: string | null;
  client_company_id: string | null;
  items: { candidate_id: string; name: string | null; note: string }[];
};

export type InterviewQuestion = {
  id: string;
  prompt: string;
  focus: string | null;
  source: string;
  answer: string | null;
  answered_at: string | null;
};

export type InterviewReport = {
  status: string | null;
  summary: string | null;
  recommendation: string | null;
  score: number | null;
  generated_at: string | null;
};

export type Interview = {
  id: string;
  submission_id: string;
  candidate_id: string;
  candidate_name: string | null;
  job_title: string | null;
  job_interview_levels: number;
  level: string;
  kind: string;
  question_source: string | null;
  question_count: number;
  outcome: string;
  scheduled_at: string | null;
  duration_minutes: number | null;
  mode: string | null;
  status: string;
  interviewer_name: string | null;
  feedback: string | null;
  rating: number | null;
  meeting_provider: string | null;
  meeting_url: string | null;
  invited_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  join_url: string | null;
  ai_report: InterviewReport | null;
  questions: InterviewQuestion[];
  invitation?: { sent: boolean; error: string };
  warning?: string;
};

export type InterviewRoom = {
  candidate_name: string;
  job_title: string;
  scheduled_at: string | null;
  duration_minutes: number | null;
  meeting_url: string | null;
  status: string;
  submitted: boolean;
  questions: { id: string; prompt: string; focus: string | null }[];
};

export type TrackRecord = {
  user: { id: string; full_name: string; email: string };
  effort: {
    jobs_posted: number;
    jobs_assigned: number;
    resumes_uploaded: number;
    candidates_created: number;
    submissions: number;
    shares: number;
    interviews_scheduled: number;
    interviews_completed: number;
    effort_points: number;
  };
  achievement: {
    screening_passed: number;
    levels_passed: number;
    offers: number;
    placements: number;
    average_interview_rating: number | null;
    pass_rate: number | null;
    feedback_count: number;
  };
  activity: {
    action: string;
    object_type: string;
    object_id: string;
    detail: string;
    created_at: string;
  }[];
};

export type Task = {
  id: string;
  title: string;
  notes: string;
  status: string;
  due_at: string | null;
  candidate_id: string | null;
  candidate_name: string | null;
  assigned_to: string | null;
  created_at: string;
};

export const REQUIREMENT_KINDS = [
  "title",
  "seniority",
  "skill",
  "tool",
  "responsibility",
  "education",
  "certification",
  "domain",
  "location",
  "work_mode",
  "employment_type",
  "experience",
  "salary",
  "notice",
  "other",
] as const;

export const PRIORITIES = [
  { value: "must_have", label: "Must have" },
  { value: "preferred", label: "Preferred" },
  { value: "informational", label: "Informational" },
] as const;
