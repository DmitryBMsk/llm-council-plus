const { test, expect } = require('@playwright/test');

// Real browser/UI; API responses are controlled to reproduce network ordering.
async function mockConversations(page) {
  const records = ['a', 'b'].map(id => ({ id, title: `Conversation ${id.toUpperCase()}`, created_at: '2026-09-08', messages: [{ role: 'user', content: `Content ${id.toUpperCase()}` }], message_count: 1 }));
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    let body = {};
    if (path === '/api/setup/status') body = { setup_required: false };
    if (path === '/api/auth/status') body = { auth_enabled: false };
    if (path === '/api/conversations') body = records;
    if (path.startsWith('/api/conversations/')) body = records.find(c => c.id === path.split('/')[3]);
    return route.fulfill({ json: body || {} });
  });
  return records;
}

test('stale A response cannot replace selected B or allow an early send', async ({ page }) => {
  const records = await mockConversations(page);
  let finishA;
  await page.route('**/api/conversations/a', route => new Promise(resolve => {
    finishA = async () => { await route.fulfill({ json: records[0] }); resolve(); };
  }));
  await page.goto('/');
  await page.getByText('Conversation A', { exact: true }).click();
  await expect.poll(() => Boolean(finishA)).toBe(true);
  await expect(page.locator('.message-input')).toHaveCount(0);
  await page.getByText('Conversation B', { exact: true }).click();
  await expect(page.getByText('Content B', { exact: true })).toBeVisible();
  await finishA();
  await expect(page.getByText('Content A', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Content B', { exact: true })).toBeVisible();
});

test('drafts and delayed attachments stay with their originating conversation', async ({ page }) => {
  await mockConversations(page);
  let finishUpload;
  await page.route('**/api/upload', route => new Promise(resolve => {
    finishUpload = async () => { await route.fulfill({ json: { filename: 'draft-a.txt', content: 'attachment A', char_count: 12, file_type: 'text' } }); resolve(); };
  }));
  await page.goto('/');
  await page.getByText('Conversation A', { exact: true }).click();
  await page.locator('.message-input').fill('Draft A');
  await page.locator('input[type=file]').setInputFiles({ name: 'draft-a.txt', mimeType: 'text/plain', buffer: Buffer.from('attachment A') });
  await expect.poll(() => Boolean(finishUpload)).toBe(true);
  await page.getByText('Conversation B', { exact: true }).click();
  await expect(page.locator('.message-input')).toBeEnabled();
  await expect(page.locator('.message-input')).toHaveValue('');
  await page.locator('.message-input').fill('Draft B');
  await finishUpload();
  await expect(page.locator('.attachment-name')).toHaveCount(0);
  await page.getByText('Conversation A', { exact: true }).click();
  await expect(page.locator('.message-input')).toHaveValue('Draft A');
  await expect(page.locator('.attachment-name')).toHaveText('draft-a.txt');
  await page.getByText('Conversation B', { exact: true }).click();
  await expect(page.locator('.message-input')).toHaveValue('Draft B');
  await expect(page.locator('.attachment-name')).toHaveCount(0);
});
