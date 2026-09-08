const { test, expect } = require('@playwright/test');
const apiBase = `http://localhost:${process.env.E2E_BACKEND_PORT || '18765'}`;
const providerBase = `http://127.0.0.1:${process.env.E2E_PROVIDER_PORT || '18766'}`;

for (const failure of [false, true]) {
  test(`Tavily ${failure ? '400 stays failure' : 'sources reach model'} through browser and reload`, async ({ page, request }) => {
    const response = await request.post(`${apiBase}/api/conversations`, { data: {
      models: ['e2e-alpha:latest'], chairman: 'e2e-chair:latest', execution_mode: 'chat_only', router_type: 'ollama',
    } });
    const { id } = await response.json();
    await page.goto('/');
    await page.locator('.conversation-item').first().click();
    await page.locator('textarea.message-input').fill(`latest research ${failure ? '__TAVILY_FAIL__' : '__TAVILY_OK__'}`);
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await expect(page.getByText('E2E_ANSWER_42: deterministic council response.', { exact: true }).first()).toBeVisible();
    const saved = await (await request.get(`${apiBase}/api/conversations/${id}`)).json();
    const output = saved.messages[1].metadata.tool_outputs[0];
    expect(output.status).toBe(failure ? 'error' : 'success');
    const calls = await (await request.get(`${providerBase}/__calls`)).json();
    const call = calls.findLast(c => c.messages.some(m => String(m.content).includes(failure ? '__TAVILY_FAIL__' : '__TAVILY_OK__')) &&
      c.messages.some(m => String(m.content).includes(failure ? 'Search unavailable' : 'SEARCH_EVIDENCE_42')));
    expect(call).toBeTruthy();
    if (failure) expect(JSON.stringify(call)).not.toContain('Invalid fixture query');
    await page.reload();
    await page.locator('.conversation-item').first().click();
    if (failure) {
      await expect(page.getByRole('status')).toContainText('Tavily: Search unavailable (HTTP 400)');
      await expect(page.getByText('0 sources', { exact: true })).toBeVisible();
    } else {
      await page.getByRole('button', { name: /Search context/ }).click();
      await expect(page.getByRole('link', { name: 'Tavily fixture source' })).toHaveAttribute('href', 'https://example.com/tavily-source');
    }
  });
}
