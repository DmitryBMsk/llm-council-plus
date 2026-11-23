const { test, expect } = require('@playwright/test');
const apiBase = `http://localhost:${process.env.E2E_BACKEND_PORT || '18765'}`;

// #57: below 768 px the sidebar is an off-canvas drawer and the composer wraps.
test.describe('phone viewport', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('drawer opens and closes, a message can be sent, nothing is cut off', async ({ page, request }) => {
    const created = await request.post(`${apiBase}/api/conversations`, { data: {
      models: ['e2e-alpha:latest', 'e2e-beta:latest'],
      chairman: 'e2e-chair:latest', execution_mode: 'full', router_type: 'openrouter',
    } });
    expect(created.ok()).toBeTruthy();
    const { id } = await created.json();
    try {
      await page.goto('/');
      const sidebar = page.locator('#sidebar');
      const toggle = page.getByRole('button', { name: 'Conversations', exact: true });
      await expect(sidebar).toBeHidden();
      await expect(toggle).toHaveAttribute('aria-expanded', 'false');

      await toggle.click();
      await expect(sidebar).toBeInViewport({ ratio: 1 });
      await expect(sidebar).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(sidebar).toBeHidden();
      await expect(toggle).toBeFocused();

      await toggle.click();
      await page.locator('.sidebar-backdrop').click({ position: { x: 360, y: 400 } });
      await expect(sidebar).toBeHidden();

      // The 3-dot menu is portalled to <body>: Escape must not leave it over the chat
      await toggle.click();
      await page.locator('.menu-btn').first().click();
      await expect(page.locator('.menu-dropdown-portal')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.locator('.menu-dropdown-portal')).toHaveCount(0);
      await expect(sidebar).toBeHidden();

      await toggle.click();
      await page.locator('.conversation-item').first().click();
      await expect(sidebar).toBeHidden();

      const input = page.locator('textarea.message-input');
      const send = page.locator('.send-button');
      await input.fill('Explain council agreement on a phone');
      await expect(send).toBeInViewport({ ratio: 1 });
      await send.click();
      await expect(input).toBeEnabled();
      await expect(page.getByText('E2E_ANSWER_42: deterministic council response.', { exact: true }).first()).toBeVisible();
      await page.getByText('How the council decided').click();
      await expect(page.locator('.stage1 .tabs')).toBeVisible();

      for (const width of [390, 360]) {
        await page.setViewportSize({ width, height: 844 });
        await expect(send).toBeInViewport({ ratio: 1 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
          `page scrolls sideways at ${width}px`).toBe(true);
        // .app and .messages-container clip their overflow, so the page-level check alone
        // would pass with content cut off: measure the clipped boxes too.
        for (const selector of ['.messages-container', '.input-form']) {
          const [scrollWidth, clientWidth] = await page.locator(selector)
            .evaluate(el => [el.scrollWidth, el.clientWidth]);
          expect(scrollWidth, `${selector} overflows at ${width}px`).toBeLessThanOrEqual(clientWidth);
        }
      }
    } finally { await request.delete(`${apiBase}/api/conversations/${id}`).catch(() => {}); }
  });
});

test.describe('desktop viewport', () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  test('sidebar is always visible and there is no toggle', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#sidebar')).toBeInViewport({ ratio: 1 });
    await expect(page.locator('.sidebar-toggle')).toBeHidden();
  });
});
