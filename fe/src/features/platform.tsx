import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { Badge, Button, Card, Input, Select } from "../components/ui";
import { api, setActiveOrg } from "../lib/api";
import { isPlatform, useAuth } from "../lib/auth";
import { errorText, labelize, when } from "../lib/format";

type Organization = {
  id: string;
  name: string;
  slug: string;
  contact_email: string;
  status: string;
  read_only: boolean;
  status_reason: string;
  status_changed_at: string | null;
  global_access: string[];
  counts?: { members: number; candidates: number; jobs: number; submissions: number };
};

type CatalogItem = {
  id: string;
  organization: { id: string; name: string };
  updated_at: string;
  label: string;
  detail: string;
};

type CatalogScope = {
  key: string;
  label: string;
  count: number;
  recent: CatalogItem[];
};

type CatalogOrganization = {
  id: string;
  name: string;
  status: string;
  read_only: boolean;
  granted_scopes: string[];
  active_resumes: number;
  clients: number;
  customers: number;
  open_jds: number;
};

type Catalog = {
  generated_at: string;
  totals: {
    organizations: number;
    granted_organizations: number;
    active_resumes: number;
    clients: number;
    customers: number;
    open_jds: number;
  };
  scopes: Record<string, CatalogScope>;
  organizations: CatalogOrganization[];
};

const SCOPES = [
  { value: "resumes", label: "Global resumes" },
  { value: "clients", label: "Global clients" },
  { value: "customers", label: "Global customers" },
  { value: "jds", label: "Global job descriptions" },
];

function statusTone(status: string) {
  if (status === "active") return "good" as const;
  if (status === "past_due") return "warn" as const;
  return "bad" as const;
}

