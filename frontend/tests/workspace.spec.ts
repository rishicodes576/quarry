import { test, expect } from "@playwright/test";

let sampleCookies: Awaited<
  ReturnType<import("@playwright/test").BrowserContext["cookies"]>
> = [];
async function login(page: import("@playwright/test").Page) {
  if (sampleCookies.length) await page.context().addCookies(sampleCookies);
  await page.goto("/");
  if (!sampleCookies.length) {
    await page
      .getByRole("button", { name: "Explore sample workspace" })
      .click();
    sampleCookies = await page.context().cookies();
  }
  await expect(
    page.getByRole("heading", { name: "Research, with receipts." }),
  ).toBeVisible();
  sampleCookies = await page.context().cookies();
  await expect(page.locator(".stat").first().locator("strong")).not.toHaveText(
    "0",
  );
}

test("complete evidence workflow, export and reload", async ({ page }) => {
  await login(page);
  await page.screenshot({
    path: "test-results/01-research-workspace.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Source library", exact: false })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Source library." }),
  ).toBeVisible();
  await page.getByLabel("Upload document").setInputFiles({
    name: "browser-audit.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Browser audit\n\nThe BrowserAudit collector uses a 75-second lease and renews it every 25 seconds. Every result commit checks the current fencing token. This is an original synthetic test source.\n",
    ),
  });
  await expect(
    page.getByRole("button", { name: "browser-audit.md", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".document-card")
      .filter({
        has: page.getByRole("button", {
          name: "browser-audit.md",
          exact: true,
        }),
      })
      .getByText("ready", { exact: true }),
  ).toBeVisible({ timeout: 120000 });
  await page.getByRole("button", { name: /New research/ }).click();
  await page
    .getByLabel("Research question")
    .fill(
      "How often does the BrowserAudit collector renew its 75-second lease?",
    );
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  await expect(page.locator(".status-pill.completed")).toBeVisible({
    timeout: 120000,
  });
  await expect(
    page.getByRole("article", { name: "Research answer" }),
  ).toContainText("25 seconds");
  await page.getByRole("button", { name: "E1", exact: true }).first().click();
  await expect(
    page.getByRole("complementary", { name: "Evidence inspector" }),
  ).toContainText("Content fingerprint");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/02-cited-research.png",
    fullPage: true,
  });
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export brief" }).click();
  expect((await download).suggestedFilename()).toMatch(/quarry-.*\.md/);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Research, with receipts." }),
  ).toBeVisible();
  await page.locator(".recent-item").first().click();
  await expect(
    page.getByRole("article", { name: "Research answer" }),
  ).toContainText("25 seconds");
});

test("retrieval lab reports all real strategies", async ({ page }) => {
  await login(page);
  await page
    .getByRole("button", { name: "Retrieval lab", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Compare retrieval", exact: true })
    .click();
  await expect(page.locator(".lab-timing")).toHaveCount(4, { timeout: 120000 });
  await expect(page.locator(".lab-hit").first()).toBeVisible();
  await page.screenshot({
    path: "test-results/03-retrieval-lab.png",
    fullPage: true,
  });
  const evaluationResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/evaluations"),
  );
  await page.getByRole("button", { name: "Evaluations", exact: true }).click();
  const evaluation = await (await evaluationResponse).json();
  if (evaluation.status === "completed" || evaluation.status === "partial")
    await expect(page.getByRole("table").getByRole("row")).toHaveCount(5);
  else
    await expect(
      page.getByRole("heading", { name: "Run the frozen evaluation set." }),
    ).toBeVisible();
  await page.screenshot({
    path: "test-results/04-evaluations.png",
    fullPage: true,
  });
  let release: (() => void) | undefined;
  await page.route("**/api/v1/evaluations", async (route) => {
    await new Promise<void>((resolve) => {
      release = resolve;
    });
    await route.fulfill({
      status: 503,
      json: { detail: "Simulated unavailable artifact" },
    });
  });
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page.getByRole("button", { name: "Evaluations", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Loading measured results." }),
  ).toBeVisible();
  await expect.poll(() => Boolean(release)).toBeTruthy();
  release!();
  await expect(
    page.getByRole("heading", { name: "Results could not be loaded." }),
  ).toBeVisible();
  await page.unroute("**/api/v1/evaluations");
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  if (evaluation.status === "completed" || evaluation.status === "partial")
    await expect(page.getByRole("table").getByRole("row")).toHaveCount(5);
  else
    await expect(
      page.getByRole("heading", { name: "Run the frozen evaluation set." }),
    ).toBeVisible();
});

test("responsive navigation and provider policy", async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Make the rules explicit." }),
  ).toBeVisible();
  await expect(
    page.getByText("Optional paid provider", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".provider-card")
      .filter({ hasText: "Optional paid provider" }),
  ).toContainText("Disabled");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/05-mobile-settings.png",
    fullPage: true,
  });
});

