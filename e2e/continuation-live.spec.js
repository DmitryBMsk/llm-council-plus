const {test,expect}=require('@playwright/test');
const base=`http://127.0.0.1:${process.env.E2E_BACKEND_PORT || '18765'}`;
const provider=`http://127.0.0.1:${process.env.E2E_PROVIDER_PORT || '18766'}`;

test('real stack persists finish reason, budgets and explicitly continues one model',async({page,request})=>{
  const original=await(await request.get(`${base}/api/settings`)).json();
  const model='e2e-alpha:latest';
  let cid;
  try {
    await page.goto('/');
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.getByRole('button',{name:'Generation limits',exact:true}).click();
    await page.getByLabel('stage1 output limit',{exact:true}).fill('128');
    await page.getByLabel('continuation output limit',{exact:true}).fill('256');
    await page.getByLabel('Model generation overrides',{exact:true}).fill(JSON.stringify({[model]:{continuation:{max_tokens:384,reasoning_effort:'low'}}}));
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await expect(page.getByText('Saved!',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Close settings'}).click();
    const response=await request.post(`${base}/api/conversations`,{data:{models:[model,'e2e-beta:latest'],chairman:'e2e-chair:latest',router_type:'openrouter',execution_mode:'chat_only'}});
    expect(response.status()).toBe(200);
    cid=(await response.json()).id;
    const title='Truncation '+cid;
    await request.patch(`${base}/api/conversations/${cid}/title`,{data:{title}});
    await page.reload();
    await page.getByText(title,{exact:true}).click();
    await page.locator('textarea.message-input').fill('__TRUNCATE_TEST__ Explain a project');
    await page.getByRole('button',{name:'Send',exact:true}).click();
    await expect(page.locator('textarea.message-input')).toBeEnabled();
    await page.locator('.stage1 .tab').filter({hasText:'e2e-alpha:latest'}).click();
    await expect(page.getByText('Response truncated by token limit',{exact:true})).toBeVisible();
    let saved=await(await request.get(`${base}/api/conversations/${cid}`)).json();
    const source=structuredClone(saved.messages[1]);
    const record=source.stage1.find(r=>r.model===model);
    expect(record.finish_reason).toBe('length');
    expect(record.native_finish_reason).toBe('max_tokens');
    expect(record.generation_id).toMatch(/^gen-fixture-/);
    expect(record.effective_max_tokens).toBe(128);
    const before=(await(await request.get(`${provider}/__calls`)).json()).length;
    // First-message title generation may replace the initial test title.
    await request.patch(`${base}/api/conversations/${cid}/title`,{data:{title}});
    await page.reload();
    await page.getByText(title,{exact:true}).click();
    await page.locator('.stage1 .tab').filter({hasText:'e2e-alpha:latest'}).click();
    await expect(page.getByText('Response truncated by token limit',{exact:true})).toBeVisible();
    expect((await(await request.get(`${provider}/__calls`)).json()).length).toBe(before);
    const sent=page.waitForRequest(r=>r.url().endsWith('/continue'));
    await page.getByRole('button',{name:'Continue response (additional paid request)',exact:true}).click();
    const payload=(await sent).postDataJSON();
    await expect(page.getByText('TRUNCATED_PREFIX: continuation completed.',{exact:true})).toBeVisible();
    saved=await(await request.get(`${base}/api/conversations/${cid}`)).json();
    expect(saved.messages).toHaveLength(4);
    expect(saved.messages[1]).toEqual(source);
    const continuation=saved.messages[3];
    expect(continuation.stage1).toHaveLength(1);
    expect(continuation.stage1[0].finish_reason).toBe('stop');
    expect(continuation.metadata.provider_usage.attempts).toBe(1);
    expect(continuation.metadata.continuation_of.model).toBe(model);
    const calls=await(await request.get(`${provider}/__calls`)).json();
    expect(calls).toHaveLength(before+1);
    expect(calls.at(-1).model).toBe(model);
    expect(calls.at(-1).max_tokens).toBe(384);
    expect(calls.at(-1).reasoning.effort).toBe('low');
    const replay=await request.post(`${base}/api/conversations/${cid}/continue`,{data:payload});
    expect(replay.status()).toBe(200);
    expect((await(await request.get(`${provider}/__calls`)).json()).length).toBe(before+1);
  } finally {
    if(cid) await request.delete(`${base}/api/conversations/${cid}`).catch(()=>{});
    await request.post(`${base}/api/settings/import`,{data:original}).catch(()=>{});
  }
});

for(const [stage,mode,marker] of [['stage2','chat_ranking','__EMPTY_STAGE2__'],['stage3','full','__CUT_STAGE3__']]) {
  test(`real stack continues ${stage} without rerunning other stages`,async({page,request})=>{
    const created=await request.post(`${base}/api/conversations`,{data:{models:['e2e-alpha:latest','e2e-beta:latest'],chairman:'e2e-chair:latest',router_type:'openrouter',execution_mode:mode}});
    const {id}=await created.json();
    try {
      await page.goto('/');
      await page.locator('.conversation-item').first().click();
      await page.locator('textarea.message-input').fill(marker+' Explain a project');
      await page.getByRole('button',{name:'Send',exact:true}).click();
      await expect(page.locator('textarea.message-input')).toBeEnabled();
      if(stage==='stage2') await page.locator('.stage2 .tab').filter({hasText:'e2e-alpha:latest'}).click();
      const source=await(await request.get(`${base}/api/conversations/${id}`)).json();
      const before=(await(await request.get(`${provider}/__calls`)).json()).length;
      const block=page.locator('.'+stage);
      await expect(block.getByText('Response truncated by token limit',{exact:true})).toBeVisible();
      await block.getByRole('button',{name:'Continue response (additional paid request)',exact:true}).click();
      await expect.poll(async()=> (await(await request.get(`${base}/api/conversations/${id}`)).json()).messages.length).toBe(4);
      const saved=await(await request.get(`${base}/api/conversations/${id}`)).json();
      expect(saved.messages[1]).toEqual(source.messages[1]);
      const fresh=saved.messages[3][stage];
      const result=Array.isArray(fresh)?fresh[0]:fresh;
      expect(result.truncated).toBe(false);
      if(stage==='stage2') expect(result.parsed_ranking).toEqual(['Response A','Response B']);
      else expect(result.response).toBe('FINAL_PREFIX: final continuation.');
      expect((await(await request.get(`${provider}/__calls`)).json()).length).toBe(before+1);
    } finally { await request.delete(`${base}/api/conversations/${id}`).catch(()=>{}); }
  });
}
