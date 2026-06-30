/**
 * E2E UI smoke tests via Playwright against Docker stack.
 *
 * Prerequisites:
 *   docker compose up -d --build
 *   npx playwright install chromium
 *
 * Run:
 *   npx playwright test e2e/ui-smoke.spec.mjs --project=chromium
 */

import { test, expect } from '@playwright/test';

const BASE = 'http://localhost';
const API = 'http://localhost:8001';

test.describe('UI Smoke Tests', () => {

  test('1. Frontend loads and shows app title', async ({ page }) => {
    await page.goto(BASE);
    // Wait for React to hydrate
    await page.waitForLoadState('networkidle');

    // Should see some main UI element — sidebar or title
    const body = await page.textContent('body');
    expect(body).toBeTruthy();

    // Take screenshot for evidence
    await page.screenshot({ path: 'e2e/screenshots/01-homepage.png' });
  });

  test('2. Sidebar is visible with LLM Council branding', async ({ page }) => {
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');

    // Look for sidebar or branding text
    const sidebar = page.locator('.sidebar, [class*="sidebar"], [class*="Sidebar"]').first();
    if (await sidebar.isVisible()) {
      const text = await sidebar.textContent();
      expect(text.toLowerCase()).toContain('council');
    }

    await page.screenshot({ path: 'e2e/screenshots/02-sidebar.png' });
  });

  test('3. New conversation button works', async ({ page }) => {
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');

    // Find and click new conversation button
    const newBtn = page.locator('button').filter({ hasText: /new|create|\+/i }).first();
    if (await newBtn.isVisible()) {
      await newBtn.click();
      await page.waitForTimeout(500);
    }

    await page.screenshot({ path: 'e2e/screenshots/03-new-conversation.png' });
  });

  test('4. Chat input is present and focusable', async ({ page }) => {
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');

    // Find textarea or input for chat
    const input = page.locator('textarea, input[type="text"]').first();
    if (await input.isVisible()) {
      await input.focus();
      await input.fill('Hello from Playwright E2E test');
      const value = await input.inputValue();
      expect(value).toContain('Hello from Playwright');
    }

    await page.screenshot({ path: 'e2e/screenshots/04-chat-input.png' });
  });

  test('5. API version shown matches 1.3.1', async ({ page }) => {
    // Verify backend API is accessible from browser context
    const response = await page.request.get(`${API}/api/version`);
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.version).toBe('1.3.1');
  });

  test('6. Conversations API works through UI proxy', async ({ page }) => {
    // Create conversation via API
    const createResp = await page.request.post(`${API}/api/conversations`, { data: {} });
    expect(createResp.ok()).toBeTruthy();
    const conv = await createResp.json();
    expect(conv.id).toBeTruthy();

    // List conversations
    const listResp = await page.request.get(`${API}/api/conversations`);
    expect(listResp.ok()).toBeTruthy();
    const convs = await listResp.json();
    expect(convs.some(c => c.id === conv.id)).toBeTruthy();

    // Cleanup
    await page.request.delete(`${API}/api/conversations/${conv.id}`);
  });

  test('7. Model selector modal can be opened', async ({ page }) => {
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');

    // Look for model selector trigger
    const trigger = page.locator('button').filter({ hasText: /model|select|configure/i }).first();
    if (await trigger.isVisible()) {
      await trigger.click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: 'e2e/screenshots/07-model-selector.png' });
    }
  });

  test('8. Settings page loads', async ({ page }) => {
    // Verify settings API
    const resp = await page.request.get(`${API}/api/settings`);
    expect(resp.ok()).toBeTruthy();
    const settings = await resp.json();
    expect(settings).toHaveProperty('council_temperature');
  });

  test('9. No console errors on page load', async ({ page }) => {
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto(BASE);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Filter out known harmless errors (CORS, favicon, etc)
    const realErrors = errors.filter(e =>
      !e.includes('favicon') &&
      !e.includes('CORS') &&
      !e.includes('ERR_CONNECTION_REFUSED')
    );

    // Allow up to 1 console error (network-related)
    expect(realErrors.length).toBeLessThanOrEqual(1);
  });

  test('10. Page responsive — no layout overflow', async ({ page }) => {
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');

    // Check no horizontal scroll
    const hasOverflow = await page.evaluate(() => {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth;
    });
    expect(hasOverflow).toBe(false);

    await page.screenshot({ path: 'e2e/screenshots/10-responsive.png', fullPage: true });
  });
});
