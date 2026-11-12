import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { ErrorState } from "../components/states";
import { Button, Card, Input, Label } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { errorText } from "../lib/format";

const loginSchema = z.object({
  email: z.string().trim().min(1, "Email is required.").regex(/^[^\s@]+@[^\s@]+\.[^\s@]+$/, "Enter a valid email."),
  password: z.string().min(1, "Password is required."),
});

const loginOtpSchema = z.object({
  email: z.string().trim().min(1, "Email is required.").regex(/^[^\s@]+@[^\s@]+\.[^\s@]+$/, "Enter a valid email."),
  code: z.string().trim().regex(/^\d{6}$/, "Enter the 6-digit code."),
});

export function LoginPage() {
  const { login, loginWithOtp, user } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"password" | "code">("password");
  const [error, setError] = useState("");
  const [otpMessage, setOtpMessage] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const form = useForm({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });
  const otpForm = useForm({
    resolver: zodResolver(loginOtpSchema),
    defaultValues: { email: "", code: "" },
  });

  if (user) {
    navigate("/", { replace: true });
  }

  async function sendCode() {
    setError("");
    setOtpMessage("");
    if (!(await otpForm.trigger("email"))) return;
    setSendingCode(true);
    try {
      await api("/api/v1/auth/otp/request/", {
        method: "POST",
        json: { email: otpForm.getValues("email") },
      });
      setOtpMessage("If that email belongs to a desk account, a 6-digit code is on its way. It expires in ten minutes.");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSendingCode(false);
    }
  }

  return (
    <div className="mx-auto grid min-h-screen max-w-md place-items-center px-4">
      <Card className="w-full">
        <p className="text-sm text-accent">Sable</p>
        <h1 className="mt-1 text-4xl">Sign in to the desk</h1>
        <p className="mt-2 text-sm text-muted">Candidate files stay inside the agency until a recruiter shares them with a client.</p>
        {mode === "password" ? (
          <form
            className="mt-6 grid gap-3"
            noValidate
            onSubmit={form.handleSubmit(async (values) => {
              setError("");
              try {
                await login(values.email, values.password);
                navigate("/");
              } catch (err) {
                setError(errorText(err));
              }
            })}
          >
            <div className="grid gap-1">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="username" {...form.register("email")} />
              {form.formState.errors.email ? <p className="text-sm text-danger">{form.formState.errors.email.message}</p> : null}
            </div>
            <div className="grid gap-1">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
              {form.formState.errors.password ? <p className="text-sm text-danger">{form.formState.errors.password.message}</p> : null}
            </div>
            {error ? <ErrorState message={error} /> : null}
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        ) : (
          <form
            className="mt-6 grid gap-3"
            noValidate
            onSubmit={otpForm.handleSubmit(async (values) => {
              setError("");
              try {
                await loginWithOtp(values.email, values.code);
                navigate("/");
              } catch (err) {
                setError(errorText(err));
              }
            })}
          >
            <div className="grid gap-1">
              <Label htmlFor="otp-email">Email</Label>
              <Input id="otp-email" type="email" autoComplete="username" {...otpForm.register("email")} />
              {otpForm.formState.errors.email ? <p className="text-sm text-danger">{otpForm.formState.errors.email.message}</p> : null}
            </div>
            <Button type="button" variant="outline" onClick={sendCode} disabled={sendingCode}>
              {sendingCode ? "Sending…" : "Email me a code"}
            </Button>
            {otpMessage ? <p className="text-sm text-muted">{otpMessage}</p> : null}
            <div className="grid gap-1">
              <Label htmlFor="otp-code">6-digit code</Label>
              <Input
                id="otp-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                {...otpForm.register("code")}
              />
              {otpForm.formState.errors.code ? <p className="text-sm text-danger">{otpForm.formState.errors.code.message}</p> : null}
            </div>
            {error ? <ErrorState message={error} /> : null}
            <Button type="submit" disabled={otpForm.formState.isSubmitting}>
              {otpForm.formState.isSubmitting ? "Signing in…" : "Sign in with code"}
            </Button>
          </form>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setMode(mode === "password" ? "code" : "password");
              setError("");
              setOtpMessage("");
            }}
          >
            {mode === "password" ? "Email me a sign-in code" : "Use a password instead"}
          </Button>
          {mode === "password" ? (
            <Link className="text-sm text-accent" to="/recover">
              Forgot password
            </Link>
          ) : null}
        </div>
        <p className="mt-4 text-xs text-muted">Local seed: ravi@sable.test or ada@sable.test, password Harbor-Desk-19. Client desk: client@sable.test.</p>
      </Card>
    </div>
  );
}

