import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = process.env.DAILY_VNEXT_URL || "https://academic-door.github.io/econ-paper-monitor/";
const urls = [base];

async function visibleEntries(page, selector = '.paper-entry') {
  return page.locator(`${selector}:not([hidden])`).count();
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
  assert.ok((await page.locator('.hero-total').count()) >= 1);
  const entries = page.locator('.paper-entry');
  const total = await entries.count();
  assert.ok(total >= 0);

  const search = page.locator('input.search').last();
  const china = page.locator('.filter[data-filter="china"]').last();
  assert.ok(await search.isVisible(), `${url} paper search is not visible`);
  assert.ok(await china.isVisible(), `${url} China filter is not visible`);
  assert.equal(await visibleEntries(page), total, `${url} default paper filter`);
  await china.click();
  await page.waitForTimeout(250);
  assert.equal(await visibleEntries(page), await page.locator('.paper-entry[data-china="true"]').count(), `${url} China filter`);
  await page.locator('.filter[data-filter="all"]').click();
  const searchable = total > 0
    ? await entries.first().getAttribute('data-search')
    : null;
  if (searchable) {
    await search.fill(searchable.split(/\s+/)[0]);
    await page.waitForTimeout(250);
    assert.ok(await visibleEntries(page) >= 1, `${url} search returned no result`);
  }
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
  await page.waitForTimeout(500);
  assert.ok(await page.locator('.hero h1').isVisible(), "Homepage fallback hid Hero title");
  assert.ok(await page.locator('.hero-lede').isVisible(), "Homepage fallback hid Hero lede");
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
