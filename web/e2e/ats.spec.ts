import { expect, test, type Page } from "@playwright/test";

/**
 * End-to-end journey through the ATS, against a live, seeded stack.
 *
 * These tests deliberately assert on *outcomes a recruiter would notice* —
 * candidates appear ranked, the score is a real number, the AI analysis quotes
 * the résumé, dragging a card moves it in the funnel — rather than on internal
 * state the unit tests already cover.
 */

const API = process.env.E2E_API_BASE ?? "http://localhost:8000";

async function firstJobId(): Promise<number> {
  const response = await fetch(`${API}/ats/jobs`);
  const jobs = await response.json();
  expect(jobs.length, "o ATS precisa estar populado (make seed)").toBeGreaterThan(0);
  return jobs[0].id;
}

/** Wait for the ranking request the job page fires on arrival. */
async function waitForRanking(page: Page) {
  await page.waitForResponse(
    (r) => r.url().includes("/rank") && r.status() === 200,
    { timeout: 90_000 },
  );
}

test.describe("infraestrutura", () => {
  test("a API responde e reporta os dois bancos conectados", async () => {
    const health = await (await fetch(`${API}/health`)).json();
    expect(health.status).toBe("ok");
    expect(health.postgres).toBe("connected");
    expect(health.qdrant).toBe("connected");
  });

  test("o ATS está populado com vagas e candidatos", async () => {
    const overview = await (await fetch(`${API}/ats/overview`)).json();
    expect(overview.jobs_total).toBeGreaterThan(0);
    expect(overview.candidates_total).toBeGreaterThan(0);
    expect(overview.applications_total).toBeGreaterThan(0);
  });
});

test.describe("visão geral", () => {
  test("mostra os indicadores do funil e a saúde do pipeline de IA", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Visão geral" })).toBeVisible();
    await expect(page.getByText("Vagas abertas")).toBeVisible();
    await expect(page.getByText("Banco de talentos")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Funil de contratação" })).toBeVisible();

    // The observability panel must show real traces, not the empty state.
    await expect(page.getByRole("heading", { name: "Saúde do pipeline de IA" })).toBeVisible();
    await expect(page.getByText("Nenhuma execução registrada")).toHaveCount(0);
  });

  test("a barra lateral reporta a API conectada e o modelo em uso", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("API conectada")).toBeVisible();
    await expect(page.getByText("PII anonimizada antes de qualquer LLM")).toBeVisible();
  });
});

test.describe("vagas e ranqueamento", () => {
  test("lista as vagas com competências obrigatórias", async ({ page }) => {
    await page.goto("/jobs");
    await expect(page.getByRole("heading", { name: "Vagas" })).toBeVisible();
    const cards = page.locator("main .panel").filter({ hasText: "Ranquear candidatos" });
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThan(0);
  });

  test("ranqueia candidatos e mostra score, aderência e cobertura", async ({ page }) => {
    const jobId = await firstJobId();
    await page.goto(`/jobs/${jobId}`);
    await waitForRanking(page);

    // The podium is rendered with a real, bounded score.
    const firstCard = page.getByTestId("ranked-candidate").first();
    await expect(firstCard).toBeVisible();
    await expect(firstCard.getByText(/das competências da vaga/)).toBeVisible();

    const scoreLabel = firstCard.locator("svg[role='img'][aria-label^='Score']").first();
    await expect(scoreLabel).toBeVisible();
    const aria = await scoreLabel.getAttribute("aria-label");
    const score = Number(aria?.match(/Score (\d+)/)?.[1]);
    expect(score).toBeGreaterThanOrEqual(0);
    expect(score).toBeLessThanOrEqual(100);

    // Fit is never colour-only: the word is always present.
    await expect(firstCard.getByText(/Aderência (forte|moderada|baixa)/)).toBeVisible();
  });

  test("expõe por qual estratégia de busca cada candidato foi encontrado", async ({ page }) => {
    const jobId = await firstJobId();
    await page.goto(`/jobs/${jobId}`);
    await waitForRanking(page);

    const firstCard = page.getByTestId("ranked-candidate").first();
    await firstCard.getByRole("button", { name: /Analisar com IA|Ver análise da IA/ }).click();

    await expect(firstCard.getByText("Como este candidato foi encontrado")).toBeVisible();
    await expect(firstCard.getByText(/Após reranking:/)).toBeVisible();
  });

  test("a análise da IA cita trechos e marca cada citação como verificada", async ({ page }) => {
    test.setTimeout(180_000);
    const jobId = await firstJobId();
    await page.goto(`/jobs/${jobId}`);
    await waitForRanking(page);

    const firstCard = page.getByTestId("ranked-candidate").first();
    await firstCard.getByRole("button", { name: "Analisar com IA" }).click();

    await expect(firstCard.getByText("Evidências citadas")).toBeVisible({ timeout: 120_000 });
    await expect(firstCard.getByText(/verificadas no currículo/)).toBeVisible();
    await expect(firstCard.getByText("Pontos fortes", { exact: true })).toBeVisible();
    await expect(firstCard.getByText("Perguntas sugeridas para a entrevista")).toBeVisible();
  });

  test("os controles de busca expõem os pesos da fusão RRF", async ({ page }) => {
    const jobId = await firstJobId();
    await page.goto(`/jobs/${jobId}`);
    await waitForRanking(page);

    await page.getByRole("button", { name: "Ajustar busca" }).click();
    await expect(page.getByText("Pesos da fusão RRF")).toBeVisible();
    await expect(page.getByText("Reranking com cross-encoder")).toBeVisible();
  });

  test("o funil kanban lista as candidaturas por etapa", async ({ page }) => {
    const jobId = await firstJobId();
    await page.goto(`/jobs/${jobId}`);
    await waitForRanking(page);

    await page.getByRole("tab", { name: /Funil/ }).click();
    await expect(page.getByText("Triagem inicial")).toBeVisible();
    await expect(page.getByText("Entrevista técnica")).toBeVisible();
    await expect(page.getByText("Contratado")).toBeVisible();
  });

  test("a aba de documento prova que a IA só recebeu o texto anonimizado", async ({ page }) => {
    const jobId = await firstJobId();
    await page.goto(`/jobs/${jobId}`);
    await waitForRanking(page);

    await page.getByRole("tab", { name: /Documento e PII/ }).click();
    await expect(page.getByText("Texto enviado à IA (anonimizado)")).toBeVisible();
    await expect(page.getByText("Documento original (nunca enviado à IA)")).toBeVisible();
  });
});

