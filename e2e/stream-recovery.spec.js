const { test, expect } = require('@playwright/test');

// Real browser/UI with fault injection at HTTP boundary; no paid model calls.
for (const failure of ['eof', 'server-error', 'malformed']) {
  test(`partial answer survives ${failure}, navigation and a subsequent successful request`, async ({ page }) => {
    const records = ['a', 'b'].map(id => ({ id, title: `Conversation ${id.toUpperCase()}`, created_at: '2026-09-08', messages: [], message_count: 0 }));
    let sends = 0;
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/message/stream')) {
        sends++;
        let body = 'data: {"type":"stage1_start"}\n\n';
        body += 'data: {"type":"stage1_model_response","data":{"model":"test/model","response":"Partial answer survives"}}\n\n';
        if (sends > 1) body += 'data: {"type":"stage1_complete","data":[{"model":"test/model","response":"Recovered answer"}]}\n\ndata: {"type":"complete"}\n\n';
        else if (failure === 'server-error') body += 'data: {"type":"error","message":"Provider unavailable"}\n\n';
        else if (failure === 'malformed') body += 'data: malformed\n\n';
        return route.fulfill({ contentType: 'text/event-stream', body });
      }
      let json = {};
      if (path === '/api/setup/status') json = { setup_required: false };
      if (path === '/api/auth/status') json = { auth_enabled: false };
      if (path === '/api/conversations') json = records;
      if (path.startsWith('/api/conversations/')) json = records.find(c => c.id === path.split('/')[3]);
      return route.fulfill({ json: json || {} });
    });
    await page.goto('/');
    await page.getByText('Conversation A', { exact: true }).click();
    await page.locator('.message-input').fill('Question');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await expect(page.getByText('Partial answer survives', { exact: true })).toBeVisible();
    await expect(page.locator('.stream-status')).toContainText('Response interrupted');
    await expect(page.locator('.message-input')).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0);
    await expect(page.locator('.stage-loading')).toHaveCount(0);
    expect(sends).toBe(1); // No silent retries of a possibly accepted request.
    await page.getByText('Conversation B', { exact: true }).click();
    await page.getByText('Conversation A', { exact: true }).click();
    await expect(page.getByText('Partial answer survives', { exact: true })).toBeVisible();
    await page.locator('.message-input').fill('Explicit next request');
    await page.getByRole('button', { name: 'Send follow-up', exact: true }).click();
    await expect(page.getByText('Recovered answer', { exact: true })).toBeVisible();
    await expect(page.locator('.message-input')).toBeEnabled();
    expect(sends).toBe(2);
  });
}
