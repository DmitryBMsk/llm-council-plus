const {test,expect}=require('@playwright/test');
const base=`http://127.0.0.1:${process.env.E2E_BACKEND_PORT || '18765'}`;
const provider=`http://127.0.0.1:${process.env.E2E_PROVIDER_PORT || '18766'}`;

test('real stack retries one failed Stage 1 model with exactly one provider request',async({page,request})=>{
  const model='e2e-alpha:latest';
  // The fixture provider fails this model once per marker, so a Playwright retry needs a fresh one.
  const marker=`__FAIL_ONCE_${Date.now().toString(16)}__`;
  const created=await request.post(`${base}/api/conversations`,{data:{models:[model,'e2e-beta:latest'],chairman:'e2e-chair:latest',router_type:'openrouter',execution_mode:'chat_only'}});
  const {id}=await created.json();
  try {
    await page.goto('/');
    await page.locator('.conversation-item').first().click();
    await page.locator('textarea.message-input').fill(marker+' Explain a project');
    await page.getByRole('button',{name:'Send',exact:true}).click();
    await expect(page.locator('textarea.message-input')).toBeEnabled();
    await page.locator('.stage1 .tab').filter({hasText:model}).click();
    const retry=page.getByRole('button',{name:'Retry model (additional paid request)',exact:true});
    await expect(retry).toBeEnabled();
    const source=await(await request.get(`${base}/api/conversations/${id}`)).json();
    expect(source.messages).toHaveLength(2);
    expect(source.messages[1].stage1.find(r=>r.model===model).error).toBe(true);
    const before=(await(await request.get(`${provider}/__calls`)).json()).length;
    await retry.click();
    await expect(page.getByText(`Retry of ${model}. Other models, rankings and synthesis were not rerun.`,{exact:true})).toBeVisible();
    const saved=await(await request.get(`${base}/api/conversations/${id}`)).json();
    expect(saved.messages).toHaveLength(4);
    expect(saved.messages[1]).toEqual(source.messages[1]);
    const retried=saved.messages[3];
    expect(retried.stage1).toHaveLength(1);
    expect(retried.stage1[0].model).toBe(model);
    expect(retried.stage1[0].response).toBe('E2E_ANSWER_42: deterministic council response.');
    expect(retried.metadata.retry_of).toEqual({message_index:1,stage:'stage1',model});
    expect(retried.metadata.provider_usage.attempts).toBe(1);
    const calls=await(await request.get(`${provider}/__calls`)).json();
    expect(calls).toHaveLength(before+1);
    expect(calls.at(-1).model).toBe(model);
    expect(JSON.stringify(calls.at(-1).messages)).toContain(marker);
  } finally { await request.delete(`${base}/api/conversations/${id}`).catch(()=>{}); }
});
