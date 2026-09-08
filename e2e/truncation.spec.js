const { test, expect } = require('@playwright/test');

test('saved truncation needs explicit payment action; continuation cannot overwrite a switched conversation', async ({ page }) => {
  const source = { role: 'assistant', stage1: [{ model: 'anthropic/claude-fable-5.1', response: 'Original cut off', finish_reason: 'length', truncated: true }], stage2: [], stage3: null };
  const records = ['a', 'b'].map(id => ({ id, title: `Conversation ${id.toUpperCase()}`, created_at: '2026-09-08', messages: id === 'a' ? [{ role: 'user', content: 'Question' }, source] : [{ role: 'user', content: 'Other question' }], message_count: 2 }));
  let calls = 0;
  let release;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/continue')) {
      calls++;
      expect(route.request().postDataJSON()).toMatchObject({ message_index: 1, stage: 'stage1', model: 'anthropic/claude-fable-5.1' });
      expect(route.request().postDataJSON().request_id).toMatch(/^[a-f0-9-]{36}$/);
      await new Promise(resolve => { release = resolve; });
      records[0].messages.push({ role: 'assistant', stage1: [{ model: 'anthropic/claude-fable-5.1', response: 'Continued answer', finish_reason: 'stop' }], metadata: { continuation_of: { model: 'anthropic/claude-fable-5.1', message_index: 1, stage: 'stage1' } } });
      return route.fulfill({ json: {} });
    }
    let json = {};
    if (path === '/api/setup/status') json = { setup_required: false };
    if (path === '/api/auth/status') json = { auth_enabled: false };
    if (path === '/api/conversations') json = records;
    if (path.startsWith('/api/conversations/')) json = records.find(record => record.id === path.split('/')[3]);
    return route.fulfill({ json });
  });
  await page.goto('/');
  await page.getByText('Conversation A', { exact: true }).click();
  await expect(page.getByText('Response truncated by token limit')).toBeVisible();
  expect(calls).toBe(0);
  await page.reload();
  await page.getByText('Conversation A', { exact: true }).click();
  await expect(page.getByText('Response truncated by token limit')).toBeVisible();
  expect(calls).toBe(0);
  await page.getByRole('button', { name: 'Continue response (additional paid request)' }).click();
  await expect.poll(() => calls).toBe(1);
  await expect(page.getByText('Original cut off')).toBeVisible();
  await expect(page.getByRole('button', { name: /additional paid request/ })).toBeDisabled();
  await page.getByText('Conversation B', { exact: true }).click();
  release();
  await expect(page.locator('.message-input')).toBeEnabled();
  await expect(page.getByText('Other question')).toBeVisible();
  await expect(page.getByText('Continued answer', { exact: true })).toHaveCount(0);
  await page.getByText('Conversation A', { exact: true }).click();
  await expect(page.getByText('Continued answer', { exact: true })).toBeVisible();
  await expect(page.getByText('Original cut off')).toBeVisible();
  await expect(page.getByText(/Continuation from anthropic/)).toBeVisible();
  expect(calls).toBe(1);
});

for (const failure of ['network', 'ambiguous-502', 'failed', 'aborted']) {
  test(`continuation retries ${failure} only on explicit click with safe request id`, async ({ page }) => {
    const record = { id: 'retry', title: 'Retry conversation', messages: [{ role: 'assistant', stage1: [{ model: 'test/model', response: 'Partial original', truncated: true }] }], message_count: 1 };
    const ids = [];
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/continue')) {
        ids.push(route.request().postDataJSON().request_id);
        if (ids.length === 1) {
          if (failure === 'network') return route.abort('failed');
          if (failure === 'ambiguous-502') return route.fulfill({ status: 502, json: { detail: 'Upstream unavailable' } });
          return route.fulfill({ status: failure === 'failed' ? 502 : 409, json: { detail: { code: 'continuation_failed', message: 'Provider stopped', status: failure, run_id: 'run-1' } } });
        }
        return route.fulfill({ json: {} });
      }
      let json = {};
      if (path === '/api/setup/status') json = { setup_required: false };
      if (path === '/api/auth/status') json = { auth_enabled: false };
      if (path === '/api/conversations') json = [record];
      if (path === '/api/conversations/retry') json = record;
      return route.fulfill({ json });
    });
    await page.goto('/');
    await page.getByText('Retry conversation', { exact: true }).click();
    const button = page.getByRole('button', { name: /additional paid request/ });
    await button.click();
    await expect.poll(() => ids.length).toBe(1);
    await expect(button).toBeEnabled();
    if (failure === 'failed' || failure === 'aborted') await expect(page.getByText(/next click starts a new paid request/)).toBeVisible();
    expect(ids).toHaveLength(1);
    await button.click();
    await expect.poll(() => ids.length).toBe(2);
    if (failure === 'failed' || failure === 'aborted') expect(ids[1]).not.toBe(ids[0]);
    else expect(ids[1]).toBe(ids[0]);
  });
}
