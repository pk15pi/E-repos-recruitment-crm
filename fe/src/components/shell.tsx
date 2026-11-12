import * as Dialog from "@radix-ui/react-dialog";
import { Menu, X } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useState } from "react";

import { api, setActiveOrg, useActiveOrg } from "../lib/api";
import { isAdmin, isAgency, isPlatform, useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { Button } from "./ui";

type Item = { to: string; label: string; agency?: boolean; admin?: boolean; platform?: boolean };

const ITEMS: Item[] = [
  { to: "/", label: "Desk" },
  { to: "/candidates", label: "Candidates" },
  { to: "/upload", label: "Upload resumes", agency: true },
  { to: "/search", label: "Search", agency: true },
  { to: "/search/natural", label: "Describe a search", agency: true },
  { to: "/jobs/from-description", label: "From a job description", agency: true },
  { to: "/jobs", label: "Requisitions" },
  { to: "/shortlists", label: "Shortlists" },
  { to: "/clients", label: "Clients", agency: true },
  { to: "/submissions", label: "Submissions" },
  { to: "/interviews", label: "Interviews" },
  { to: "/tasks", label: "Follow-ups", agency: true },
  { to: "/reports", label: "Reports" },
  { to: "/track-record", label: "Track record", agency: true },
  { to: "/processing", label: "Processing queue", agency: true },
  { to: "/admin/users", label: "People and roles", admin: true },
  { to: "/admin/catalog", label: "Global catalog", platform: true },
  { to: "/admin/organizations", label: "Organizations", platform: true },
  { to: "/admin/billing", label: "Plans and billing", platform: true },
  { to: "/settings", label: "Privacy and retention" },
];

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth();
  const agency = isAgency(user);
  const admin = isAdmin(user);
  const platform = isPlatform(user);
  return (
    <nav className="grid gap-1" aria-label="Primary">
      {ITEMS.filter((item) =>
        item.platform ? platform : item.admin ? admin : item.agency ? agency : true,
      ).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "rounded-md px-3 py-2 text-sm",
              isActive ? "bg-white/10 text-white" : "text-[#e7e1d6] hover:bg-white/5",
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function Shell() {
  const { user, loading, logout } = useAuth();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const platform = isPlatform(user);
  const activeOrg = useActiveOrg();
  const organizations = useQuery({
    queryKey: ["organizations", activeOrg],
    enabled: platform,
    queryFn: () =>
      api<{ id: string; name: string; status: string; read_only: boolean }[]>("/api/v1/admin/organizations/"),
  });
  const selectedOrg = organizations.data?.find((org) => org.id === activeOrg);
  const settings = useQuery({
    queryKey: ["settings", activeOrg],
    enabled: !!user && (!platform || !!activeOrg),
    queryFn: () =>
      api<{ ai_provider: string; ai_provider_label: string; name: string }>("/api/v1/settings/organization/"),
  });

  function switchOrganization(id: string) {
    setActiveOrg(id);
    client.clear();
  }

  if (loading) return <p className="p-8 text-sm text-muted">Opening the desk…</p>;
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className="hidden bg-sidebar text-[#f4f0e6] md:flex md:flex-col md:gap-6 md:p-4">
        <div>
          <p className="font-serif text-2xl">Sable</p>
          <p className="text-xs text-[#c9c1b4]">
            {platform ? selectedOrg?.name ?? "Platform" : user.membership?.organization.name || "Platform"}
          </p>
        </div>
        <NavItems />
      </aside>
      <div className="min-w-0">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <Dialog.Root open={open} onOpenChange={setOpen}>
              <Dialog.Trigger asChild>
                <Button variant="outline" size="sm" className="md:hidden" aria-label="Open menu">
                  <Menu className="h-4 w-4" />
                </Button>
              </Dialog.Trigger>
              <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
                <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-72 bg-sidebar p-4 text-[#f4f0e6]">
                  <div className="mb-4 flex items-center justify-between">
                    <Dialog.Title className="text-2xl text-white">Sable</Dialog.Title>
                    <Dialog.Close className="rounded-md p-1" aria-label="Close menu">
                      <X className="h-4 w-4" />
                    </Dialog.Close>
                  </div>
                  <NavItems onNavigate={() => setOpen(false)} />
                </Dialog.Content>
              </Dialog.Portal>
            </Dialog.Root>
            <p className="text-sm text-muted md:hidden">Sable</p>
            {platform ? (
              <label className="flex items-center gap-2 text-sm">
                <span className="hidden text-muted sm:inline">Organization</span>
                <select
                  aria-label="Organization context"
                  value={activeOrg}
                  onChange={(event) => switchOrganization(event.target.value)}
                  className="h-9 max-w-[14rem] rounded-md border border-line bg-card px-2 text-sm"
                >
                  <option value="">All organizations</option>
                  {(organizations.data ?? []).map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span>
              {user.full_name}
              <span className="text-muted"> · {user.membership?.role.replaceAll("_", " ") || "platform admin"}</span>
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                logout().then(() => navigate("/login"));
              }}
            >
              Sign out
            </Button>
          </div>
        </header>
        {platform && !activeOrg ? (
          <p className="border-b border-line bg-paper px-4 py-2 text-sm text-muted">
            Choose an organization in the header to work inside its desk.
          </p>
        ) : null}
        {platform && selectedOrg?.read_only ? (
          <p className="border-b border-danger/30 bg-danger-soft px-4 py-2 text-sm text-danger">
            {selectedOrg.name} is read-only. Its people can view records but cannot change them; you can still
            update it from Organizations.
          </p>
        ) : null}
        {user.membership?.organization.read_only ? (
          <p className="border-b border-danger/30 bg-danger-soft px-4 py-2 text-sm text-danger">
            {user.membership.organization.status === "past_due"
              ? "Payment is past due, so this organization is read-only."
              : "This organization is inactive and read-only."}
            {user.membership.organization.status_reason
              ? ` Reason: ${user.membership.organization.status_reason}.`
              : ""}{" "}
            Contact the platform owner to restore write access.
          </p>
        ) : null}
        {settings.data?.ai_provider === "deterministic" ? (
          <p className="border-b border-warn/30 bg-warn-soft px-4 py-2 text-sm text-warn">
            {settings.data.ai_provider_label}. Hosted model calls have not been run from this desk.
          </p>
        ) : null}
        <main key={activeOrg || "all-organizations"} className="mx-auto max-w-6xl px-4 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
