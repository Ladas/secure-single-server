'use strict';
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const {X509Certificate,createHash}=require('node:crypto');
const assert=require('node:assert/strict');
let stage='setup';
(async()=>{
 if(process.env.MOCK_DEPLOYMENT_CONFIRMED!=='yes')throw new Error('mock confirmation required');
 const dir=process.env.KEY_DIRECTORY,base=process.env.GATEWAY_URL;
 const keyPath=path.join(dir,'admin.key');assert.equal(fs.statSync(keyPath).mode&0o077,0);
 const cert=new X509Certificate(fs.readFileSync(path.join(dir,'server.pem')));
 const pin=createHash('sha256').update(cert.publicKey.export({type:'spki',format:'der'})).digest('base64');
 const browser=await chromium.launch({args:['--ignore-certificate-errors-spki-list='+pin]});
 async function login(key){const context=await browser.newContext();const page=await context.newPage();await page.goto(base+'/login');await page.locator('#api_key').fill(key);await Promise.all([page.waitForURL(u=>u.pathname!=='/login'),page.getByRole('button',{name:'Sign In',exact:true}).click()]);return {context,page};}
 async function done(page,action){await page.locator('#status').evaluate(el=>el.textContent='');await action();await page.waitForFunction(()=>document.querySelector('#status').textContent==='Done');}
 try{
  const key=fs.readFileSync(keyPath,'utf8').trim();const {page}=await login(key);await page.goto(base+'/management');await page.waitForFunction(()=>document.querySelector('#gatewayState')?.textContent==='Active configuration loaded');
  const original=await page.evaluate(async()=>await(await fetch('/api/v1/management/gateway/config')).json());
  assert.ok(original.configuration.providers.length&&original.configuration.providers.every(p=>p.name==='mock'&&Object.entries(p.urls).every(([api,url])=>url===(api==='openai'?'http://pricetag-provider:18080/v1':'http://pricetag-provider:18081'))));
  stage='stage bounded model change';
  const model=original.configuration.models.find(m=>m.id==='mock/demo-cheap');assert.ok(model);
  const row=page.locator('#gatewayModels p').filter({hasText:'mock/demo-cheap →'});await row.getByRole('button',{name:'Edit model',exact:true}).click();
  await page.locator('#gatewayModel [name=output]').fill(String(model.output-1));await done(page,()=>page.getByRole('button',{name:'Stage model',exact:true}).click());
  stage='activate with armed one-shot start fault';await page.getByRole('button',{name:'Apply provider/model changes',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.startsWith('Activation failed'),null,{timeout:180000});
  stage='verify rollback';
  const current=await page.evaluate(async()=>await(await fetch('/api/v1/management/gateway/config')).json());assert.equal(current.revision,original.revision);assert.deepEqual(current.configuration,original.configuration);
  const results=await page.evaluate(async key=>{
   const catalog=await(await fetch('/v1/models')).json();const model=catalog.data.find(m=>m.id==='mock/demo-cheap');
   const body=JSON.stringify({model:'mock/demo-cheap',messages:[{role:'user',content:'rollback verification'}],max_completion_tokens:16});
   const response=await fetch('/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body});await response.text();
   const anonymous=await fetch('/v1/responses',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
   return {output:model.praxis.output,inference:response.status,anonymous:anonymous.status};
  },key);
  assert.equal(results.output,model.output);assert.equal(results.inference,200);assert.equal(results.anonymous,401);
  console.log('PASS: failed gateway start rolled back configuration/catalog; authenticated inference works and anonymous inference remains denied');
 }finally{await browser.close();}
})().catch(()=>{console.error('FAIL at '+stage+'; sensitive details withheld');process.exitCode=1});
