'use strict';
require('./mock-guard.cjs')();
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const {X509Certificate,createHash}=require('node:crypto');
const assert=require('node:assert/strict');
let stage='setup';
(async()=>{
 if(process.env.MOCK_DEPLOYMENT_CONFIRMED!=='yes')throw new Error('mock confirmation required');
 const dir=process.env.KEY_DIRECTORY,base=process.env.GATEWAY_URL;
 const manifest=JSON.parse(fs.readFileSync(path.join(dir,'manifest.json')));
 assert.equal(manifest.synthetic,true);assert.equal(manifest.users.length,20);
 const cert=new X509Certificate(fs.readFileSync(path.join(dir,'server.pem')));
 const pin=createHash('sha256').update(cert.publicKey.export({type:'spki',format:'der'})).digest('base64');
 const browser=await chromium.launch({args:['--ignore-certificate-errors-spki-list='+pin]});
 async function session(user){
  const file=path.join(dir,user.subject+'.key');assert.equal(fs.statSync(file).mode&0o077,0);
  const context=await browser.newContext();const page=await context.newPage();
  await page.goto(base+'/login');await page.locator('#api_key').fill(fs.readFileSync(file,'utf8').trim());
  await Promise.all([page.waitForURL(u=>u.pathname!=='/login'),page.getByRole('button',{name:'Sign In',exact:true}).click()]);
  return {context,page};
 }
 try{
  for(const index of [0,10,1]){
   const user=manifest.users[index];stage='session '+(user.manager?'manager':'personal')+' team '+user.team;
   const {context,page}=await session(user);
   await page.goto(base+(user.manager?'/manager':'/dashboard'));
   const allowed=manifest.users.filter(u=>user.manager?u.team===user.team:u.subject===user.subject).map(u=>u.user_id);
   const outside=manifest.users.find(u=>u.team!==user.team);
   const result=await page.evaluate(async({allowed,outside})=>{
    const scope=await(await fetch('/api/v1/org/scope')).json();
    const response=await fetch('/api/v1/org/usage');const rows=await response.json();
    const inside=await fetch('/api/v1/org/person?slug='+encodeURIComponent(allowed[0]));
    const denied=await fetch('/api/v1/org/person?slug='+encodeURIComponent(outside));
    const rootDenied=await fetch('/api/v1/org/usage?root='+encodeURIComponent(outside));
    const directory=await fetch('/api/v1/dashboard/directory-users');
    const admin=await fetch('/api/v1/management/users',{headers:{'X-Forwarded-User':'admin','X-MaaS-Username':'admin'}});
    const who=await(await fetch('/api/v1/whoami')).json();
    return {scope,status:response.status,rows,inside:inside.status,denied:denied.status,rootDenied:rootDenied.status,directory:directory.status,admin:admin.status,quota:who.quota};
   },{allowed,outside:outside.user_id});
   assert.equal(result.status,200);assert.equal(result.scope.scope,user.manager?'manager':'self');
   assert.equal(result.scope.isManager,user.manager);
   assert.deepEqual(result.rows.map(r=>r.slug).sort(),allowed.sort());
   assert.ok(result.rows.every(r=>r.requests>0),'synthetic usage missing');
   assert.equal(result.inside,200);assert.equal(result.denied,403);assert.equal(result.rootDenied,403);
   assert.equal(result.directory,403);assert.equal(result.admin,403);
   if(user.manager){await page.waitForFunction(()=>document.querySelector('#scopeSub')?.textContent.includes('10 people in your tree'));}
   console.log('PASS: '+(user.manager?'manager':'personal')+' team '+user.team+' sees '+result.rows.length+' scoped profiles; cross-team and admin access denied');
   await context.close();
  }
 }finally{await browser.close();}
})().catch(()=>{console.error('FAIL at '+stage+'; credentials and response bodies withheld');process.exitCode=1});