test("cross-origin mutations are rejected", async ({ request }) => {
  const response = await request.post("/api/v1/conversations", {
    headers: { Origin: "https://attacker.example" },
    data: { title: "blocked" },
  });
  expect(response.status()).toBe(403);
});

test("import dialog traps keyboard focus and restores it on Escape", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("button", { name: "Source library", exact: false })
    .first()
    .click();
  const trigger = page.getByRole("button", { name: "Import URL", exact: true });
  await trigger.click();
  const close = page.getByRole("button", { name: "Close import dialog" });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    page.getByRole("button", { name: "Import source", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("invitation signup, least privilege and browser session revocation", async ({
  page,
  browser,
}) => {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.text().includes("Content Security Policy"))
      violations.push(message.text());
  });
  await login(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Account security", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Revoke", exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/06-account-security.png",
    fullPage: true,
  });
  const email = `browser-${Date.now()}@example.com`;
  await page.getByLabel("Invite email").fill(email);
  await page.getByLabel("Permission", { exact: true }).selectOption("viewer");
  await page
    .getByRole("button", { name: "Create invitation", exact: true })
    .click();
  const link = page.getByLabel("Private invitation link");
  await expect(link).toBeVisible();
  const invitation = await link.inputValue();
  const context = await browser.newContext();
  const guest = await context.newPage();
  await guest.goto(invitation);
  await expect(
    guest.getByRole("heading", { name: "Accept your invitation." }),
  ).toBeVisible();
  await expect(guest).not.toHaveURL(/#invite=/);
  await guest
    .getByLabel("New password", { exact: true })
    .fill("a strong browser passphrase 2026");
  await guest.getByRole("button", { name: "Save password" }).click();
  await expect(
    guest.getByText("Account updated. Sign in with your password."),
  ).toBeVisible();
  await guest.getByLabel("Email address").fill(email);
  await guest
    .getByLabel("Password", { exact: true })
    .fill("a strong browser passphrase 2026");
  await guest
    .getByRole("button", { name: "Open workspace", exact: true })
    .click();
  await expect(
    guest.getByRole("heading", { name: "Research, with receipts." }),
  ).toBeVisible();
  await expect(
    guest.getByRole("button", { name: "Start research", exact: true }),
  ).toBeDisabled();
  await guest.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    guest.getByRole("heading", { name: "Workspace access", exact: true }),
  ).toHaveCount(0);
  await guest.getByRole("button", { name: "Revoke", exact: true }).click();
  await expect(
    guest.getByRole("heading", { name: "Welcome to Quarry." }),
  ).toBeVisible();
  await context.close();
  expect(violations).toEqual([]);
});

test("public file exposure, security headers and unauthenticated authorization", async ({
  request,
}) => {
  const response = await request.get("/");
  expect(response.headers()["content-security-policy"]).toContain(
    "script-src 'self' 'nonce-",
  );
  expect(response.headers()["content-security-policy"]).not.toContain(
    "script-src 'unsafe-inline'",
  );
  expect(response.headers()["x-frame-options"]).toBe("DENY");
  for (const path of [
    "/.env",
    "/.git/config",
    "/backup.sql",
    "/api/metrics",
    "/api/docs",
  ])
    expect((await request.get(path)).status()).toBe(404);
  for (const path of [
    "/api/v1/documents",
    "/api/v1/conversations",
    "/api/v1/members",
    "/api/v1/auth/security",
  ])
    expect((await request.get(path)).status()).toBe(401);
});

