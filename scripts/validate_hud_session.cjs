// Real local HTTP guard and HUD recovery. Cookie stays private to this client.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

async function main(){
  const root=path.resolve(__dirname,'..');
  let cookie='jarvis_session=expired-validation';
  const requests=[];
  const sandbox=vm.createContext({ReactorVisuals:class{},window:{addEventListener(){}},AbortSignal,
    fetch:async(url,options)=>{
      const response=await fetch('http://127.0.0.1:8000'+url,{...options,headers:{...options.headers,Cookie:cookie}});
      requests.push({path:url,status:response.status});
      if(url==='/'){
        const header=response.headers.get('set-cookie');
        assert.ok(header?.startsWith('jarvis_session='));
        cookie=header.split(';',1)[0];
      }
      return response;
    }});
  vm.runInContext(fs.readFileSync(path.join(root,'web/app.js'),'utf8')+'\nglobalThis.HUD=JarvisHUD;',sandbox);
  const hud=Object.create(sandbox.HUD.prototype);
  await hud.api('reminders');
  assert.deepEqual(requests,[{path:'/api/reminders',status:403},{path:'/',status:200},{path:'/api/reminders',status:200}]);
  assert.equal(hud.sessionErrorShown,false);
  await hud.api('reminders');
  assert.equal(requests.length,4);assert.equal(requests[3].status,200);
  const report={passed:true,real_http:true,read_only:true,requests};
  fs.writeFileSync(path.join(root,'.data/hud-session-validation.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
