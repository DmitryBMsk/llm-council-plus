const { test, expect } = require('@playwright/test');
const apiBase = `http://localhost:${process.env.E2E_BACKEND_PORT || '18765'}`;
const providerBase = `http://127.0.0.1:${process.env.E2E_PROVIDER_PORT || '18766'}`;

for (const [router, mode] of ['ollama', 'openrouter'].flatMap(router =>
  ['chat_only', 'chat_ranking', 'full'].map(mode => [router, mode]))) {
  test(`real browser + API + local provider: ${router}/${mode}, reload, follow-up`, async ({ page, request }) => {
    // Create via HTTP so each scenario starts with known model/mode settings;
    // messages travel through the real browser SSE client and real backend.
    const response = await request.post(`${apiBase}/api/conversations`, { data: {
      models: ['e2e-alpha:latest', 'e2e-beta:latest'],
      chairman: 'e2e-chair:latest', execution_mode: mode, router_type: router,
      system_prompt: 'E2E_SYSTEM_POLICY',
    } });
    expect(response.ok()).toBeTruthy();
    const conversation = await response.json();
    await page.goto('/');
    await page.locator('.conversation-item').first().click();
    const input = page.locator('textarea.message-input');
    await input.fill(`Explain council agreement ${router} ${mode}`);
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await expect(input).toBeEnabled();
    await expect(page.getByText('E2E_ANSWER_42: deterministic council response.', { exact: true }).first()).toBeVisible();
    const saved = await (await request.get(`${apiBase}/api/conversations/${conversation.id}`)).json();
    expect(saved.messages).toHaveLength(2);
    expect(saved.messages[1].stage1).toHaveLength(2);
    expect(Boolean(saved.messages[1].stage2?.length)).toBe(mode !== 'chat_only');
    expect(Boolean(saved.messages[1].stage3?.response)).toBe(mode === 'full');
    await page.reload();
    await page.locator('.conversation-item').first().click();
    await expect(page.getByText('E2E_ANSWER_42: deterministic council response.', { exact: true }).first()).toBeVisible();
    await input.fill(`Clarify the previous answer ${router} ${mode}`);
    await page.getByRole('button', { name: 'Send follow-up', exact: true }).click();
    await expect(input).toBeEnabled();
    await expect.poll(async () => {
      const item = await (await request.get(`${apiBase}/api/conversations/${conversation.id}`)).json();
      return item.messages.length;
    }).toBe(4);
    const calls = await (await request.get(`${providerBase}/__calls`)).json();
    const followups = calls.filter(call => call.messages.some(message =>
      String(message.content).includes(`Current follow-up question: Clarify the previous answer ${router} ${mode}`)));
    expect(followups).toHaveLength(2);
    for (const call of followups) {
      expect(call.messages[0]).toEqual({ role: 'system', content: 'E2E_SYSTEM_POLICY' });
      expect(call.messages.some(message => String(message.content).includes('E2E_ANSWER_42'))).toBeTruthy();
    }
  });
}

test('browser creates a council with Ollama selection', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '+ New Conversation', exact: true }).click();
  await page.locator('select').filter({ has: page.locator('option[value="ollama"]') }).selectOption('ollama');
  await expect(page.getByText('e2e-alpha:latest', { exact: true }).first()).toBeVisible();
  await page.locator('select').filter({ has: page.locator('option[value="chat_only"]') }).selectOption('chat_only');
  await page.getByRole('button', { name: /Start.*Council|Create.*Council|Start Conversation/ }).click();
  await expect(page.locator('textarea.message-input')).toBeEnabled();
});
