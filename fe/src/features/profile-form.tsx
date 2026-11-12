import { Badge, Input, Select, Textarea } from "../components/ui";
import type { EvidenceField, Profile } from "../lib/types";

function metaFor(fields: EvidenceField[] | undefined, path: string) {
  return fields?.find((field) => field.path === path);
}

function tone(status?: string, low?: boolean) {
  if (status === "conflicting") return "bad" as const;
  if (low || status === "needs_review") return "warn" as const;
  if (status === "verified") return "good" as const;
  if (status === "missing") return "neutral" as const;
  if (status) return "neutral" as const;
  return undefined;
}

export function FieldWrap({
  label,
  path,
  fields,
  children,
}: {
  label: string;
  path: string;
  fields?: EvidenceField[];
  children: React.ReactNode;
}) {
  const meta = metaFor(fields, path);
  const highlight = meta && (meta.low_confidence || meta.status === "needs_review" || meta.status === "conflicting");
  return (
    <div className={highlight ? "rounded-md bg-warn-soft p-2" : "grid gap-1"}>
      <label className="grid gap-1">
        <span className="flex items-center justify-between gap-2 text-sm font-medium">
          {label}
          {meta ? <Badge tone={tone(meta.status, meta.low_confidence)}>{meta.status.replaceAll("_", " ")}</Badge> : null}
        </span>
        {children}
      </label>
      {meta?.quote ? <p className="mt-1 text-xs text-muted">From the resume: “{meta.quote}”</p> : null}
      {meta?.page ? <p className="text-xs text-muted">Page {meta.page}</p> : null}
    </div>
  );
}

