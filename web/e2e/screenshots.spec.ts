import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Captures the screenshots embedded in the README.
 *
 *   cd web && npx playwright test e2e/screenshots.spec.ts
 *
 * Requires a live, seeded stack — the images are of the real product, not
 * mockups. Output goes to docs/screenshots/.
 */

const API = process.env.E2E_API_BASE ?? "http://localhost:8000";
const OUT = path.resolve(__dirname, "../../docs/screenshots");

test.beforeAll(() => fs.mkdirSync(OUT, { recursive: true }));

/** Let fade-in animations settle so nothing is captured mid-transition. */
async function settle(page: Page, ms = 900) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(ms);
}

async function shoot(page: Page, name: string, fullPage = false) {
  await settle(page);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage });
}

async function firstJob(): Promise<{ id: number; title: string }> {
  const jobs = await (await fetch(`${API}/ats/jobs`)).json();
  return jobs[0];
}

test.describe.configure({ mode: "serial" });

test("01 — visão geral", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Funil de contratação")).toBeVisible();
  await shoot(page, "01-dashboard", true);
});

test("02 — vagas", async ({ page }) => {
  await page.goto("/jobs");
  await expect(page.locator("main .panel").first()).toBeVisible();
  await shoot(page, "02-vagas", true);
});

test("03 — ranking de candidatos", async ({ page }) => {
  const job = await firstJob();
  await page.goto(`/jobs/${job.id}`);
  await page.waitForResponse((r) => r.url().includes("/rank") && r.status() === 200, {
    timeout: 90_000,
  });
  await expect(page.getByText(/das competências da vaga/).first()).toBeVisible();
  await shoot(page, "03-ranking", true);
});

test("04 — análise da IA com evidências verificadas", async ({ page }) => {
  test.setTimeout(240_000);
  const job = await firstJob();
  await page.goto(`/jobs/${job.id}`);
  await page.waitForResponse((r) => r.url().includes("/rank") && r.status() === 200, {
    timeout: 90_000,
  });

  const card = page.getByTestId("ranked-candidate").first();
  await card.getByRole("button", { name: "Analisar com IA" }).click();
  await expect(card.getByText("Evidências citadas")).toBeVisible({ timeout: 180_000 });

  await card.scrollIntoViewIfNeeded();
  await settle(page);
  await card.screenshot({ path: path.join(OUT, "04-analise-ia.png") });
});

test("05 — funil kanban", async ({ page }) => {
  const job = await firstJob();
  await page.goto(`/jobs/${job.id}`);
  await page.waitForResponse((r) => r.url().includes("/rank") && r.status() === 200, {
    timeout: 90_000,
  });
  await page.getByRole("tab", { name: /Funil/ }).click();
  await expect(page.getByText("Triagem inicial")).toBeVisible();
  await shoot(page, "05-funil-kanban");
});

test("06 — comparador de PII", async ({ page }) => {
  const job = await firstJob();
  await page.goto(`/jobs/${job.id}`);
  await page.waitForResponse((r) => r.url().includes("/rank") && r.status() === 200, {
    timeout: 90_000,
  });
  await page.getByRole("tab", { name: /Documento e PII/ }).click();
  await expect(page.getByText("Texto enviado à IA (anonimizado)")).toBeVisible();
  await shoot(page, "06-pii");
});

test("07 — perfil do candidato", async ({ page }) => {
  await page.goto("/candidates");
  await page
    .locator("main .panel")
    .filter({ hasText: "Ver perfil" })
    .first()
    .getByRole("link", { name: "Ver perfil" })
    .click();
  await expect(page.getByText("Competências na taxonomia ESCO")).toBeVisible();
  await shoot(page, "07-candidato", true);
});

test("08 — copiloto conversacional", async ({ page }) => {
  test.setTimeout(300_000);
  const job = await firstJob();
  await page.goto("/copilot");
  await page
    .getByPlaceholder(/Pergunte sobre suas vagas/)
    .fill(`Quais são os 5 candidatos mais aderentes à vaga ${job.title}? Comente os dois primeiros.`);
  await page.keyboard.press("Enter");

  await expect(page.getByText(/Ranking —/)).toBeVisible({ timeout: 240_000 });

  // The transcript lives in its own scroll container and auto-scrolls to the
  // bottom; rewind it so the question and the answer are both in frame.
  await page.evaluate(() => {
    const scroller = document.querySelector("main .panel > div.overflow-y-auto");
    scroller?.scrollTo({ top: 0 });
  });
  await shoot(page, "08-copiloto");
});

test("09 — observabilidade", async ({ page }) => {
  await page.goto("/observability");
  await expect(page.getByText("Tempo por camada do pipeline")).toBeVisible();
  // fullPage would be dominated by the trace list; the metrics are the story.
  await shoot(page, "09-observabilidade");
});

test("10 — cascata de um trace", async ({ page }) => {
  await page.goto("/observability");
  await expect(page.getByText("Traces recentes")).toBeVisible();

  // Prefer a trace with LLM calls, so the span detail has a prompt to show.
  const row = page.locator("button").filter({ hasText: /seed\.explain|copilot\.chat|explain\.pair/ }).first();
  await row.click();
  await expect(page.getByText("Cascata de execução")).toBeVisible();

  const dialog = page.getByRole("dialog");
  const llmSpan = dialog.getByTestId("span-row").filter({ hasText: /llm\./ }).first();
  await (await llmSpan.count() ? llmSpan : dialog.getByTestId("span-row").first()).click();
  await expect(dialog.getByText(/Atributos|Entrada enviada/).first()).toBeVisible();

  await settle(page);
  await dialog.screenshot({ path: path.join(OUT, "10-trace.png") });
});

test("11 — auditoria de viés", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/fairness");

  // Pick a pair where every axis has something to flip, so the report is not
  // four "not applicable" rows.
  const jobSelect = page.locator("select").first();
  const candidateSelect = page.locator("select").nth(1);
  const jobId = (await (await fetch(`${API}/ats/jobs`)).json()).find(
    (j: { title: string }) => j.title.includes("Site Reliability"),
  ).id;
  const candidateId = (await (await fetch(`${API}/ats/candidates?q=Henrique`)).json())[0].id;
  await jobSelect.selectOption(String(jobId));
  await candidateSelect.selectOption(String(candidateId));

  await page.getByRole("button", { name: "Auditar" }).click();
  await expect(page.getByText(/limite de tolerância/)).toBeVisible({ timeout: 200_000 });
  await shoot(page, "11-equidade", true);
});
