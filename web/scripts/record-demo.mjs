/**
 * Records the product demo embedded in the README.
 *
 *   make demo        (or: cd web && node scripts/record-demo.mjs)
 *
 * Needs the same live, seeded stack as the e2e suite — this is the real
 * product, not a mockup. The copilot and the bias audit make real LLM calls;
 * those waits are fast-forwarded on screen, with a badge saying so.
 * Output (not committed): docs/demo/demo.mp4 — the README version, under
 * GitHub's 10 MB attachment limit — and docs/demo/demo-linkedin.mp4, the
 * full-quality 2560×1440 file for social posts.
 */
import { chromium } from "@playwright/test";
import path from "node:path";
import { Director, SCALE, VIEWPORT } from "./demo/director.mjs";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3100";
const API = process.env.E2E_API_BASE ?? "http://localhost:8000";
const OUT = {
  readme: path.resolve(import.meta.dirname, "../../docs/demo/demo.mp4"),
  linkedin: path.resolve(import.meta.dirname, "../../docs/demo/demo-linkedin.mp4"),
};

const getJson = async (url) => (await fetch(`${API}${url}`)).json();
const jobs = await getJson("/ats/jobs");
// A job whose applications are spread across the funnel, so the board is not one pile.
const job = jobs.find((j) => j.title.includes("Engenheiro(a) de Dados")) ?? jobs[0];
if (!job) throw new Error("Nenhuma vaga no ATS — rode `make seed` antes de gravar.");
// A pair where every audited axis has something to flip (same choice as the screenshots).
const auditJob = jobs.find((j) => j.title.includes("Site Reliability")) ?? job;
const [auditCandidate] = await getJson("/ats/candidates?q=Henrique");

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT,
  deviceScaleFactor: SCALE,
  colorScheme: "dark",
  locale: "pt-BR",
});
const d = await Director.create(context);
const { page } = d;
page.setDefaultTimeout(30_000);
const nav = (label) => page.getByRole("link", { name: label, exact: true });
const isRank = (r) => r.url().includes("/rank") && r.ok();

// Warm the local embedding and reranker models off camera.
await page.goto(`${BASE}/jobs/${job.id}`);
await page.waitForResponse(isRank, { timeout: 180_000 });

// ── 0 · Title ───────────────────────────────────────────────────────
await d.goto(`${BASE}/`);
await d.card(
  `<h1>Resume Ranker</h1><p>Um ATS com ranking de candidatos por IA — explicável, auditável e com privacidade por padrão.</p>`,
);
await page.getByText("Funil de contratação").waitFor();
await d.hold(800);
await d.record();
await d.hold(2600);
await d.card(null, 700);

// ── 1 · Dashboard ───────────────────────────────────────────────────
await d.caption("Visão geral", "Um ATS completo: vagas, funil de contratação e banco de talentos");
await d.pointAt(page.getByText("Funil de contratação"), 900);
await d.hold(1800);

// ── 2 · Job → ranking ───────────────────────────────────────────────
await d.click(nav("Vagas"));
await d.caption("Vagas", "A IA lê a descrição da vaga e extrai os requisitos");
await d.hold(1200);
const ranked = page.waitForResponse(isRank, { timeout: 180_000 });
await d.click(page.getByRole("link", { name: job.title, exact: true }));
await page.getByText("Requisitos extraídos pela IA").waitFor();
await d.hold(1200);

await d.caption("Ranking", "Busca híbrida em 3 representações + reranker com score calibrado");
await ranked;
const top = page.getByTestId("ranked-candidate").first();
await d.frame(top);
await d.pointAt(top.getByRole("button").first(), 800);
await d.hold(1800);

// ── 3 · Explained analysis ──────────────────────────────────────────
await d.caption("Análise da IA", "Cada afirmação cita um trecho do currículo — e a citação é verificada");
const analyze = top.getByRole("button", { name: /Ver análise da IA|Analisar com IA/ });
const cached = (await analyze.textContent())?.includes("Ver análise");
await d.click(analyze);
const evidence = top.getByText("Evidências citadas");
if (cached) await evidence.waitFor();
else await d.fastForward(8, () => evidence.waitFor({ timeout: 180_000 }));
await d.hold(500);
await d.pointAt(top.getByText(/verificadas no currículo/), 900);
await d.hold(3000);

