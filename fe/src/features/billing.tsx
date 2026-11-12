import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge, Button, Card, Input, Select, Textarea } from "../components/ui";
import { api } from "../lib/api";
import { isPlatform, useAuth } from "../lib/auth";
import { errorText, labelize, when } from "../lib/format";

type Plan = {
  id: string;
  code: string;
  name: string;
  description: string;
  price_cents: number;
  currency: string;
  interval: string;
  is_active: boolean;
  sort_order: number;
  subscribers: number;
};

type Promo = {
  id: string;
  code: string;
  description: string;
  kind: "percent" | "fixed";
  percent_off: number | null;
  amount_off_cents: number | null;
  currency: string;
  valid_from: string | null;
  valid_until: string | null;
  max_redemptions: number | null;
  is_active: boolean;
  redeemed: number;
};

type Organization = {
  id: string;
  name: string;
  slug: string;
  status: string;
  read_only: boolean;
  status_reason: string;
};

type Subscription = {
  id: string;
  organization: Organization;
  plan: Plan;
  status: string;
  current_period_start: string;
  current_period_end: string;
  list_price_cents: number;
  discount_cents: number;
  amount_cents: number;
  promo_code: string | null;
  notes: string;
  updated_at: string;
};

function money(cents: number, currency: string) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "USD" }).format(cents / 100);
}

function discountLabel(promo: Promo) {
  if (promo.kind === "percent") return `${promo.percent_off}% off`;
  return `${money(promo.amount_off_cents ?? 0, promo.currency)} off`;
}

function statusTone(status: string) {
  if (status === "active" || status === "trialing") return "good" as const;
  if (status === "past_due") return "warn" as const;
  return "bad" as const;
}