export function OrganizationsPage() {
  const { user } = useAuth();
  const client = useQueryClient();
  const orgs = useQuery({
    queryKey: ["organizations"],
    queryFn: () => api<Organization[]>("/api/v1/admin/organizations/"),
  });
  const [form, setForm] = useState({
    name: "",
    contact_email: "",
    admin_full_name: "",
    admin_email: "",
    admin_password: "",
  });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  if (!isPlatform(user)) return <p className="text-sm text-muted">Platform owners only.</p>;

  async function createOrganization() {
    setError("");
    setMessage("");
    try {
      await api("/api/v1/admin/organizations/", { method: "POST", json: form });
      setForm({ name: "", contact_email: "", admin_full_name: "", admin_email: "", admin_password: "" });
      setMessage("Organization created. Its agency admin can now add the team.");
      client.invalidateQueries({ queryKey: ["organizations"] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Organizations</h1>
      <p className="text-sm text-muted">
        Register the organization and its first agency admin here. That admin adds the rest of the team, and every
        organization only ever sees its own records. Global data access is granted per organization.
      </p>
      <Card className="grid gap-2 md:grid-cols-2">
        <Input
          aria-label="Organization name"
          placeholder="Organization name"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
        <Input
          aria-label="Organization email"
          placeholder="Organization email"
          value={form.contact_email}
          onChange={(event) => setForm({ ...form, contact_email: event.target.value })}
        />
        <Input
          aria-label="First admin name"
          placeholder="First agency admin name"
          value={form.admin_full_name}
          onChange={(event) => setForm({ ...form, admin_full_name: event.target.value })}
        />
        <Input
          aria-label="First admin email"
          placeholder="First agency admin email"
          value={form.admin_email}
          onChange={(event) => setForm({ ...form, admin_email: event.target.value })}
        />
        <Input
          aria-label="First admin password"
          type="password"
          placeholder="Temporary password"
          value={form.admin_password}
          onChange={(event) => setForm({ ...form, admin_password: event.target.value })}
        />
        <Button onClick={createOrganization}>Create organization</Button>
        {message ? <p className="text-sm">{message}</p> : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
      </Card>
      {orgs.isLoading ? <p className="text-sm text-muted">Loading organizations…</p> : null}
      {orgs.isError ? <p className="text-sm text-danger">{errorText(orgs.error)}</p> : null}
      <div className="grid gap-3">
        {(orgs.data ?? []).map((org) => (
          <OrganizationCard key={org.id} org={org} />
        ))}
        {orgs.data?.length === 0 ? <p className="text-sm text-muted">No organizations yet.</p> : null}
      </div>
    </div>
  );
}

const SCOPE_LABELS: Record<string, string> = {
  resumes: "Global resumes",
  clients: "Global clients",
  customers: "Global customers",
  jds: "Global job descriptions",
};

export function CatalogPage() {
  const { user } = useAuth();
  const catalog = useQuery({
    queryKey: ["global-catalog"],
    queryFn: () => api<Catalog>("/api/v1/admin/global-catalog/"),
  });

  if (!isPlatform(user)) return <p className="text-sm text-muted">Platform owners only.</p>;

  const totals = catalog.data?.totals;

  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Global catalog</h1>
      <p className="text-sm text-muted">
        Every organization writes into one central store. This is the platform view of the active records that can be
        shared with organizations granted global access. Organizations still only see another desk's records read-only,
        and never see internal notes, plans, or team membership.
      </p>
      {catalog.isLoading ? <p className="text-sm text-muted">Loading the catalog…</p> : null}
      {catalog.isError ? <p className="text-sm text-danger">{errorText(catalog.error)}</p> : null}
      {totals ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <Total label="Organizations" value={totals.organizations} />
          <Total label="With global access" value={totals.granted_organizations} />
          <Total label="Active resumes" value={totals.active_resumes} />
          <Total label="Clients" value={totals.clients} />
          <Total label="Client contacts" value={totals.customers} />
          <Total label="Open job descriptions" value={totals.open_jds} />
        </div>
      ) : null}
      {catalog.data ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {Object.values(catalog.data.scopes).map((scope) => (
            <Card key={scope.key} className="grid gap-2">
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium">{scope.label}</p>
                <Badge>{scope.count}</Badge>
              </div>
              {scope.recent.length === 0 ? (
                <p className="text-sm text-muted">Nothing stored yet.</p>
              ) : (
                <ul className="grid gap-1 text-sm">
                  {scope.recent.map((item) => (
                    <li key={item.id} className="flex flex-wrap items-baseline justify-between gap-2">
                      <span>
                        {item.label}
                        <span className="text-muted"> · {item.organization.name}</span>
                        {item.detail ? <span className="text-muted"> · {item.detail}</span> : null}
                      </span>
                      <span className="text-xs text-muted">{when(item.updated_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ))}
        </div>
      ) : null}
      {catalog.data ? (
        <Card className="grid gap-2">
          <p className="font-medium">By organization</p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Organization</th>
                  <th className="py-1 pr-3 font-medium">Status</th>
                  <th className="py-1 pr-3 font-medium">Global access</th>
                  <th className="py-1 pr-3 font-medium">Resumes</th>
                  <th className="py-1 pr-3 font-medium">Clients</th>
                  <th className="py-1 pr-3 font-medium">Contacts</th>
                  <th className="py-1 font-medium">Open JDs</th>
                </tr>
              </thead>
              <tbody>
                {catalog.data.organizations.map((org) => (
                  <tr key={org.id} className="border-t border-line">
                    <td className="py-2 pr-3">{org.name}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={statusTone(org.status)}>{org.read_only ? "Read only" : labelize(org.status)}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      {org.granted_scopes.length === 0 ? (
                        <span className="text-muted">None</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {org.granted_scopes.map((scope) => (
                            <Badge key={scope} tone="good">
                              {SCOPE_LABELS[scope] ?? scope}
                            </Badge>
                          ))}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3">{org.active_resumes}</td>
                    <td className="py-2 pr-3">{org.clients}</td>
                    <td className="py-2 pr-3">{org.customers}</td>
                    <td className="py-2">{org.open_jds}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted">Snapshot generated {when(catalog.data.generated_at)}.</p>
        </Card>
      ) : null}
    </div>
  );
}

function Total({ label, value }: { label: string; value: number }) {
  return (
    <Card className="grid gap-1">
      <p className="text-sm text-muted">{label}</p>
      <p className="text-3xl font-serif">{value}</p>
    </Card>
  );
}

function OrganizationCard({ org }: { org: Organization }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState(org.name);
  const [contact, setContact] = useState(org.contact_email);
  const [status, setStatus] = useState(org.status);
  const [reason, setReason] = useState(org.status_reason);
  const [scopes, setScopes] = useState<string[]>(org.global_access);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function save(path: string, option: "PATCH" | "PUT", json: unknown, note: string) {
    setError("");
    setMessage("");
    try {
      await api(path, { method: option, json });
      setMessage(note);
      client.invalidateQueries({ queryKey: ["organizations"] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  function toggleScope(scope: string) {
    setScopes(scopes.includes(scope) ? scopes.filter((item) => item !== scope) : [...scopes, scope]);
  }

  return (
    <Card className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-lg font-medium">
            {org.name} <span className="text-sm text-muted">· {org.slug}</span>
          </p>
          <p className="text-sm text-muted">
            {org.contact_email || "No organization email"} · {org.counts?.members ?? 0} people ·{" "}
            {org.counts?.candidates ?? 0} candidates · {org.counts?.jobs ?? 0} JDs ·{" "}
            {org.counts?.submissions ?? 0} submissions
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={statusTone(org.status)}>{labelize(org.status)}</Badge>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setActiveOrg(org.id);
              client.clear();
              navigate("/");
            }}
          >
            Open desk
          </Button>
        </div>
      </div>
      <div className="grid gap-2 border-t border-line pt-3 md:grid-cols-3">
        <Input aria-label={`Name for ${org.name}`} value={name} onChange={(event) => setName(event.target.value)} />
        <Input
          aria-label={`Email for ${org.name}`}
          value={contact}
          onChange={(event) => setContact(event.target.value)}
        />
        <Button
          variant="outline"
          onClick={() =>
            save(
              `/api/v1/admin/organizations/${org.id}/`,
              "PATCH",
              { name, contact_email: contact },
              "Organization profile saved.",
            )
          }
        >
          Save profile
        </Button>
        <Select label="Status" value={status} onChange={setStatus}>
          <option value="active">Active</option>
          <option value="past_due">Payment past due</option>
          <option value="inactive">Inactive</option>
        </Select>
        <Input
          aria-label={`Status reason for ${org.name}`}
          placeholder="Reason shown to the organization"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <Button
          variant="outline"
          onClick={() =>
            save(
              `/api/v1/admin/organizations/${org.id}/`,
              "PATCH",
              { status, status_reason: reason },
              "Organization status saved.",
            )
          }
        >
          Save status
        </Button>
      </div>
      <div className="grid gap-2 border-t border-line pt-3 text-sm">
        <p className="font-medium">Global data access</p>
        <div className="flex flex-wrap gap-4">
          {SCOPES.map((scope) => (
            <label key={scope.value} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={scopes.includes(scope.value)}
                onChange={() => toggleScope(scope.value)}
              />
              {scope.label}
            </label>
          ))}
        </div>
        <div>
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              save(
                `/api/v1/admin/organizations/${org.id}/global-access/`,
                "PUT",
                { scopes },
                "Global access saved.",
              )
            }
          >
            Save global access
          </Button>
        </div>
      </div>
      {org.status_changed_at ? (
        <p className="text-xs text-muted">Status changed {when(org.status_changed_at)}.</p>
      ) : null}
      {message ? <p className="text-sm">{message}</p> : null}
      {error ? <p className="text-sm text-danger">{error}</p> : null}
    </Card>
  );
}