export function ProfileForm({
  value,
  onChange,
  fields,
}: {
  value: Profile;
  onChange: (next: Profile) => void;
  fields?: EvidenceField[];
}) {
  function set<K extends keyof Profile>(key: K, next: Profile[K]) {
    onChange({ ...value, [key]: next });
  }

  return (
    <div className="grid gap-4">
      <FieldWrap label="Full name" path="full_name" fields={fields}>
        <Input value={value.full_name || ""} onChange={(event) => set("full_name", event.target.value)} placeholder="Not provided" />
      </FieldWrap>
      <FieldWrap label="Summary" path="summary" fields={fields}>
        <Textarea value={value.summary || ""} onChange={(event) => set("summary", event.target.value)} placeholder="Not provided" />
      </FieldWrap>
      <div className="grid gap-3 md:grid-cols-2">
        <FieldWrap label="Current title" path="current_title" fields={fields}>
          <Input value={value.current_title || ""} onChange={(event) => set("current_title", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="Normalized title" path="normalized_title" fields={fields}>
          <Input value={value.normalized_title || ""} onChange={(event) => set("normalized_title", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="Current employer" path="current_employer" fields={fields}>
          <Input value={value.current_employer || ""} onChange={(event) => set("current_employer", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="Location" path="location" fields={fields}>
          <Input value={value.location || ""} onChange={(event) => set("location", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="LinkedIn" path="linkedin_url" fields={fields}>
          <Input value={value.linkedin_url || ""} onChange={(event) => set("linkedin_url", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="GitHub" path="github_url" fields={fields}>
          <Input value={value.github_url || ""} onChange={(event) => set("github_url", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="Portfolio" path="portfolio_url" fields={fields}>
          <Input value={value.portfolio_url || ""} onChange={(event) => set("portfolio_url", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="Industry" path="industry" fields={fields}>
          <Input value={value.industry || ""} onChange={(event) => set("industry", event.target.value)} />
        </FieldWrap>
        <FieldWrap label="Total experience (months)" path="total_experience_months" fields={fields}>
          <Input
            inputMode="numeric"
            value={value.total_experience_months ?? ""}
            onChange={(event) => set("total_experience_months", event.target.value === "" ? null : Number(event.target.value))}
          />
        </FieldWrap>
        <FieldWrap label="Relevant experience (months)" path="relevant_experience_months" fields={fields}>
          <Input
            inputMode="numeric"
            value={value.relevant_experience_months ?? ""}
            onChange={(event) => set("relevant_experience_months", event.target.value === "" ? null : Number(event.target.value))}
          />
        </FieldWrap>
        <Select label="Work mode" value={value.work_mode || ""} onChange={(next) => set("work_mode", next)}>
          <option value="">Not provided</option>
          <option value="remote">Remote</option>
          <option value="hybrid">Hybrid</option>
          <option value="onsite">On-site</option>
        </Select>
        <Select label="Employment type" value={value.employment_type || ""} onChange={(next) => set("employment_type", next)}>
          <option value="">Not provided</option>
          <option value="full_time">Full-time</option>
          <option value="part_time">Part-time</option>
          <option value="contract">Contract</option>
          <option value="internship">Internship</option>
          <option value="temporary">Temporary</option>
        </Select>
        <FieldWrap label="Notice (days)" path="notice_period_days" fields={fields}>
          <Input
            inputMode="numeric"
            value={value.notice_period_days ?? ""}
            onChange={(event) => set("notice_period_days", event.target.value === "" ? null : Number(event.target.value))}
          />
        </FieldWrap>
        <FieldWrap label="Available from" path="availability_date" fields={fields}>
          <Input type="date" value={value.availability_date || ""} onChange={(event) => set("availability_date", event.target.value || null)} />
        </FieldWrap>
        <Select
          label="Willing to relocate"
          value={value.willing_to_relocate === null || value.willing_to_relocate === undefined ? "" : value.willing_to_relocate ? "yes" : "no"}
          onChange={(next) => set("willing_to_relocate", next === "" ? null : next === "yes")}
        >
          <option value="">Not provided</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </Select>
        <FieldWrap label="Source" path="source" fields={fields}>
          <Input value={value.source || ""} onChange={(event) => set("source", event.target.value)} />
        </FieldWrap>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <FieldWrap label="Current salary" path="current_salary_amount" fields={fields}>
          <Input
            value={value.current_salary_amount ?? ""}
            onChange={(event) => set("current_salary_amount", event.target.value || null)}
          />
        </FieldWrap>
        <FieldWrap label="Currency" path="current_salary_currency" fields={fields}>
          <Input value={value.current_salary_currency || ""} onChange={(event) => set("current_salary_currency", event.target.value)} />
        </FieldWrap>
        <Select label="Period" value={value.current_salary_period || ""} onChange={(next) => set("current_salary_period", next)}>
          <option value="">Not provided</option>
          <option value="annual">Annual</option>
          <option value="monthly">Monthly</option>
          <option value="daily">Daily</option>
          <option value="hourly">Hourly</option>
        </Select>
        <FieldWrap label="Expected salary" path="expected_salary_amount" fields={fields}>
          <Input
            value={value.expected_salary_amount ?? ""}
            onChange={(event) => set("expected_salary_amount", event.target.value || null)}
          />
        </FieldWrap>
        <FieldWrap label="Expected currency" path="expected_salary_currency" fields={fields}>
          <Input value={value.expected_salary_currency || ""} onChange={(event) => set("expected_salary_currency", event.target.value)} />
        </FieldWrap>
        <Select label="Expected period" value={value.expected_salary_period || ""} onChange={(next) => set("expected_salary_period", next)}>
          <option value="">Not provided</option>
          <option value="annual">Annual</option>
          <option value="monthly">Monthly</option>
          <option value="daily">Daily</option>
          <option value="hourly">Hourly</option>
        </Select>
      </div>
      <ListEditor
        label="Emails"
        path="emails"
        fields={fields}
        rows={(value.emails || []).map((row) => row.email)}
        placeholder="name@example.com"
        onChange={(rows) => set("emails", rows.filter(Boolean).map((email, index) => ({ email, is_primary: index === 0 })))}
      />
      <ListEditor
        label="Phones"
        path="phones"
        fields={fields}
        rows={(value.phones || []).map((row) => row.raw)}
        placeholder="+91 …"
        onChange={(rows) => set("phones", rows.filter(Boolean).map((raw, index) => ({ raw, is_primary: index === 0 })))}
      />
      <ListEditor
        label="Skills"
        path="skills"
        fields={fields}
        rows={(value.skills || []).map((row) => row.name)}
        placeholder="Skill"
        onChange={(rows) => set("skills", rows.filter(Boolean).map((name) => ({ name })))}
      />
      <ListEditor
        label="Preferred locations"
        path="preferred_locations"
        fields={fields}
        rows={value.preferred_locations || []}
        placeholder="City"
        onChange={(rows) => set("preferred_locations", rows.filter(Boolean))}
      />
      <ListEditor
        label="Tags and talent pools"
        path="tags"
        fields={fields}
        rows={value.tags || []}
        placeholder="Tag"
        onChange={(rows) => set("tags", rows.filter(Boolean))}
      />
      <ExperienceEditor value={value} onChange={onChange} fields={fields} />
      <EducationEditor value={value} onChange={onChange} fields={fields} />
      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <h3 className="text-lg">Certifications</h3>
          <button type="button" className="text-sm text-accent" onClick={() => set("certifications", [...(value.certifications || []), { name: "", issuer: "", issued_on: null, expires_on: null }])}>
            Add certification
          </button>
        </div>
        {(value.certifications || []).map((row, index) => (
          <div key={index} className="grid gap-2 md:grid-cols-2">
            <Input
              aria-label={`Certification ${index + 1}`}
              value={row.name}
              onChange={(event) => {
                const next = [...(value.certifications || [])];
                next[index] = { ...row, name: event.target.value };
                set("certifications", next);
              }}
            />
            <Input
              aria-label={`Issuer ${index + 1}`}
              value={row.issuer || ""}
              placeholder="Issuer"
              onChange={(event) => {
                const next = [...(value.certifications || [])];
                next[index] = { ...row, issuer: event.target.value };
                set("certifications", next);
              }}
            />
          </div>
        ))}
      </div>
      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <h3 className="text-lg">Projects</h3>
          <button type="button" className="text-sm text-accent" onClick={() => set("projects", [...(value.projects || []), { name: "", description: "", url: "", technologies: "" }])}>
            Add project
          </button>
        </div>
        {(value.projects || []).map((row, index) => (
          <div key={index} className="grid gap-2">
            <Input
              aria-label={`Project ${index + 1}`}
              value={row.name}
              onChange={(event) => {
                const next = [...(value.projects || [])];
                next[index] = { ...row, name: event.target.value };
                set("projects", next);
              }}
            />
            <Textarea
              aria-label={`Project description ${index + 1}`}
              value={row.description || ""}
              onChange={(event) => {
                const next = [...(value.projects || [])];
                next[index] = { ...row, description: event.target.value };
                set("projects", next);
              }}
            />
          </div>
        ))}
      </div>
      <ListEditor
        label="Languages"
        path="languages"
        fields={fields}
        rows={(value.languages || []).map((row) => row.language)}
        placeholder="Language"
        onChange={(rows) => set("languages", rows.filter(Boolean).map((language) => ({ language })))}
      />
    </div>
  );
}

function ListEditor({
  label,
  path,
  fields,
  rows,
  onChange,
  placeholder,
}: {
  label: string;
  path: string;
  fields?: EvidenceField[];
  rows: string[];
  onChange: (rows: string[]) => void;
  placeholder: string;
}) {
  const items = rows.length ? rows : [""];
  return (
    <FieldWrap label={label} path={path} fields={fields}>
      <div className="grid gap-2">
        {items.map((row, index) => (
          <Input
            key={index}
            aria-label={`${label} ${index + 1}`}
            placeholder={placeholder}
            value={row}
            onChange={(event) => {
              const next = [...items];
              next[index] = event.target.value;
              onChange(next);
            }}
          />
        ))}
        <button type="button" className="justify-self-start text-sm text-accent" onClick={() => onChange([...items, ""])}>
          Add {label.toLowerCase().replace(/s$/, "")}
        </button>
      </div>
    </FieldWrap>
  );
}

function ExperienceEditor({ value, onChange, fields }: { value: Profile; onChange: (next: Profile) => void; fields?: EvidenceField[] }) {
  const rows = value.experiences || [];
  return (
    <FieldWrap label="Employment history" path="experiences" fields={fields}>
      <div className="grid gap-3">
        {rows.map((row, index) => (
          <div key={index} className="grid gap-2 rounded-md border border-line p-2 md:grid-cols-2">
            <Input
              aria-label={`Employer ${index + 1}`}
              placeholder="Employer"
              value={row.employer || ""}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...row, employer: event.target.value };
                onChange({ ...value, experiences: next });
              }}
            />
            <Input
              aria-label={`Title ${index + 1}`}
              placeholder="Title"
              value={row.title || ""}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...row, title: event.target.value };
                onChange({ ...value, experiences: next });
              }}
            />
            <Input
              aria-label={`Start ${index + 1}`}
              type="date"
              value={(row.start_date || "").slice(0, 10)}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...row, start_date: event.target.value || null };
                onChange({ ...value, experiences: next });
              }}
            />
            <Input
              aria-label={`End ${index + 1}`}
              type="date"
              value={(row.end_date || "").slice(0, 10)}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...row, end_date: event.target.value || null };
                onChange({ ...value, experiences: next });
              }}
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={!!row.is_current}
                onChange={(event) => {
                  const next = [...rows];
                  next[index] = { ...row, is_current: event.target.checked };
                  onChange({ ...value, experiences: next });
                }}
              />
              Current role
            </label>
          </div>
        ))}
        <button
          type="button"
          className="justify-self-start text-sm text-accent"
          onClick={() => onChange({ ...value, experiences: [...rows, { employer: "", title: "", start_date: null, end_date: null, is_current: false }] })}
        >
          Add role
        </button>
      </div>
    </FieldWrap>
  );
}

function EducationEditor({ value, onChange, fields }: { value: Profile; onChange: (next: Profile) => void; fields?: EvidenceField[] }) {
  const rows = value.education || [];
  return (
    <FieldWrap label="Education" path="education" fields={fields}>
      <div className="grid gap-3">
        {rows.map((row, index) => (
          <div key={index} className="grid gap-2 md:grid-cols-3">
            <Input
              aria-label={`Institution ${index + 1}`}
              placeholder="Institution"
              value={row.institution || ""}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...row, institution: event.target.value };
                onChange({ ...value, education: next });
              }}
            />
            <Input
              aria-label={`Degree ${index + 1}`}
              placeholder="Degree"
              value={row.degree || ""}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...row, degree: event.target.value };
                onChange({ ...value, education: next });
              }}
            />
            <Input
              aria-label={`Field ${index + 1}`}
              placeholder="Field"
              value={row.field_of_study || ""}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...row, field_of_study: event.target.value };
                onChange({ ...value, education: next });
              }}
            />
          </div>
        ))}
        <button
          type="button"
          className="justify-self-start text-sm text-accent"
          onClick={() => onChange({ ...value, education: [...rows, { institution: "", degree: "", field_of_study: "", start_date: null, end_date: null }] })}
        >
          Add education
        </button>
      </div>
    </FieldWrap>
  );
}

