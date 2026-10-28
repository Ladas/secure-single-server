#!/usr/bin/env python3
"""Exercise the public API through the CLI helper against a mock gateway."""
import json
import os
from pathlib import Path
import subprocess
import ssl
import urllib.request
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]


def main():
    if os.environ.get('MOCK_DEPLOYMENT_CONFIRMED')!='yes': raise ValueError('mock confirmation required')
    directory=Path(os.environ['KEY_DIRECTORY'])
    base=os.environ['GATEWAY_URL']
    subject='demo-cli-'+uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory() as temporary:
        private=Path(temporary)
        counter=0
        def api(method,path,body=None,key=None):
            nonlocal counter
            counter+=1
            output=private/f'response-{counter}.json'
            cmd=[sys.executable,str(ROOT/'scripts/pricetag/api'),method,path,'--url',base,'--key-file',str(key or directory/'admin.key'),'--ca-file',str(directory/'ca.pem'),'--output',str(output)]
            if body is not None:
                source=private/f'input-{counter}.json';source.write_text(json.dumps(body));source.chmod(0o600)
                cmd+=['--input',str(source)]
            for attempt in range(30 if method == 'GET' else 1):
                output=private/f'response-{counter}-{attempt}.json'
                cmd[cmd.index('--output')+1]=str(output)
                result=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                if result.returncode==0: return json.loads(output.read_text())
                if method=='GET': time.sleep(1)
            raise RuntimeError(method+' '+path+' failed; mutations are not retried')
        config=api('GET','/api/v1/management/gateway/config')['configuration']
        assert config['providers'] and all(p['name']=='mock' and set(p['urls'].values())=={'http://pricetag-provider:18080/v1','http://pricetag-provider:18081'} for p in config['providers'])
        created=[]
        changed=False
        def apply(configuration,credentials):
            current=api('GET','/api/v1/management/gateway/config')
            operation=api('PUT','/api/v1/management/gateway/config',{'revision':current['revision'],'configuration':configuration,'credentials':credentials})
            for _ in range(90):
                status=api('GET','/api/v1/management/gateway/status')
                assert status.get('operation_id',status.get('id'))==operation.get('operation_id',operation.get('id'))
                if status.get('state')=='complete': return
                if status.get('state')=='failed': raise AssertionError('activation failed')
                time.sleep(1)
            raise AssertionError('activation timeout')
        try:
            for name,role in [(subject+'-manager','user'),(subject,'user')]:
                api('PUT','/api/v1/management/users',{'subject':name,'name':'Synthetic CLI test','role':role});created.append(name)
            rows=api('GET','/api/v1/management/users')
            manager=next(r for r in rows if subject+'-manager' in r.get('logins',[]))
            user=next(r for r in rows if subject in r.get('logins',[]))
            api('PATCH','/api/v1/admin/partner-users/'+user['user_id'],{'role':'user','manager_user_id':manager['user_id']})
            api('PUT','/api/v1/management/budgets',{'subject':subject,'monthly_usd':5})
            api('GET','/api/v1/management/budgets')
            api('PUT','/api/v1/management/prices',{'model':'fixture-cli-'+uuid.uuid4().hex[:8],'provider':'mock','input_cost_per_mtok':1,'output_cost_per_mtok':2,'cache_write_cost_per_mtok':0,'cache_read_cost_per_mtok':0})
            api('GET','/api/v1/management/prices')
            policy=api('GET','/api/v1/management/policy');api('PUT','/api/v1/management/policy',{k:policy[k] for k in ('default_monthly_usd','enforced','allowed_over_limit_models')})
            discounts=api('GET','/api/v1/admin/pricing-discounts');api('PUT','/api/v1/admin/pricing-discounts',discounts)
            issued=api('POST','/api/v1/management/keys',{'subject':subject,'name':'CLI demo','expiresIn':'1h'})
            key=private/'user.key';key.write_text(issued['key']);key.chmod(0o600)
            api('GET','/api/v1/whoami',key=key)
            api('GET','/api/v1/dashboard/overview',key=key)
            own=api('POST','/me/keys',{'name':'personal-cli','expiresIn':'1h'},key=key)
            api('GET','/me/keys',key=key);api('DELETE','/me/keys/'+own['id'],key=key)
            # Publish an alias and rotate the synthetic provider credential via
            # the public CLI, then verify real authenticated mock inference.
            api('POST','/api/v1/management/gateway/discover',{'provider':'mock','api':'openai','credential':'synthetic-anthropic'})
            candidate=json.loads(json.dumps(config))
            alias=json.loads(json.dumps(candidate['models'][0]))
            alias['id']='mock/cli-'+uuid.uuid4().hex[:8]
            candidate['models'].append(alias)
            changed=True
            apply(candidate,{'mock':'synthetic-anthropic'})
            tls=ssl.create_default_context(cafile=str(directory/'ca.pem'))
            request=urllib.request.Request(base+'/v1/chat/completions',json.dumps({'model':alias['id'],'messages':[{'role':'user','content':'synthetic CLI route test'}],'max_tokens':16}).encode(),headers={'Authorization':'Bearer '+issued['key'],'Content-Type':'application/json'})
            with urllib.request.urlopen(request,context=tls,timeout=30) as response:
                assert response.status==200 and json.load(response)['usage']['total_tokens']==5
            apply(config,{})
            changed=False
            api('DELETE','/me/keys/'+issued['id'],key=key)
            print('PASS: CLI/public HTTPS users, manager assignment, budget, prices, discounts, policy, finite personal keys, dashboard read and credential/alias activation with authenticated mock inference')
        finally:
            if changed: apply(config,{})
            for name in created: api('PUT','/api/v1/management/users',{'subject':name,'active':False})


if __name__=='__main__':main()