test.describe("talentos", () => {
  test("busca no banco de talentos filtra a lista", async ({ page }) => {
    await page.goto("/candidates");
    const cards = page.locator("main .panel").filter({ hasText: "Ver perfil" });
    await expect(cards.first()).toBeVisible();
    const total = await cards.count();

    await page.getByPlaceholder(/Buscar por nome/).fill("zzzz-inexistente");
    await expect(page.getByText("Nenhum candidato corresponde à busca")).toBeVisible();

    await page.getByRole("button", { name: "Limpar busca" }).click();
    await expect(cards).toHaveCount(total);
  });

  test("o perfil mostra o mapeamento ESCO e o comparador de PII", async ({ page }) => {
    await page.goto("/candidates");
    await page.locator("main .panel").filter({ hasText: "Ver perfil" }).first()
      .getByRole("link", { name: "Ver perfil" }).click();

    await expect(page.getByText("Competências na taxonomia ESCO")).toBeVisible();
    await expect(page.getByText("Trajetória consolidada pela IA")).toBeVisible();

    await page.getByRole("tab", { name: /PII e documento/ }).click();
    await expect(page.getByText(/entidades anonimizadas/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Revelar dados originais" })).toBeVisible();
  });
});

test.describe("equidade", () => {
  test("roda a auditoria contrafactual nos quatro eixos", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/fairness");

    await expect(page.getByRole("heading", { name: "Equidade algorítmica" })).toBeVisible();

    const jobSelect = page.locator("select").first();
    const candidateSelect = page.locator("select").nth(1);
    await jobSelect.selectOption({ index: 1 });
    await candidateSelect.selectOption({ index: 1 });
    await page.getByRole("button", { name: "Auditar" }).click();

    await expect(page.getByText(/limite de tolerância/)).toBeVisible({ timeout: 150_000 });
    for (const axis of ["Gênero", "Nome e sobrenome", "Idade / tempo de formação", "Instituição de ensino"]) {
      await expect(page.getByText(axis, { exact: true })).toBeVisible();
    }
  });
});

test.describe("observabilidade", () => {
  test("mostra métricas agregadas e a lista de traces", async ({ page }) => {
    await page.goto("/observability");

    await expect(page.getByRole("heading", { name: "Observabilidade" })).toBeVisible();
    await expect(page.getByText("Latência p95", { exact: true })).toBeVisible();
    await expect(page.getByText("Custo acumulado", { exact: true })).toBeVisible();
    await expect(page.getByText("Tempo por camada do pipeline")).toBeVisible();
    await expect(page.getByText("Traces recentes")).toBeVisible();
  });

  test("abre a cascata de um trace e detalha um span", async ({ page }) => {
    await page.goto("/observability");

    await page.locator("button").filter({ hasText: /seed\.|ats\.|ingest\./ }).first().click();
    await expect(page.getByText("Cascata de execução")).toBeVisible();

    // Clicking a span in the waterfall reveals its attributes.
    await page.getByRole("dialog").getByTestId("span-row").first().click();
    await expect(page.getByRole("dialog").getByText(/Atributos|Entrada enviada/).first()).toBeVisible();
  });

  test("o gráfico de latência oferece a visão em tabela", async ({ page }) => {
    await page.goto("/observability");
    await page.getByRole("button", { name: "Ver dados" }).first().click();
    await expect(page.getByRole("table").first()).toBeVisible();
  });
});

test.describe("copiloto", () => {
  test("responde usando ferramentas e devolve um ranking renderizado", async ({ page }) => {
    test.setTimeout(240_000);
    await page.goto("/copilot");

    await expect(page.getByText("Ferramentas disponíveis")).toBeVisible();
    await expect(page.getByText("ranquear_candidatos")).toBeVisible();

    const jobId = await firstJobId();
    const jobs = await (await fetch(`${API}/ats/jobs`)).json();
    const title = jobs.find((j: { id: number }) => j.id === jobId).title;

    await page
      .getByPlaceholder(/Pergunte sobre suas vagas/)
      .fill(`Liste os 5 melhores candidatos para a vaga ${title}.`);
    await page.keyboard.press("Enter");

    // The tool badge proves the copilot queried real data instead of inventing it.
    await expect(page.getByText("ranquear_candidatos").nth(1)).toBeVisible({ timeout: 200_000 });
    await expect(page.getByText(/Ranking —/)).toBeVisible();
  });
});
