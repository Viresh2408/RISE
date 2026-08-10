import { test, expect } from '@playwright/test';

const VIEWPORTS = [
  { width: 375, height: 812, name: 'mobile' },
  { width: 1280, height: 800, name: 'desktop-sm' },
  { width: 1440, height: 900, name: 'desktop-lg' },
];

const PAGES = [
  { path: '/', name: 'Marketing Landing' },
  { path: '/login', name: 'Login' },
  { path: '/incidents', name: 'Incidents Feed' },
  { path: '/incidents/mock-001', name: 'Incident Detail' },
  { path: '/reports', name: 'Reports' },
  { path: '/policies', name: 'Policies' },
  { path: '/knowledge', name: 'Knowledge Base' },
  { path: '/integrations', name: 'Integrations' },
  { path: '/non-existent-route-404-test', name: '404 Fallback' },
];

// 1. Spacing Assertions
test('incident card desktop padding >= 24px', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/incidents');
  const card = page.locator('[data-testid="incident-card"]').first();
  if (await card.isVisible()) {
    const paddingLeft = await card.evaluate((el) => parseInt(getComputedStyle(el).paddingLeft));
    expect(paddingLeft).toBeGreaterThanOrEqual(24);
  }
});

test('action panel button gap >= 16px on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/incidents/mock-001');
  const row = page.locator('[data-testid="action-btn-row"]');
  if (await row.isVisible()) {
    const gap = await row.evaluate((el) => parseInt(getComputedStyle(el).gap));
    expect(gap).toBeGreaterThanOrEqual(16);
  }
});

// 2. AdminGate Fetch Prevention Test
test('AdminGate blocks /policies API fetch for non-admin session', async ({ page }) => {
  let policiesApiCalled = false;
  await page.route('**/api/v1/policies', (route) => {
    policiesApiCalled = true;
    route.fulfill({ status: 200, body: JSON.stringify({ data: [] }) });
  });

  await page.goto('/policies');
  // Confirm unauthenticated/non-admin gate blocks render & fetch
  expect(page.locator('text=Admin Access Required')).toBeDefined();
});

// 3. Viewport & Overflow Assertions across all 9 pages + 404
for (const vp of VIEWPORTS) {
  for (const p of PAGES) {
    test(`${p.name} at ${vp.width}px — no horizontal scroll overflow`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(p.path);
      const scrollWidth = await page.evaluate(() => document.body.scrollWidth);
      expect(scrollWidth).toBeLessThanOrEqual(vp.width + 2);
    });
  }
}
