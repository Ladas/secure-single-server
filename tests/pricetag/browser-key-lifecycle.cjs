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
  const {page:admin}=await login(fs.readFileSync(keyPath,'utf8').trim());await admin.goto(base+'/management');await admin.locator('#admin').waitFor({state:'visible'});
  const config=await admin.evaluate(async()=>(await(await fetch('/api/v1/management/gateway/config')).json()).configuration);
  assert.ok(config.providers.length&&config.providers.every(p=>p.name==='mock'&&Object.entries(p.urls).every(([api,url])=>url===(api==='openai'?'http://pricetag-provider:18080/v1':'http://pricetag-provider:18081'))));
  const subject='demo-lifecycle-'+Date.now();stage='UI onboarding';
  await admin.locator('#user [name=subject]').fill(subject);await admin.locator('#user [name=name]').fill('Key lifecycle verification');await done(admin,()=>admin.locator('#user button').click());
  await admin.locator('#onboard [name=subject]').selectOption(subject);await admin.locator('#onboard [name=expiresIn]').fill('1d');await done(admin,()=>admin.getByRole('button',{name:'Issue key',exact:true}).click());
  const issued=JSON.parse(await admin.locator('#onboardKey').textContent());await admin.getByRole('button',{name:'Clear displayed key',exact:true}).click();
  const {page:user}=await login(issued.key);await user.goto(base+'/management');
  async function create(name,lifetime){await user.locator('#key [name=name]').fill(name);await user.locator('#key [name=expiresIn]').fill(lifetime);await done(user,()=>user.locator('#key button').click());return JSON.parse(await user.locator('#newKey').textContent());}
  async function infer(key){return await user.evaluate(async key=>{const r=await fetch('/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},body:JSON.stringify({model:'mock/demo-cheap',messages:[{role:'user',content:'synthetic key test'}],max_completion_tokens:16})});await r.text();return r.status;},key);}
  stage='own key revocation';const own=await create('revoke-test','1h');assert.equal(await infer(own.key),200);
  await done(user,()=>user.getByRole('button',{name:'List my keys',exact:true}).click());await done(user,()=>user.locator('#keys p').filter({hasText:own.id}).getByRole('button',{name:'Revoke',exact:true}).click());
  assert.equal(await infer(own.key),401);
  stage='cross-user revocation denied';
  const adminKeys=await admin.evaluate(async()=>(await(await fetch('/me/keys')).json()).data);assert.ok(adminKeys.length);
  const cross=await user.evaluate(async id=>(await fetch('/me/keys/'+encodeURIComponent(id),{method:'DELETE'})).status,adminKeys[0].id);assert.ok([403,404].includes(cross));
  stage='finite key expiry';const short=await create('expiry-test','10s');assert.equal(await infer(short.key),200);await new Promise(r=>setTimeout(r,12000));assert.equal(await infer(short.key),401);
  stage='maximum lifetime enforced';await user.locator('#key [name=expiresIn]').fill('9999d');const rejected=user.waitForResponse(r=>new URL(r.url()).pathname==='/me/keys'&&r.request().method()==='POST');await user.locator('#key button').click();assert.equal((await rejected).status(),400);
  stage='replacement key preserves access';const replacement=await create('replacement','1h');assert.equal(await infer(replacement.key),200);
  console.log('PASS: UI-created keys revoke and expire; cross-user revocation rejected; excessive lifetime rejected; replacement works');
 }finally{await browser.close();}
})().catch(()=>{console.error('FAIL at '+stage+'; sensitive details withheld');process.exitCode=1});
