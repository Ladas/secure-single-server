'use strict';
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const {X509Certificate,createHash}=require('node:crypto');
const assert=require('node:assert/strict');
let stage='setup';
(async()=>{
 if(process.env.MOCK_DEPLOYMENT_CONFIRMED!=='yes')throw new Error('mock confirmation required');
 const directory=process.env.KEY_DIRECTORY,base=process.env.GATEWAY_URL;
 const keyPath=path.join(directory,'admin.key');if(fs.statSync(keyPath).mode&0o077)throw new Error('private key file required');
 const cert=new X509Certificate(fs.readFileSync(path.join(directory,'server.pem')));
 const pin=createHash('sha256').update(cert.publicKey.export({type:'spki',format:'der'})).digest('base64');
 const browser=await chromium.launch({args:['--ignore-certificate-errors-spki-list='+pin]});
 try{
  const page=await browser.newPage();
  page.on('response',r=>{if(new URL(r.url()).pathname==='/api/v1/management/gateway/config')console.log('Gateway configuration HTTP '+r.status());});
  stage='login';await page.goto(base+'/login');await page.locator('#api_key').fill(fs.readFileSync(keyPath,'utf8').trim());
  await Promise.all([page.waitForURL(u=>u.pathname!=='/login'),page.getByRole('button',{name:'Sign In',exact:true}).click()]);
  await page.goto(base+'/management');
  stage='read gateway configuration';
  await page.waitForFunction(()=>document.querySelector('#gatewayState')?.textContent==='Active configuration loaded');
  const configured=await page.evaluate(async()=>(await(await fetch('/api/v1/management/gateway/config')).json()).configuration);
  assert.ok(configured.providers.length>0&&configured.providers.every(p=>p.name==='mock'&&Object.entries(p.urls).every(([api,url])=>url===(api==='openai'?'http://pricetag-provider:18080/v1':'http://pricetag-provider:18081'))),'mock-only destination required');
  stage='require provider removal control';
  assert.ok(await page.locator('#providerList').getByRole('button',{name:'Remove provider',exact:true}).count());
  stage='stage new provider';
  await page.locator('#provider [name=name]').fill('demo-provider');
  await page.locator('#provider [name=openai]').selectOption('http://pricetag-provider:18080');
  await page.locator('#provider [name=anthropic]').selectOption('http://pricetag-provider:18081');
  await page.locator('#provider [name=credential]').fill('synthetic-anthropic');
  await page.getByRole('button',{name:'Stage provider',exact:true}).click();
  assert.equal(await page.locator('#provider [name=credential]').inputValue(),'');
  stage='stage model alias';
  const form=page.locator('#gatewayModel');await form.locator('[name=id]').fill('demo-provider/fixture');await form.locator('[name=provider]').selectOption('demo-provider');
  await form.locator('[name=model]').fill('fixture-cheap');await form.locator('[name=context]').fill('32768');await form.locator('[name=output]').fill('2048');
  await form.locator('[name=anthropic]').check();await form.getByRole('button',{name:'Stage model',exact:true}).click();
  stage='activate model alias';await page.getByRole('button',{name:'Apply provider/model changes',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#gatewayState').textContent==='Configuration activated',{},{timeout:180000});
  stage='verify published alias';
  const ids=await page.evaluate(async()=>{const response=await fetch('/v1/models');return (await response.json()).data.map(m=>m.id)});
  assert.ok(ids.includes('demo-provider/fixture'));
  stage='verify configured limits and native inference';
  const results=await page.evaluate(async key=>{
   const catalog=await(await fetch('/v1/models')).json();
   const model=catalog.data.find(m=>m.id==='demo-provider/fixture');
   const statuses=[];
   for(const [path,body] of [['/v1/chat/completions',{messages:[{role:'user',content:'synthetic route check'}],max_completion_tokens:16}],['/v1/responses',{input:'synthetic route check',max_output_tokens:16}],['/v1/messages',{messages:[{role:'user',content:'synthetic route check'}],max_tokens:16}]]){
    const headers={'Content-Type':'application/json'};
    if(path==='/v1/messages'){headers['x-api-key']=key;headers['anthropic-version']='2023-06-01';}else headers.Authorization='Bearer '+key;
    const response=await fetch(path,{method:'POST',headers,body:JSON.stringify({...body,model:'demo-provider/fixture'})});statuses.push(response.status);
   }
   return {output:model.praxis.output,statuses};
  },fs.readFileSync(keyPath,'utf8').trim());
  assert.equal(results.output,2048);assert.deepEqual(results.statuses,[200,200,200]);
  stage='remove provider safely through UI';
  const providerRow=page.locator('#providerList p').filter({hasText:'demo-provider —'});
  assert.ok(await providerRow.getByRole('button',{name:'Remove provider',exact:true}).isDisabled());
  await page.locator('#gatewayModels p').filter({hasText:'demo-provider/fixture →'}).getByRole('button',{name:'Remove model',exact:true}).click();
  await providerRow.getByRole('button',{name:'Remove provider',exact:true}).click();
  await page.getByRole('button',{name:'Apply provider/model changes',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#gatewayState').textContent==='Configuration activated',null,{timeout:180000});
  const restored=await page.evaluate(async()=>(await(await fetch('/api/v1/management/gateway/config')).json()).configuration);
  assert.deepEqual(restored,configured);
  console.log('PASS: UI created a provider/model; all inference APIs worked; removal restored the original configuration');
 }finally{await browser.close()}
})().catch(()=>{console.error('FAIL at '+stage+'; sensitive response details withheld');process.exitCode=1});