// ── 4 · Funnel ──────────────────────────────────────────────────────
const funnelTab = page.getByRole("tab", { name: /Funil/ });
await d.click(funnelTab);
await d.caption("Funil", "Arraste candidatos entre as etapas — cada movimento vai para a linha do tempo");
const column = (label) =>
  page.locator("section").filter({ has: page.locator("header", { hasText: label }) });
await column("Triagem inicial").waitFor();
await d.frame(column("Triagem inicial"));
await d.hold(600);
await d.drag(column("Triagem inicial").locator("li[draggable]").first(), column("Entrevista RH").locator("ul"));
await d.hold(1800);

// ── 5 · Copilot ─────────────────────────────────────────────────────
await d.click(nav("Copiloto"));
await d.caption("Copiloto", "Perguntas em linguagem natural — cada fato vem de uma ferramenta, não da memória do modelo");
await d.hold(600);
await d.type(
  page.getByPlaceholder(/Pergunte sobre suas vagas/),
  `Quem são os 3 candidatos mais aderentes à vaga ${job.title}? Compare os dois primeiros.`,
  22,
);
await d.hold(500);
await page.keyboard.press("Enter");
await d.fastForward(8, () => page.getByText(/Ranking —/).first().waitFor({ timeout: 240_000 }));
await d.hold(1200);
await d.frame(page.locator("main .panel > div.overflow-y-auto > *").nth(1));
await d.hold(4000);

// ── 6 · PII boundary ────────────────────────────────────────────────
await d.click(nav("Talentos"));
await d.caption("Privacidade", "Nome, CPF, e-mail e telefone são anonimizados antes de qualquer chamada ao LLM");
await d.hold(800);
await d.click(page.getByRole("link", { name: "Ver perfil" }).first());
await page.getByText("Competências na taxonomia ESCO").waitFor();
await d.hold(700);
await d.click(page.getByRole("tab", { name: /PII e documento/ }));
const piiSummary = page.getByText(/entidades anonimizadas/);
await d.frame(piiSummary);
await d.pointAt(piiSummary, 700);
await d.hold(3200);

// ── 7 · Bias audit ──────────────────────────────────────────────────
await d.click(nav("Equidade"));
await d.caption("Equidade", "Auditoria contrafactual: troca gênero, idade e origem no currículo e mede o impacto no score");
await d.hold(800);
const selects = page.locator("main select");
await d.pointAt(selects.first(), 700);
await selects.first().selectOption(String(auditJob.id));
await d.hold(500);
if (auditCandidate) {
  await d.pointAt(selects.nth(1), 600);
  await selects.nth(1).selectOption(String(auditCandidate.id));
  await d.hold(500);
}
await d.click(page.getByRole("button", { name: "Auditar" }));
// The report's verdict line; "limite de tolerância" alone also matches a static stat card.
const verdict = page.getByText(/Maior variação:/);
await d.fastForward(8, () => verdict.waitFor({ timeout: 240_000 }));
await d.hold(500);
await d.frame(verdict);
await d.pointAt(verdict, 700);
await d.hold(3200);

// ── 8 · Observability ───────────────────────────────────────────────
await d.click(nav("Observabilidade"));
await d.caption("Observabilidade", "Cada etapa vira um span: latência por camada, tokens e custo de cada chamada");
await page.getByText("Tempo por camada do pipeline").waitFor();
await d.hold(2000);
const traceRow = page.locator("button").filter({ hasText: /copilot\.chat/ }).first();
await d.click(traceRow);
const dialog = page.getByRole("dialog");
await d.fastForward(6, () => dialog.getByText("Cascata de execução").waitFor());
await d.hold(1200);
const llmSpan = dialog.getByTestId("span-row").filter({ hasText: /llm\./ }).first();
if (await llmSpan.count()) await d.click(llmSpan);
await d.hold(3000);

// ── 9 · Outro ───────────────────────────────────────────────────────
await d.caption("", "");
await d.card(
  `<h1>Resume Ranker</h1><p>FastAPI · Qdrant · Next.js · reranker local · Presidio</p><small>github.com/luccapinto/resume_ranker</small>`,
  3500,
);

await d.finish(OUT);
await browser.close();
for (const file of Object.values(OUT)) console.log(`Demo gravada em ${path.relative(process.cwd(), file)}`);
