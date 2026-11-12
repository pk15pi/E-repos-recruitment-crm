import { expect, test } from "@playwright/test";

const PASSWORD = "Harbor-Desk-19";

async function signIn(page: import("@playwright/test").Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Today on the desk" })).toBeVisible();
}

test("resume becomes a searchable candidate", async ({ page }) => {
  const token = Array.from({ length: 8 }, () => "abcdefghijklmnopqrstuvwxyz"[Math.floor(Math.random() * 26)]).join("");
  const email = `nisha.${token}@example.com`;
  const resume = `Nisha ${token} Iyer
Bengaluru
${email}
+91 9845011224
https://www.linkedin.com/in/nisha-${token}
Senior Backend Engineer
Northwind Payments
Skills
Python, Django, PostgreSQL
Experience
Senior Backend Engineer, Northwind Payments — Jan 2020 – Present
Built ledger services in Python and Django.
Education
B.Tech, IIT Bombay
`;
  await signIn(page, "ravi@sable.test");
  await page.goto("/upload");
  await page.getByLabel("Resume files").setInputFiles({
    name: `nisha-${token}.txt`,
    mimeType: "text/plain",
    buffer: Buffer.from(resume),
  });
  await page.getByRole("link", { name: "Review" }).click({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Review extraction" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /Full name/ })).toHaveValue(new RegExp(`Nisha ${token}`, "i"));
  await page.getByRole("button", { name: "Verify and save candidate" }).click();
  await expect(page.getByRole("heading", { name: new RegExp(`Nisha ${token}`, "i") })).toBeVisible();
  await page.goto("/candidates");
  await page.getByLabel("Search name or text").fill(token);
  await page.getByLabel("Search name or text").blur();
  await expect(page.getByRole("link", { name: new RegExp(token, "i") })).toBeVisible();
});

test("a pasted job description ranks a real candidate, then a client sees only the share", async ({ page }) => {
  await signIn(page, "ravi@sable.test");
  await page.goto("/jobs/from-description");
  const description = `Senior Backend Engineer
Harbour Labs is hiring a Senior Backend Engineer in Bengaluru.
Must have: Python, Django, PostgreSQL, 5+ years experience.
Preferred: AWS.
Hybrid work. Full-time.`;
  await page.getByLabel("Job description").fill(description);
  await page.getByLabel("Client").selectOption({ label: "Harbour Labs" });
  await page.getByRole("button", { name: "Analyze job description" }).click();
  await expect(page.getByText("Analysis ready")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Save requirements" }).click();
  await page.getByRole("button", { name: "Find matching candidates" }).click();
  await page.getByRole("button", { name: "Find matching candidates" }).last().click();
  await expect(page.getByText("Asha Rao").first()).toBeVisible({ timeout: 30_000 });
  const card = page.locator("li").filter({ hasText: "Asha Rao" }).first();
  await card.getByRole("button", { name: "Shortlist" }).click();
  await card.getByLabel("New shortlist name").fill(`Harbour ${Date.now()}`);
  await card.getByRole("button", { name: "Create and add" }).click();
  await expect(card.getByText(/Added to Harbour/)).toBeVisible();
  await card.getByRole("button", { name: "Submit" }).click();
  await card.getByRole("button", { name: "Submit to client" }).click();
  await expect(card.getByText(/Submitted/)).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "client@sable.test");
  await page.goto("/candidates");
  await expect(page.getByRole("link", { name: "Asha Rao" })).toBeVisible();
  await page.getByRole("link", { name: "Asha Rao" }).click();
  await page.getByRole("tab", { name: "contact" }).click();
  await expect(page.getByText("Contact details were not included in this share.")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "otherclient@sable.test");
  await page.goto("/candidates");
  await expect(page.getByRole("link", { name: "Asha Rao" })).toHaveCount(0);
});
