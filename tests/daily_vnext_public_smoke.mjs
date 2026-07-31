import assert from "node:assert/strict";
import { chromium } from "playwright";

const root = process.env.SITE_ROOT_URL || process.env.DAILY_VNEXT_URL || "https://academic-door.github.io/econ-paper-monitor/";
const dailyVnext = new URL("daily-vnext/", root).href;
const urls = [root, dailyVnext];

async function visibleEntries(page, selector = '.paper-entry') {
  return page.locator(`${selector}:not([hidden])`).count();
}

async function checkPage(browser, url) {
  const errors = [];
  const mobile = Number(process.env.VIEWPORT_WIDTH || 0);
  const page = await browser.newPage(mobile ? { viewport: { width: mobile, height: 844 } } : undefined);
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2400);
  assert.equal(errors.length, 0, `${url} page errors: ${errors.join(" | ")}`);
  assert.ok(await page.locator('.hero h1').isVisible(), `${url} Hero title is not visible`);
  assert.ok(await page.locator('.hero-lede').isVisible(), `${url} Hero lede is not visible`);
  assert.ok((await page.locator('.hero-total').count()) >= 1);
  if (mobile) {
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${url} has horizontal overflow`);
  }
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

async function checkSecondaryPages(browser) {
  const paths = ["classic/", "recent72/", "topics/china/", "archive/", "search/", "journals/", "working-papers/"];
  const mobile = Number(process.env.VIEWPORT_WIDTH || 0);
  for (const path of paths) {
    const url = new URL(path, root).href;
    const page = await browser.newPage(mobile ? { viewport: { width: mobile, height: 844 } } : undefined);
    const errors = [];
    const indexRequests = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("request", (request) => {
      if (request.url().includes("/paper-index/")) indexRequests.push(request.url());
    });
    const response = await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForTimeout(500);
    assert.equal(response?.status(), 200, `${url} did not return 200`);
    assert.equal(errors.length, 0, `${url} page errors: ${errors.join(" | ")}`);
    if (path === "classic/") {
      assert.ok(await page.locator('.sidebar').isVisible(), `${url} classic sidebar is missing`);
    } else {
      assert.ok(await page.locator('.site-header').isVisible(), `${url} vNext header is missing`);
      assert.equal(await page.locator('.sidebar').count(), 0, `${url} legacy sidebar leaked`);
      assert.ok(await page.locator('.secondary-page').isVisible(), `${url} secondary shell is missing`);
    }
    assert.equal(indexRequests.some((requestUrl) => requestUrl.endsWith("/paper-index.json")), false, `${url} requested the legacy full index`);
    if (path === "search/") {
      assert.equal(indexRequests.length, 0, `${url} downloaded search data before user interaction`);
      const initialEntries = await page.locator('.event').count();
      const browse = page.locator('.lazy-start').first();
      if (await browse.count()) {
        await browse.click();
        await page.waitForFunction((count) => document.querySelectorAll('.event').length > count, initialEntries);
        assert.ok(indexRequests.some((requestUrl) => requestUrl.endsWith("/manifest.json")), `${url} did not load its search manifest on demand`);
        assert.ok(indexRequests.some((requestUrl) => /\/shards\/\d{4}\.json$/.test(requestUrl)), `${url} did not load a result shard on demand`);
      }
    }
    if (path === "working-papers/") {
      assert.ok(indexRequests.some((requestUrl) => requestUrl.endsWith("/manifest.json")), `${url} did not load its scoped manifest`);
      assert.ok(indexRequests.length <= 3, `${url} loaded too many initial index files: ${indexRequests.length}`);
      const before = await page.locator('.event').count();
      const more = page.locator('.lazy-more').first();
      if (await more.count()) {
        await more.click();
        await page.waitForFunction((count) => document.querySelectorAll('.event').length > count, before);
      }
    }
    if (mobile) {
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${url} has horizontal overflow`);
    }
    await page.close();
  }
  const feedPage = await browser.newPage();
  const feed = await feedPage.request.get(new URL("feed.xml", root).href);
  assert.equal(feed.status(), 200, "feed.xml did not return 200");
  await feedPage.close();
}

async function checkDetailPage(browser) {
  const listing = await browser.newPage();
  await listing.goto(new URL("recent72/", root).href, { waitUntil: "networkidle", timeout: 60000 });
  const detailHref = await listing.locator('a[href*="paper.html?key="]').first().getAttribute('href');
  assert.ok(detailHref, "Recent72 does not expose a detail-page link");
  const detailUrl = new URL(detailHref, listing.url()).href;
  await listing.close();

  const mobile = Number(process.env.VIEWPORT_WIDTH || 0);
  const page = await browser.newPage(mobile ? { viewport: { width: mobile, height: 844 } } : undefined);
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const response = await page.goto(detailUrl, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForFunction(() => !document.querySelector('#paperRoot')?.classList.contains('detail-loading'));
  assert.equal(response?.status(), 200, `${detailUrl} did not return 200`);
  assert.equal(errors.length, 0, `${detailUrl} page errors: ${errors.join(" | ")}`);
  assert.ok(await page.locator('.detail-page h1').isVisible(), `${detailUrl} detail title is missing`);
  assert.notEqual((await page.locator('.detail-page h1').innerText()).trim(), '正在载入论文详情');
  assert.ok(await page.locator('.site-header').isVisible(), `${detailUrl} vNext header is missing`);
  assert.equal(await page.locator('.sidebar').count(), 0, `${detailUrl} legacy sidebar leaked`);
  assert.equal(await page.locator('a[href*="archive/"]').count(), 0, `${detailUrl} archive navigation leaked`);
  if (mobile) {
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${detailUrl} has horizontal overflow`);
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
  await page.goto(root, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(500);
  assert.ok(await page.locator('.hero h1').isVisible(), "Homepage fallback hid Hero title");
  assert.ok(await page.locator('.hero-lede').isVisible(), "Homepage fallback hid Hero lede");
  assert.equal(errors.length, 0, `GSAP fallback errors: ${errors.join(" | ")}`);
  await page.close();
}

const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_EXECUTABLE || undefined,
});
try {
  for (const url of urls) await checkPage(browser, url);
  await checkSecondaryPages(browser);
  await checkDetailPage(browser);
  await checkGsapFallback(browser);
  console.log(`Daily vNext public smoke passed for ${urls.join(" and ")}`);
} finally {
  await browser.close();
}
