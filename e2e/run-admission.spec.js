const { test, expect } = require('@playwright/test');
const { randomUUID } = require('node:crypto');
const api = `http://localhost:${process.env.E2E_BACKEND_PORT || '18765'}`;
const provider = `http://127.0.0.1:${process.env.E2E_PROVIDER_PORT || '18766'}`;

for (const endpoint of ['message', 'message/stream']) {
  test(`real HTTP ${endpoint}: replay never pays twice`, async ({ request }) => {
    const created = await request.post(`${api}/api/conversations`, {data: {
      models:['e2e-alpha:latest','e2e-beta:latest'],router_type:'openrouter',execution_mode:'chat_only',
    }});
    const {id} = await created.json();
    const data = {content:'Idempotent prompt '+randomUUID(),request_id:randomUUID()};
    const first = await request.post(`${api}/api/conversations/${id}/${endpoint}`,{data});
    expect(first.status()).toBe(200);
    const firstBody = await first.text();
    const before = (await (await request.get(`${provider}/__calls`)).json()).length;
    const second = await request.post(`${api}/api/conversations/${id}/${endpoint}`,{data});
    expect(second.status()).toBe(200);
    expect((await (await request.get(`${provider}/__calls`)).json()).length).toBe(before);
    const saved = await (await request.get(`${api}/api/conversations/${id}`)).json();
    expect(saved.messages).toHaveLength(2);
    if (endpoint==='message') {
      const body = JSON.parse(firstBody);
      expect(await second.json()).toEqual(body);
      expect(body.metadata.provider_usage.attempts).toBe(3); // two models + title
      expect(body.metadata.provider_usage.totals.total_tokens).toBe(90);
    } else {
      expect(await second.text()).toContain('"type": "complete"');
      expect(firstBody).toContain('provider_usage');
    }
    const conflict = await request.post(`${api}/api/conversations/${id}/${endpoint}`, {data:{...data,content:'changed'}});
    expect(conflict.status()).toBe(409);
    await request.delete(`${api}/api/conversations/${id}`);
  });
}

test('real HTTP rejects model count and duplicates before creating council', async ({request}) => {
  expect((await request.post(`${api}/api/conversations`,{data:{models:['a','b','c','d','e','f']}})).status()).toBe(422);
  expect((await request.post(`${api}/api/conversations`,{data:{models:['a','a']}})).status()).toBe(422);
});

test('real HTTP limits concurrent runs before history or provider calls', async ({request}) => {
  const ids=[];
  for(let i=0;i<3;i++) {
    const r=await request.post(`${api}/api/conversations`,{data:{models:['e2e-alpha:latest'],router_type:'openrouter',execution_mode:'chat_only'}});
    ids.push((await r.json()).id);
  }
  const marker='__SLOW_RUN__'+randomUUID();
  const first=request.post(`${api}/api/conversations/${ids[0]}/message`,{data:{content:marker+' A',request_id:randomUUID()}});
  const second=request.post(`${api}/api/conversations/${ids[1]}/message`,{data:{content:marker+' B',request_id:randomUUID()}});
  await expect.poll(async()=>{
    const calls=await(await request.get(`${provider}/__calls`)).json();
    return calls.filter(c=>JSON.stringify(c.messages).includes(marker)).length;
  }).toBeGreaterThanOrEqual(2);
  const busy=await request.post(`${api}/api/conversations/${ids[0]}/message`,{data:{content:'must not run'}});
  expect(busy.status()).toBe(409);
  const limited=await request.post(`${api}/api/conversations/${ids[2]}/message`,{data:{content:'must not run'}});
  expect(limited.status()).toBe(429);
  expect(limited.headers()['retry-after']).toBeDefined();
  expect((await(await request.get(`${api}/api/conversations/${ids[2]}`)).json()).messages).toHaveLength(0);
  expect((await first).status()).toBe(200);
  expect((await second).status()).toBe(200);
  for(const id of ids) await request.delete(`${api}/api/conversations/${id}`);
});