const recoverSchema = z.object({
  email: z.string().trim().min(1, "Email is required.").regex(/^[^\s@]+@[^\s@]+\.[^\s@]+$/, "Enter a valid email."),
  code: z.string().trim().regex(/^\d{6}$/, "Enter the 6-digit code."),
  password: z.string().min(8, "Use at least 8 characters."),
});

export function RecoverPage() {
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const form = useForm({
    resolver: zodResolver(recoverSchema),
    defaultValues: { email: "", code: "", password: "" },
  });

  async function sendCode() {
    setError("");
    if (!(await form.trigger("email"))) return;
    setSending(true);
    try {
      await api("/api/v1/auth/password-reset/otp/", {
        method: "POST",
        json: { email: form.getValues("email") },
      });
      setSent(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mx-auto grid min-h-screen max-w-md place-items-center px-4">
      <Card className="w-full">
        <h1 className="text-4xl">Reset a password</h1>
        <p className="mt-2 text-sm text-muted">
          We email a 6-digit code. If the email belongs to a desk account, the code arrives within a minute.
        </p>
        {done ? (
          <div className="mt-4 grid gap-3">
            <p className="text-sm">Your password was updated. Sign in with the new password.</p>
            <Link className="text-sm text-accent" to="/login">
              Back to sign in
            </Link>
          </div>
        ) : (
          <form
            className="mt-4 grid gap-3"
            noValidate
            onSubmit={form.handleSubmit(async (values) => {
              setError("");
              try {
                await api("/api/v1/auth/password-reset/otp/confirm/", { method: "POST", json: values });
                setDone(true);
              } catch (err) {
                setError(errorText(err));
              }
            })}
          >
            <div className="grid gap-1">
              <Label htmlFor="recover-email">Email</Label>
              <Input id="recover-email" type="email" autoComplete="username" {...form.register("email")} />
              {form.formState.errors.email ? <p className="text-sm text-danger">{form.formState.errors.email.message}</p> : null}
            </div>
            {sent ? (
              <>
                <p className="text-sm text-muted">
                  If that email belongs to a desk account, a code is on its way. It expires in ten minutes.
                </p>
                <div className="grid gap-1">
                  <Label htmlFor="recover-code">6-digit code</Label>
                  <Input
                    id="recover-code"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    {...form.register("code")}
                  />
                  {form.formState.errors.code ? <p className="text-sm text-danger">{form.formState.errors.code.message}</p> : null}
                </div>
                <div className="grid gap-1">
                  <Label htmlFor="recover-password">New password</Label>
                  <Input id="recover-password" type="password" autoComplete="new-password" {...form.register("password")} />
                  {form.formState.errors.password ? (
                    <p className="text-sm text-danger">{form.formState.errors.password.message}</p>
                  ) : null}
                </div>
                {error ? <ErrorState message={error} /> : null}
                <Button type="submit" disabled={form.formState.isSubmitting}>
                  {form.formState.isSubmitting ? "Updating…" : "Reset password"}
                </Button>
              </>
            ) : (
              <>
                {error ? <ErrorState message={error} /> : null}
                <Button type="button" onClick={sendCode} disabled={sending}>
                  {sending ? "Sending…" : "Email me a code"}
                </Button>
              </>
            )}
          </form>
        )}
        {done ? null : (
          <Link className="mt-4 inline-block text-sm" to="/login">
            Back to sign in
          </Link>
        )}
      </Card>
    </div>
  );
}

const resetSchema = z.object({
  password: z.string().min(8, "Use at least 8 characters."),
});

export function ResetPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const form = useForm({ resolver: zodResolver(resetSchema), defaultValues: { password: "" } });
  return (
    <div className="mx-auto grid min-h-screen max-w-md place-items-center px-4">
      <Card className="w-full">
        <h1 className="text-4xl">Choose a new password</h1>
        <form
          className="mt-4 grid gap-3"
          onSubmit={form.handleSubmit(async (values) => {
            setError("");
            try {
              await api("/api/v1/auth/password-reset/confirm/", {
                method: "POST",
                json: { token: params.get("token") || "", password: values.password },
              });
              navigate("/login");
            } catch (err) {
              setError(errorText(err));
            }
          })}
        >
          <Label htmlFor="new-password">New password</Label>
          <Input id="new-password" type="password" {...form.register("password")} />
          {form.formState.errors.password ? <p className="text-sm text-danger">{form.formState.errors.password.message}</p> : null}
          {error ? <ErrorState message={error} /> : null}
          <Button type="submit">Update password</Button>
        </form>
      </Card>
    </div>
  );
}
