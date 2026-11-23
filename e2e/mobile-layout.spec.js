const { test, expect } = require('@playwright/test');
const apiBase = `http://localhost:${process.env.E2E_BACKEND_PORT || '18765'}`;

// .app, .messages-container and .stage all clip their overflow, so scrollWidth checks pass
// while content is cut off: list the descendants whose box leaves the viewport instead.
// The tab strip, the judge matrix and code blocks are skipped: they scroll sideways by design.
const cutOff = (page, selector) => page.locator(selector).evaluate(el =>
  [...el.querySelectorAll('*')].filter(child => {
    const box = child.getBoundingClientRect();
    return box.width > 0 && !child.closest('.tabs, .judge-matrix, pre') && (box.right > window.innerWidth + 1 || box.left < -1);
  }).map(child => `${child.tagName}.${child.className}`));

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
      expect(await cutOff(page, '.chat-interface'), 'empty state at 390px').toEqual([]);

      await toggle.click();
      await expect(sidebar).toBeInViewport({ ratio: 1 });
      await expect(sidebar).toBeFocused();
      await expect(page.locator('.app-main')).toHaveAttribute('inert', ''); // Tab stays out of the covered chat
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
        expect(await cutOff(page, '.chat-interface'), `answer and composer at ${width}px`).toEqual([]);
      }

      // Narrower than the tabs: they stay on one row and nothing else is pushed out
      await page.setViewportSize({ width: 320, height: 844 });
      const tabRows = await page.locator('.stage1 .tab').evaluateAll(tabs =>
        new Set(tabs.map(tab => Math.round(tab.getBoundingClientRect().top))).size);
      expect(tabRows, 'Stage 1 tabs wrapped into several rows at 320px').toBe(1);
      expect(await cutOff(page, '.chat-interface'), 'answer and composer at 320px').toEqual([]);

      // Mid-request at 360 px: Stop joins the action row instead of dropping onto a third one
      await page.setViewportSize({ width: 360, height: 844 });
      await page.route('**/message/stream', () => {}); // never answered: the request stays in flight
      await input.fill('A request that stays in flight');
      await send.click();
      await expect(page.locator('.stop-button')).toBeVisible();
      const actionRows = await page.locator('.attach-button, .stop-button').evaluateAll(buttons =>
        new Set(buttons.map(button => Math.round(button.getBoundingClientRect().top))).size);
      expect(actionRows, 'Stop left the action row at 360px').toBe(1);
      expect(await cutOff(page, '.chat-interface'), 'composer during a request at 360px').toEqual([]);
      await page.unrouteAll({ behavior: 'ignoreErrors' });

      await page.reload();
      await expect(toggle).toBeVisible();
      expect(await cutOff(page, '.chat-interface'), 'empty state at 360px').toEqual([]);
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