export function BillingPage() {
  const { user } = useAuth();
  const client = useQueryClient();
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api<Plan[]>("/api/v1/admin/plans/") });
  const promos = useQuery({ queryKey: ["promo-codes"], queryFn: () => api<Promo[]>("/api/v1/admin/promo-codes/") });
  const orgs = useQuery({
    queryKey: ["organizations"],
    queryFn: () => api<Organization[]>("/api/v1/admin/organizations/"),
  });
  const [orgId, setOrgId] = useState("");
  const subscription = useQuery({
    queryKey: ["subscription", orgId],
    enabled: !!orgId,
    queryFn: () =>
      api<{ organization: Organization; subscription: Subscription | null }>(
        `/api/v1/admin/organizations/${orgId}/subscription/`,
      ),
  });
  const [planForm, setPlanForm] = useState({
    code: "",
    name: "",
    price: "",
    currency: "USD",
    interval: "monthly",
    description: "",
  });
  const [promoForm, setPromoForm] = useState({
    code: "",
    kind: "percent",
    percent: "20",
    amount: "",
    currency: "USD",
    valid_until: "",
    max_redemptions: "",
  });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  if (!isPlatform(user)) return <p className="text-sm text-muted">Platform owners only.</p>;

  async function createPlan() {
    setError("");
    setMessage("");
    try {
      await api("/api/v1/admin/plans/", {
        method: "POST",
        json: {
          code: planForm.code,
          name: planForm.name,
          description: planForm.description,
          price_cents: Math.round(Number(planForm.price || 0) * 100),
          currency: planForm.currency,
          interval: planForm.interval,
        },
      });
      setPlanForm({ code: "", name: "", price: "", currency: "USD", interval: "monthly", description: "" });
      setMessage("Plan created.");
      client.invalidateQueries({ queryKey: ["plans"] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function createPromo() {
    setError("");
    setMessage("");
    try {
      const body: Record<string, unknown> = {
        code: promoForm.code,
        kind: promoForm.kind,
        max_redemptions: promoForm.max_redemptions ? Number(promoForm.max_redemptions) : null,
      };
      if (promoForm.valid_until) {
        body.valid_until = new Date(`${promoForm.valid_until}T23:59:59Z`).toISOString();
      }
      if (promoForm.kind === "percent") {
        body.percent_off = Number(promoForm.percent);
      } else {
        body.amount_off_cents = Math.round(Number(promoForm.amount || 0) * 100);
        body.currency = promoForm.currency;
      }
      await api("/api/v1/admin/promo-codes/", { method: "POST", json: body });
      setPromoForm({
        code: "",
        kind: "percent",
        percent: "20",
        amount: "",
        currency: "USD",
        valid_until: "",
        max_redemptions: "",
      });
      setMessage("Promo code created.");
      client.invalidateQueries({ queryKey: ["promo-codes"] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function togglePlan(plan: Plan) {
    setError("");
    try {
      await api(`/api/v1/admin/plans/${plan.id}/`, { method: "PATCH", json: { is_active: !plan.is_active } });
      client.invalidateQueries({ queryKey: ["plans"] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function togglePromo(promo: Promo) {
    setError("");
    try {
      await api(`/api/v1/admin/promo-codes/${promo.id}/`, {
        method: "PATCH",
        json: { is_active: !promo.is_active },
      });
      client.invalidateQueries({ queryKey: ["promo-codes"] });
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="grid gap-4">
      <h1 className="text-4xl">Plans and billing</h1>
      <p className="text-sm text-muted">
        Plans and promo codes are master records. A subscription decides what an organization pays; a past-due or
        canceled subscription makes that organization read-only.
      </p>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {message ? <p className="text-sm text-accent">{message}</p> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="grid gap-3">
          <h2 className="text-2xl">Plans</h2>
          <div className="grid gap-2">
            {(plans.data ?? []).map((plan) => (
              <div key={plan.id} className="flex items-center justify-between gap-3 border-t border-line pt-2 text-sm">
                <div>
                  <p className="font-medium">
                    {plan.name} <span className="text-muted">({plan.code})</span>
                  </p>
                  <p className="text-muted">
                    {money(plan.price_cents, plan.currency)} / {plan.interval} · {plan.subscribers} subscriber(s)
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={plan.is_active ? "good" : "neutral"}>{plan.is_active ? "active" : "hidden"}</Badge>
                  <Button variant="outline" size="sm" onClick={() => togglePlan(plan)}>
                    {plan.is_active ? "Hide" : "Publish"}
                  </Button>
                </div>
              </div>
            ))}
            {plans.data?.length ? null : <p className="text-sm text-muted">No plans yet.</p>}
          </div>
          <div className="grid gap-2 border-t border-line pt-3 md:grid-cols-2">
            <Input
              aria-label="Plan code"
              placeholder="Code, e.g. studio"
              value={planForm.code}
              onChange={(event) => setPlanForm({ ...planForm, code: event.target.value })}
            />
            <Input
              aria-label="Plan name"
              placeholder="Plan name"
              value={planForm.name}
              onChange={(event) => setPlanForm({ ...planForm, name: event.target.value })}
            />
            <Input
              aria-label="Price"
              type="number"
              min="0"
              step="0.01"
              placeholder="Price"
              value={planForm.price}
              onChange={(event) => setPlanForm({ ...planForm, price: event.target.value })}
            />
            <Input
              aria-label="Currency"
              placeholder="Currency"
              value={planForm.currency}
              onChange={(event) => setPlanForm({ ...planForm, currency: event.target.value })}
            />
            <Select
              label="Interval"
              value={planForm.interval}
              onChange={(value) => setPlanForm({ ...planForm, interval: value })}
            >
              <option value="monthly">Monthly</option>
              <option value="yearly">Yearly</option>
            </Select>
            <Button onClick={createPlan}>Create plan</Button>
            <Textarea
              className="md:col-span-2"
              aria-label="Plan description"
              placeholder="What this plan includes (optional)"
              value={planForm.description}
              onChange={(event) => setPlanForm({ ...planForm, description: event.target.value })}
            />
          </div>
        </Card>

        <Card className="grid gap-3">
          <h2 className="text-2xl">Promo codes</h2>
          <div className="grid gap-2">
            {(promos.data ?? []).map((promo) => (
              <div key={promo.id} className="flex items-center justify-between gap-3 border-t border-line pt-2 text-sm">
                <div>
                  <p className="font-medium">
                    {promo.code} <span className="text-muted">· {discountLabel(promo)}</span>
                  </p>
                  <p className="text-muted">
                    {promo.valid_until ? `Until ${when(promo.valid_until)}` : "No end date"} · {promo.redeemed}
                    {promo.max_redemptions ? `/${promo.max_redemptions}` : ""} redeemed
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={promo.is_active ? "good" : "neutral"}>{promo.is_active ? "active" : "off"}</Badge>
                  <Button variant="outline" size="sm" onClick={() => togglePromo(promo)}>
                    {promo.is_active ? "Disable" : "Enable"}
                  </Button>
                </div>
              </div>
            ))}
            {promos.data?.length ? null : <p className="text-sm text-muted">No promo codes yet.</p>}
          </div>
          <div className="grid gap-2 border-t border-line pt-3 md:grid-cols-2">
            <Input
              aria-label="Promo code"
              placeholder="Code, e.g. LAUNCH20"
              value={promoForm.code}
              onChange={(event) => setPromoForm({ ...promoForm, code: event.target.value })}
            />
            <Select
              label="Discount type"
              value={promoForm.kind}
              onChange={(value) => setPromoForm({ ...promoForm, kind: value })}
            >
              <option value="percent">Percent off</option>
              <option value="fixed">Fixed amount off</option>
            </Select>
            {promoForm.kind === "percent" ? (
              <Input
                aria-label="Percent off"
                type="number"
                min="1"
                max="100"
                placeholder="Percent off"
                value={promoForm.percent}
                onChange={(event) => setPromoForm({ ...promoForm, percent: event.target.value })}
              />
            ) : (
              <>
                <Input
                  aria-label="Amount off"
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="Amount off"
                  value={promoForm.amount}
                  onChange={(event) => setPromoForm({ ...promoForm, amount: event.target.value })}
                />
                <Input
                  aria-label="Promo currency"
                  placeholder="Currency"
                  value={promoForm.currency}
                  onChange={(event) => setPromoForm({ ...promoForm, currency: event.target.value })}
                />
              </>
            )}
            <label className="grid gap-1 text-sm">
              <span className="font-medium">Valid until</span>
              <Input
                type="date"
                value={promoForm.valid_until}
                onChange={(event) => setPromoForm({ ...promoForm, valid_until: event.target.value })}
              />
            </label>
            <Input
              aria-label="Maximum redemptions"
              type="number"
              min="1"
              placeholder="Max redemptions (optional)"
              value={promoForm.max_redemptions}
              onChange={(event) => setPromoForm({ ...promoForm, max_redemptions: event.target.value })}
            />
            <Button onClick={createPromo}>Create promo code</Button>
          </div>
        </Card>

        <Card className="grid gap-3 lg:col-span-2">
          <h2 className="text-2xl">Organization subscription</h2>
          <Select label="Organization" value={orgId} onChange={setOrgId}>
            <option value="">Choose an organization</option>
            {(orgs.data ?? []).map((org) => (
              <option key={org.id} value={org.id}>
                {org.name} · {labelize(org.status)}
              </option>
            ))}
          </Select>
          {orgId ? (
            subscription.isLoading ? (
              <p className="text-sm text-muted">Loading subscription…</p>
            ) : subscription.isError ? (
              <p className="text-sm text-danger">{errorText(subscription.error)}</p>
            ) : (
              <SubscriptionEditor
                key={`${orgId}:${subscription.data?.subscription?.updated_at ?? "new"}`}
                orgId={orgId}
                subscription={subscription.data?.subscription ?? null}
                plans={plans.data ?? []}
                onSaved={() => {
                  client.invalidateQueries({ queryKey: ["subscription", orgId] });
                  client.invalidateQueries({ queryKey: ["organizations"] });
                  client.invalidateQueries({ queryKey: ["plans"] });
                  client.invalidateQueries({ queryKey: ["promo-codes"] });
                }}
              />
            )
          ) : (
            <p className="text-sm text-muted">Choose an organization to view or assign its plan.</p>
          )}
        </Card>
      </div>
    </div>
  );
}

function SubscriptionEditor({
  orgId,
  subscription,
  plans,
  onSaved,
}: {
  orgId: string;
  subscription: Subscription | null;
  plans: Plan[];
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    plan_id: subscription?.plan.id ?? "",
    status: subscription?.status ?? "active",
    current_period_end: subscription ? subscription.current_period_end.slice(0, 10) : "",
    promo_code: subscription?.promo_code ?? "",
    notes: subscription?.notes ?? "",
  });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  async function save() {
    setError("");
    setSaved("");
    try {
      const body: Record<string, unknown> = { ...form };
      if (form.current_period_end) {
        body.current_period_end = new Date(`${form.current_period_end}T00:00:00Z`).toISOString();
      }
      await api(`/api/v1/admin/organizations/${orgId}/subscription/`, { method: "PUT", json: body });
      setSaved("Subscription saved.");
      onSaved();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className="grid gap-3">
      {subscription ? (
        <div className="grid gap-1 text-sm">
          <p>
            Current plan: <strong>{subscription.plan.name}</strong>{" "}
            <Badge tone={statusTone(subscription.status)}>{labelize(subscription.status)}</Badge>
          </p>
          <p>
            Amount due: {money(subscription.amount_cents, subscription.plan.currency)} (list{" "}
            {money(subscription.list_price_cents, subscription.plan.currency)}
            {subscription.discount_cents
              ? `, discount ${money(subscription.discount_cents, subscription.plan.currency)}`
              : ""}
            )
          </p>
          <p>
            Period: {when(subscription.current_period_start)} → {when(subscription.current_period_end)}
            {subscription.promo_code ? ` · promo ${subscription.promo_code}` : ""}
          </p>
          <p>
            Organization status: {labelize(subscription.organization.status)}
            {subscription.organization.read_only ? " (read-only)" : ""}
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted">No subscription yet.</p>
      )}
      <div className="grid gap-2 md:grid-cols-2">
        <Select
          label="Plan"
          value={form.plan_id}
          onChange={(value) => setForm({ ...form, plan_id: value })}
        >
          <option value="">Choose a plan</option>
          {plans
            .filter((plan) => plan.is_active || plan.id === subscription?.plan.id)
            .map((plan) => (
              <option key={plan.id} value={plan.id}>
                {plan.name} · {money(plan.price_cents, plan.currency)} / {plan.interval}
              </option>
            ))}
        </Select>
        <Select label="Status" value={form.status} onChange={(value) => setForm({ ...form, status: value })}>
          <option value="trialing">Trialing</option>
          <option value="active">Active</option>
          <option value="past_due">Past due</option>
          <option value="canceled">Canceled</option>
          <option value="expired">Expired</option>
        </Select>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Period end</span>
          <Input
            type="date"
            value={form.current_period_end}
            onChange={(event) => setForm({ ...form, current_period_end: event.target.value })}
          />
        </label>
        <Input
          aria-label="Promo code"
          placeholder="Promo code (optional)"
          value={form.promo_code}
          onChange={(event) => setForm({ ...form, promo_code: event.target.value })}
        />
        <Input
          aria-label="Subscription notes"
          placeholder="Notes (optional)"
          value={form.notes}
          onChange={(event) => setForm({ ...form, notes: event.target.value })}
        />
        <Button onClick={save}>Save subscription</Button>
      </div>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {saved ? <p className="text-sm text-accent">{saved}</p> : null}
    </div>
  );
}
