const {test,expect}=require('@playwright/test');
const {randomUUID}=require('node:crypto');
const base=`http://127.0.0.1:${process.env.E2E_BACKEND_PORT || '18765'}`;

test('real API accepts exact 20 MiB image through message body cap and rejects one byte over',async({request})=>{
  const bytes=Buffer.alloc(20*1024*1024);
  Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ioAAAAASUVORK5CYII=','base64').copy(bytes);
  const upload=await request.post(`${base}/api/upload`,{multipart:{file:{name:'exact.png',mimeType:'image/png',buffer:bytes}}});
  expect(upload.status()).toBe(200);
  const attachment=await upload.json();
  expect(attachment.byte_size).toBe(bytes.length);
  const over=await request.post(`${base}/api/upload`,{multipart:{file:{name:'over.png',mimeType:'image/png',buffer:Buffer.alloc(bytes.length+1)}}});
  expect(over.status()).toBe(400);
  const created=await request.post(`${base}/api/conversations`,{data:{models:['e2e-alpha:latest'],router_type:'openrouter',execution_mode:'chat_only'}});
  const {id}=await created.json();
  try {
    const sent=await request.post(`${base}/api/conversations/${id}/message`,{data:{content:'Describe this image',attachments:[attachment],request_id:randomUUID()}});
    expect(sent.status()).toBe(200);
    const saved=await(await request.get(`${base}/api/conversations/${id}`)).json();
    expect(saved.messages).toHaveLength(2);
    expect(saved.messages[0].attachments[0].byte_size).toBe(bytes.length);
    expect(saved.messages[0].attachments[0].content).toBeUndefined();
  } finally {await request.delete(`${base}/api/conversations/${id}`);}
});