export function detailToProfile(detail: {
  full_name: string | null;
  summary: string | null;
  current_title: string | null;
  normalized_title: string | null;
  current_employer: string | null;
  location: string | null;
  linkedin_url: string | null;
  github_url: string | null;
  portfolio_url: string | null;
  industry: string | null;
  total_experience_months: number | null;
  relevant_experience_months: number | null;
  notice_period_days: number | null;
  availability_date: string | null;
  work_mode: string | null;
  employment_type: string | null;
  willing_to_relocate: boolean | null;
  current_salary_amount: string | number | null;
  current_salary_currency: string | null;
  current_salary_period: string | null;
  expected_salary_amount: string | number | null;
  expected_salary_currency: string | null;
  expected_salary_period: string | null;
  source: string | null;
  status: string;
  emails: { email: string; is_primary?: boolean }[];
  phones: { raw: string; is_primary?: boolean }[];
  skills: { name: string }[];
  experiences: Profile["experiences"];
  education: Profile["education"];
  certifications: Profile["certifications"];
  projects: Profile["projects"];
  languages: { language: string; proficiency: string | null }[];
  preferred_locations: string[];
  tags: string[];
}): Profile {
  return {
    full_name: detail.full_name || "",
    summary: detail.summary || "",
    current_title: detail.current_title || "",
    normalized_title: detail.normalized_title || "",
    current_employer: detail.current_employer || "",
    location: detail.location || "",
    linkedin_url: detail.linkedin_url || "",
    github_url: detail.github_url || "",
    portfolio_url: detail.portfolio_url || "",
    industry: detail.industry || "",
    total_experience_months: detail.total_experience_months,
    relevant_experience_months: detail.relevant_experience_months,
    notice_period_days: detail.notice_period_days,
    availability_date: detail.availability_date,
    work_mode: detail.work_mode || "",
    employment_type: detail.employment_type || "",
    willing_to_relocate: detail.willing_to_relocate,
    current_salary_amount: detail.current_salary_amount,
    current_salary_currency: detail.current_salary_currency || "",
    current_salary_period: detail.current_salary_period || "",
    expected_salary_amount: detail.expected_salary_amount,
    expected_salary_currency: detail.expected_salary_currency || "",
    expected_salary_period: detail.expected_salary_period || "",
    source: detail.source || "",
    status: detail.status,
    emails: detail.emails,
    phones: detail.phones,
    skills: detail.skills.map((skill) => ({ name: skill.name })),
    experiences: detail.experiences,
    education: detail.education,
    certifications: detail.certifications,
    projects: detail.projects,
    languages: detail.languages,
    preferred_locations: detail.preferred_locations,
    tags: detail.tags,
  };
}
