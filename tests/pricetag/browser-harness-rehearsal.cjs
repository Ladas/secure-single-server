'use strict';
// Coordinate UI changes with a separately running, interactive harness.
// Run setup, use the issued key, deny, allow, then restore (also after failure).
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path');
const {X509Certificate,createHash}=require('node:crypto');
const assert=require('node:assert/strict');
let stage='setup';
(async()=>{
 const action=process.env.REHEARSAL_ACTION;
 assert.ok(['setup','deny','allow','restore'].includes(action));
 assert.equal(process.env.MOCK_DEPLOYMENT_CONFIRMED,'yes');
 const dir=process.env.KEY_DIRECTORY,base=process.env.GATEWAY_URL;
 const statePath=path.join(dir,'harness-rehearsal.json'),keyPath=path.join(dir,'harness-rehearsal.key');
 const adminPath=path.join(dir,'admin.key');assert.equal(fs.lstatSync(adminPath).mode&0o077,0);
 const cert=new X509Certificate(fs.readFileSync(path.join(dir,'server.pem')));
 const pin=createHash('sha256').update(cert.publicKey.export({type:'spki',format:'der'})).digest('base64');
 const browser=await chromium.launch({args:['--ignore-certificate-errors-spki-list='+pin]});
 async function login(key){const page=await(await browser.newContext()).newPage();await page.goto(base+'/login');await page.locator('#api_key').fill(key);await Promise.all([page.waitForURL(u=>u.pathname!=='/login'),page.getByRole('button',{name:'Sign In',exact:true}).click()]);return page;}
 async function done(page,action){await page.locator('#status').evaluate(el=>el.textContent='');await action();await page.waitForFunction(()=>document.querySelector('#status').textContent==='Done');}
 try{
  const admin=await login(fs.readFileSync(adminPath,'utf8').trim());await admin.goto(base+'/management');await admin.locator('#admin').waitFor({state:'visible'});
  const config=await admin.evaluate(async()=>(await(await fetch('/api/v1/management/gateway/config')).json()).configuration);
  assert.ok(config.providers.length&&config.providers.every(p=>p.name==='mock'&&Object.entries(p.urls).every(([api,url])=>url===(api==='openai'?'http://pricetag-provider:18080/v1':'http://pricetag-provider:18081'))));
  let state;
  if(action==='setup'){
   assert.ok(!fs.existsSync(statePath)&&!fs.existsSync(keyPath),'use a fresh private directory');
   state={subject:'demo-harness-'+Date.now(),policy:await admin.evaluate(async()=>await(await fetch('/api/v1/admin/safety-net')).json())};
   fs.writeFileSync(statePath,JSON.stringify(state),{mode:0o600,flag:'wx'});
   stage='onboard user through UI';await admin.locator('#user [name=subject]').fill(state.subject);await admin.locator('#user [name=name]').fill('Interactive harness rehearsal');await done(admin,()=>admin.locator('#user button').click());
   await admin.locator('#budget [name=subject]').selectOption(state.subject);await admin.locator('#budget [name=monthly_usd]').fill('5');await done(admin,()=>admin.getByRole('button',{name:'Set override',exact:true}).click());
   await admin.locator('#onboard [name=subject]').selectOption(state.subject);await admin.locator('#onboard [name=expiresIn]').fill('1h');await done(admin,()=>admin.getByRole('button',{name:'Issue key',exact:true}).click());
   const issued=JSON.parse(await admin.locator('#onboardKey').textContent());fs.writeFileSync(keyPath,issued.key+'\n',{mode:0o600,flag:'wx'});await admin.getByRole('button',{name:'Clear displayed key',exact:true}).click();
   console.log('READY: UI-created finite key saved privately; send a prompt using mock/demo-cheap before deny.');return;
  }
  assert.equal(fs.lstatSync(statePath).mode&0o077,0);state=JSON.parse(fs.readFileSync(statePath));
  async function policy(value){
   await admin.goto(base+'/admin');await admin.locator('#vtab-safety-net').click();await admin.locator('#safety-limit').waitFor();
   while(await admin.locator('#safety-net-body button[onclick^="removeSafetyModel"]').count())await admin.locator('#safety-net-body button[onclick^="removeSafetyModel"]').first().click();
   for(const model of value.allowed_over_limit_models){await admin.locator('#safety-model-add').fill(model);await admin.getByRole('button',{name:'Add model',exact:true}).click();}
   await admin.locator('#safety-limit').fill(String(value.default_monthly_usd));await admin.locator('#safety-enforced').setChecked(value.enforced);
   const saved=admin.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/admin/safety-net'&&r.request().method()==='PUT');await admin.getByRole('button',{name:'Save safety net',exact:true}).click();assert.equal((await saved).status(),200);
  }
  if(action==='deny'){
   stage='verify harness usage';const user=await login(fs.readFileSync(keyPath,'utf8').trim());const quota=await user.evaluate(async()=>(await(await fetch('/api/v1/whoami')).json()).quota);assert.ok(quota.spent_usd>=.01,'run enough mock harness traffic to reach one cent');
   stage='set user budget through UI';await admin.locator('#budget [name=subject]').selectOption(state.subject);await admin.locator('#budget [name=monthly_usd]').fill('0.01');await done(admin,()=>admin.getByRole('button',{name:'Set override',exact:true}).click());
   await policy({...state.policy,enforced:true,allowed_over_limit_models:[]});await new Promise(r=>setTimeout(r,17000));console.log('READY: UI budget is below recorded spend and exceptions are empty; verify harness denial.');
  }else if(action==='allow'){
   stage='set exception through UI';await policy({...state.policy,enforced:true,allowed_over_limit_models:['fixture-cheap']});await new Promise(r=>setTimeout(r,17000));console.log('READY: UI exception enabled; explicitly select mock/demo-cheap in the harness.');
  }else{
   stage='restore original policy through UI';await policy(state.policy);await admin.goto(base+'/management');await admin.locator('#admin').waitFor({state:'visible'});
   await admin.locator('#user [name=subject]').fill(state.subject);await admin.locator('#user [name=name]').fill('Interactive harness rehearsal');await admin.locator('#user [name=active]').selectOption('false');await done(admin,()=>admin.locator('#user button').click());
   fs.rmSync(keyPath,{force:true});console.log('RESTORED: original policy, suspended test profile and removed temporary user key.');
  }
 }finally{await browser.close();}
})().catch(()=>{console.error('FAIL at '+stage+'; credentials withheld. Run restore with the same private directory.');process.exitCode=1});