test("public signup and password recovery deliver real local email and require verification", async ({
  page,
  request,
  browser,
}) => {
  const email = `signup-${Date.now()}@example.com`;
  async function emailLink(purpose: string) {
    let id = "";
    await expect
      .poll(
        async () => {
          const response = await request.get(
            "http://mailpit:8025/api/v1/messages",
          );
          const value = await response.json();
          const mail = value.messages.find(
            (m: { ID: string; Subject: string; To: { Address: string }[] }) =>
              m.To.some((t) => t.Address === email) &&
              m.Subject.includes(purpose),
          );
          id = mail?.ID || "";
          return !!id;
        },
        { timeout: 60000 },
      )
      .toBeTruthy();
    const message = await (
      await request.get(`http://mailpit:8025/api/v1/message/${id}`)
    ).json();
    const link = message.Text.match(
      new RegExp(`http://localhost:3000/#${purpose}=[A-Za-z0-9_-]+`),
    );
    expect(link).toBeTruthy();
    return link[0] as string;
  }
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Email address").fill(email);
  await page.getByRole("button", { name: "Send secure link" }).click();
  await expect(page.getByRole("status")).toContainText(
    "If this address is eligible",
  );
  const verification = await emailLink("signup");
  // No account or cookie is issued before the mail link is redeemed.
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
  await page.goto(verification);
  await page
    .getByLabel("New password", { exact: true })
    .fill("a verified signup passphrase");
  await page.getByLabel("Workspace name").fill("Browser verified workspace");
  await page.getByRole("button", { name: "Save password" }).click();
  await expect(
    page.getByText("Account updated. Sign in with your password."),
  ).toBeVisible();
  await page.getByLabel("Email address").fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("a verified signup passphrase");
  await page
    .getByRole("button", { name: "Open workspace", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Research, with receipts." }),
  ).toBeVisible();
  await expect(page.locator(".workspace-switch")).toContainText(
    "Browser verified workspace",
  );
  await expect(page.locator(".stat").first().locator("strong")).toHaveText("0");
  const separate = await browser.newContext();
  const recovery = await separate.newPage();
  await recovery.goto("/");
  await recovery.getByRole("button", { name: "Forgot password?" }).click();
  await recovery.getByLabel("Email address").fill(email);
  await recovery.getByRole("button", { name: "Send secure link" }).click();
  await expect(recovery.getByRole("status")).toContainText(
    "If this address is eligible",
  );
  await recovery.goto(await emailLink("reset"));
  await recovery
    .getByLabel("New password", { exact: true })
    .fill("a replacement signup passphrase");
  await recovery.getByRole("button", { name: "Save password" }).click();
  await expect(
    recovery.getByText("Account updated. Sign in with your password."),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
  await recovery.getByLabel("Email address").fill(email);
  await recovery
    .getByLabel("Password", { exact: true })
    .fill("a replacement signup passphrase");
  await recovery
    .getByRole("button", { name: "Open workspace", exact: true })
    .click();
  await expect(
    recovery.getByRole("heading", { name: "Research, with receipts." }),
  ).toBeVisible();
  await separate.close();
});

test("live campaign progress, quota state, safe passages and recoverable errors", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "Evaluations", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Live answer-quality campaigns" }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Campaign", exact: true }),
  ).toBeVisible();
  await page.route(
    "**/api/v1/evaluations/campaigns/isolated-v2-dense",
    (route) =>
      route.fulfill({
        json: {
          id: "isolated-v2-dense",
          mode: "dense",
          protocol: "isolated-v2",
          status: "pending",
          completed: 0,
          requested: 37,
          provider: "groq",
          model: "openai/gpt-oss-120b",
          means: {},
          limitations: ["Simulated empty-state fixture"],
          rows: [],
        },
      }),
  );
  await page
    .getByRole("combobox", { name: "Campaign", exact: true })
    .selectOption("isolated-v2-dense");
  await expect(
    page.getByText("No scored answers yet.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Campaign", exact: true })
    .selectOption("legacy");
  await expect(page.getByText(/fully scored/)).toBeVisible();
  const attack = '<img src=x onerror="window.quarryInjected=true">';
  await page.route("**/api/v1/evaluations/campaigns/legacy", async (route) => {
    await route.fulfill({
      json: {
        id: "legacy",
        mode: "hybrid_rerank",
        protocol: "legacy-shared-conversation",
        status: "partial",
        completed: 0,
        requested: 37,
        provider: "groq",
        model: "openai/gpt-oss-120b",
        means: {},
        limitations: ["Simulated browser safety fixture"],
        rows: [
          {
            case_id: "xss-fixture",
            run_id: "fixture",
            response: attack,
            contexts: [attack],
            metrics: {},
          },
        ],
      },
    });
  });
  await page.getByRole("button", { name: "Refresh campaigns" }).click();
  await page.locator("summary").filter({ hasText: "xss-fixture" }).click();
  await expect(page.getByText(attack, { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as { quarryInjected?: boolean }).quarryInjected,
    ),
  ).toBeUndefined();
  await page.route("**/api/v1/evaluations/campaigns", (route) =>
    route.abort("failed"),
  );
  await page.getByRole("button", { name: "Refresh campaigns" }).click();
  await expect(
    page.getByRole("button", { name: "Retry campaign results" }),
  ).toBeVisible();
  await page.unroute("**/api/v1/evaluations/campaigns");
  await page.getByRole("button", { name: "Retry campaign results" }).click();
  await expect(
    page.getByRole("combobox", { name: "Campaign", exact: true }),
  ).toBeVisible();
});
