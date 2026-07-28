import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.DAILY_VNEXT_URL || "https://academic-door.github.io/econ-paper-monitor/daily-vnext/";
const urls = [base, base.replace(/daily-vnext\/$/, "")];

async function visibleEntries(page) {
  return page.locator('.paper-entry:not([hidden])').count();
}

async function checkPage(browser, url) {
  const errors = [];
  const page = await browser.newPage();
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2400);
  assert.equal(errors.length, 0, `${url} page errors: ${errors.join(" | ")}`);
  assert.ok(await page.locator('.hero h1').isVisible(), `${url} Hero title is not visible`);
  assert.ok(await page.locator('.hero-lede').isVisible(), `${url} Hero lede is not visible`);
  assert.ok(Number(await page.locator('.hero-total').getAttribute('data-count')) >= 0);
  const total = await page.locator('.paper-entry').count();
  assert.ok(total >= 0);

  for (const type of ["all", "working", "column", "china"]) {
    await page.locator(`[data-filter="${type}"]`).click();
    await page.waitForTimeout(750);
    const expected = type === "all"
      ? total
      : type === "china"
        ? await page.locator('.paper-entry[data-china="true"]').count()
        : await page.locator(`.paper-entry[data-kind="${type}"]`).count();
    assert.equal(await visibleEntries(page), expected, `${url} filter ${type}`);
  }

  await page.locator('[data-filter="all"]').click();
  const searchable = await page.locator('.paper-entry').first().getAttribute('data-search');
  if (searchable) {
    await page.locator('.search').fill(searchable.split(/\s+/)[0]);
    await page.waitForTimeout(250);
    assert.ok(await visibleEntries(page) >= 1, `${url} search returned no result`);
  }
  await page.goto(`${url}?type=column&q=poverty`, { waitUntil: "networkidle", timeout: 60000 });
  assert.equal(await page.locator('.search').inputValue(), "poverty");
  assert.equal(await page.locator('[data-filter="column"]').getAttribute('aria-pressed'), "true");
  await page.close();
}

async function checkGsapFallback(browser) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.route("**/gsap.min.js", (route) => route.abort());
  await page.route("**/ScrollTrigger.min.js", (route) => route.abort());
  await page.route("**/Flip.min.js", (route) => route.abort());
  await page.goto(base, { waitUntil: "networkidle", timeout: 60000 });
  assert.ok(await page.locator('.hero h1').isVisible(), "GSAP fallback hid Hero title");
  assert.ok(await page.locator('.hero-lede').isVisible(), "GSAP fallback hid Hero lede");
  assert.equal(errors.length, 0, `GSAP fallback errors: ${errors.join(" | ")}`);
  await page.close();
}

const browser = await chromium.launch({ headless: true });
try {
  for (const url of urls) await checkPage(browser, url);
  await checkGsapFallback(browser);
  console.log(`Daily vNext public smoke passed for ${urls.join(" and ")}`);
} finally {
  await browser.close();
}
