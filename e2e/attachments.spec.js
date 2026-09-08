const { test, expect } = require('@playwright/test');
const backend = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || 18765}`;
const provider = `http://127.0.0.1:${process.env.E2E_PROVIDER_PORT || 18766}`;
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ioAAAAASUVORK5CYII=', 'base64');

test('real upload/send/reload/download/followup preserves document and image context', async ({ page, request }) => {
  const created = await request.post(`${backend}/api/conversations`, { data: {
    router_type: 'openrouter', execution_mode: 'chat_only',
    models: ['e2e-alpha:latest', 'e2e-beta:latest'], chairman: 'e2e-chair:latest',
  } });
  expect(created.ok()).toBeTruthy();
  const conversation = await created.json();
  const title = `Attachment lifecycle ${conversation.id}`;
  await request.patch(`${backend}/api/conversations/${conversation.id}/title`, { data: { title } });
  try {
    await page.goto('/');
    await page.getByText(title, { exact: true }).click();
    await page.locator('input[type=file]').setInputFiles([
      { name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('DOCUMENT_UNIQUE_6849') },
      { name: 'pixel.png', mimeType: 'image/png', buffer: png },
    ]);
    await expect(page.locator('.attachment-name')).toHaveCount(2);
    await page.locator('.message-input').fill('Read both attachments');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Download image', exact: true })).toBeVisible();
    const saved = await (await request.get(`${backend}/api/conversations/${conversation.id}`)).json();
    expect(saved.messages[0].attachments).toHaveLength(2);
    const text = saved.messages[0].attachments.find(a => a.file_type !== 'image');
    const image = saved.messages[0].attachments.find(a => a.file_type === 'image');
    expect(image.content).toBeUndefined();
    expect(text.content).toBe('DOCUMENT_UNIQUE_6849');
    const downloaded = await request.get(`${backend}/api/conversations/${conversation.id}/attachments/${image.id}`);
    expect(await downloaded.body()).toEqual(png);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download extracted text', exact: true }).click();
    expect((await downloadPromise).suggestedFilename()).toBe('brief.txt.extracted.txt');
    await page.reload();
    await page.getByText(saved.title, { exact: true }).first().click();
    await expect(page.getByRole('button', { name: 'Download image', exact: true })).toBeVisible();
    const priorCalls = await (await request.get(`${provider}/__calls`)).json();
    await page.locator('.message-input').fill('FOLLOWUP_ATTACHMENT_6849 describe both again');
    await page.getByRole('button', { name: 'Send follow-up', exact: true }).click();
    await expect(page.locator('.message-input')).toBeEnabled();
    const calls = (await (await request.get(`${provider}/__calls`)).json()).slice(priorCalls.length);
    const followups = calls.filter(call => JSON.stringify(call.messages).includes('FOLLOWUP_ATTACHMENT_6849'));
    expect(followups.length).toBeGreaterThan(0);
    for (const call of followups) {
      expect(JSON.stringify(call.messages)).toContain('DOCUMENT_UNIQUE_6849');
      expect(JSON.stringify(call.messages)).toContain(png.toString('base64'));
    }
  } finally {
    await request.delete(`${backend}/api/conversations/${conversation.id}`);
  }
});

test('Ollama rejects images in UI and both APIs before saving a message', async ({ page, request }) => {
  const conversation = await (await request.post(`${backend}/api/conversations`, { data: { router_type: 'ollama', execution_mode: 'chat_only' } })).json();
  const title = `Ollama image rejection ${conversation.id}`;
  await request.patch(`${backend}/api/conversations/${conversation.id}/title`, { data: { title } });
  try {
    await page.goto('/');
    await page.getByText(title, { exact: true }).click();
    await page.locator('input[type=file]').setInputFiles({ name: 'pixel.png', mimeType: 'image/png', buffer: png });
    await expect(page.getByText('Ollama images are not supported. Select OpenRouter or attach a text document.', { exact: true })).toBeVisible();
    await expect(page.locator('.attachment-name')).toHaveCount(0);
    for (const suffix of ['message', 'message/stream']) {
      const result = await request.post(`${backend}/api/conversations/${conversation.id}/${suffix}`, { data: {
        content: 'Image', attachments: [{ filename: 'pixel.png', file_type: 'image', content: `data:image/png;base64,${png.toString('base64')}` }],
      } });
      expect(result.status()).toBe(400);
    }
    expect((await (await request.get(`${backend}/api/conversations/${conversation.id}`)).json()).messages).toEqual([]);
  } finally {
    await request.delete(`${backend}/api/conversations/${conversation.id}`);
  }
});
