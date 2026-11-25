const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const readline=require('node:readline');
const path=require('node:path');
const fs=require('node:fs');

(async()=>{
  const root=path.resolve(__dirname,'..'),directory=path.join(root,'验证','learning-ui-'+Date.now());fs.mkdirSync(directory,{recursive:true});
  const driver=spawn(process.env.VOCAB_TEST_PYTHON||'python',[path.join(root,'src/tests/bridge_driver.py'),directory],
    {stdio:['pipe','pipe','inherit'],windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  let resolveReady;const ready=new Promise(r=>resolveReady=r),pending=new Map();let seq=0;
  readline.createInterface({input:driver.stdout}).on('line',line=>{const d=JSON.parse(line);if(d.ready)resolveReady(d);else {pending.get(d.id)?.(d.result);pending.delete(d.id);}});
  let browser;
  try{
    const info=await ready;browser=await chromium.launch({channel:'msedge',headless:true});
    const page=await browser.newPage({viewport:{width:1160,height:950}});page.setDefaultTimeout(12000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.exposeFunction('nativeCall',(action,payload)=>new Promise(resolve=>{const id=++seq;pending.set(id,resolve);driver.stdin.write(JSON.stringify({id,action,payload})+'\n');}));
    await page.addInitScript(()=>{
      window.pywebview={api:{call:(action,payload)=>window.nativeCall(action,payload)}};
      window.__audioPlays=[];HTMLMediaElement.prototype.play=function(){window.__audioPlays.push(this.src);return Promise.resolve();};
      HTMLMediaElement.prototype.pause=function(){};
    });
    await page.goto(info.url);await page.waitForFunction(()=>document.documentElement.dataset.appReady==='true');
    const api=(action,payload={})=>page.evaluate(async p=>{const r=await window.pywebview.api.call(p.action,p.payload);if(!r.ok)throw Error(r.error);return r.data;},{action,payload});
    await page.click('#open-settings');await page.fill('#setting-count','4');
    await page.locator('#setting-new').evaluate(e=>{e.value='100';e.dispatchEvent(new Event('input'));});
    await page.locator('#setting-meaning').evaluate(e=>{e.value='0';e.dispatchEvent(new Event('input'));});
    await page.check('#setting-audio-cache');await page.click('#save-settings');await page.waitForFunction(()=>!document.getElementById('settings-dialog').open);
    await page.click('[data-nav=lookup]');await page.fill('#query','resilient');await page.click('#lookup-button');await page.waitForFunction(()=>!document.getElementById('editor').hidden);
    await page.locator('#sense-options input').first().check();
    if(!(await page.inputValue('#edit-study-meaning')).includes('有韧性的'))throw Error('sense was not selected');
    for(const theme of ['clean','paper','focus']){await page.selectOption('#theme-select',theme);if(!(await page.inputValue('#edit-study-meaning')).includes('有韧性的'))throw Error('theme lost selected meaning');}
    if(await page.evaluate(()=>window.__audioPlays.length)!==0)throw Error('audio played without a click');
    await page.locator('#editor-audio [data-accent=uk]').click();await page.waitForFunction(()=>window.__audioPlays.length===1);
    await page.locator('#editor-audio [data-accent=us]').click();await page.waitForFunction(()=>window.__audioPlays.length===2);
    await page.click('#save-button');await page.waitForFunction(()=>document.getElementById('lookup-feedback').textContent.includes('已保存'));
    const saved=(await api('words',{search:'resilient'}))[0];
    if(!saved.study_meaning.includes('有韧性的')||!saved.meaning.includes('能迅速恢复'))throw Error('learning/full meanings not separated');
    if(fs.readdirSync(path.join(directory,'数据','发音缓存')).filter(p=>p.endsWith('.mp3')).length!==2)throw Error('both accent caches missing');
    await page.screenshot({path:path.join(directory,'study-meaning.png'),fullPage:true});
    await page.click('[data-nav=study]');await page.click('#start-quiz-button');await page.locator('#reveal-answer').waitFor();
    const first=(await api('bootstrap')).questions;if(first.length!==4||first.some(q=>q.kind!=='spelling'))throw Error('custom settings not used');
    if(await page.locator('.quiz-card .audio-button').first().isVisible())throw Error('spelling answer audio leaked before reveal');
    await page.click('#open-settings');await page.fill('#setting-count','1');
    await page.locator('#setting-meaning').evaluate(e=>{e.value='100';e.dispatchEvent(new Event('input'));});await page.click('#save-settings');await page.waitForFunction(()=>!document.getElementById('settings-dialog').open);
    if((await api('bootstrap')).questions.length!==4)throw Error('settings replaced existing daily group');
    for(const result of ['不认识','模糊','认识','认识']){
      if(await page.locator('#quiz-spelling').count())await page.fill('#quiz-spelling','test answer');
      const before=await page.locator('#progress-label').textContent();await page.click('#reveal-answer');await page.click('[data-grade='+result+']');
      await page.waitForFunction(old=>document.getElementById('progress-label').textContent!==old,before);
    }
    const daily=(await api('bootstrap')).questions;
    await page.click('#practice-wrong');await page.locator('#reveal-answer').waitFor();
    const active=(await api('bootstrap')).practice;
    if(active.questions.length!==1||active.questions[0].kind!=='meaning')throw Error('practice did not use new settings');
    await page.click('#reveal-answer');await page.click('[data-grade=认识]');await page.waitForFunction(()=>document.getElementById('study-content').textContent.includes('这一轮专项完成了'));
    if(JSON.stringify((await api('bootstrap')).questions)!==JSON.stringify(daily))throw Error('practice changed daily results');
    await page.click('#back-daily');await page.click('#practice-weak');await page.locator('#reveal-answer').waitFor();
    await page.reload();await page.waitForFunction(()=>document.documentElement.dataset.appReady==='true');
    await page.locator('#resume-practice').waitFor();await page.click('#resume-practice');await page.locator('#reveal-answer').waitFor();
    await page.click('[data-nav=report]');await page.locator('.activity-row').first().waitFor();
    const report=await api('weekly');if(report.practice_attempts!==1||report.attempts!==12)throw Error('weekly report counts incorrect');
    if(await page.locator('.activity-row').count()!==7)throw Error('weekly period is not seven days');
    const overflow=[];
    for(const width of [760,1024,1440]){
      await page.setViewportSize({width,height:950});
      for(const theme of ['clean','paper','focus']){
        await page.selectOption('#theme-select',theme);await page.waitForTimeout(200);
        if(width===1024)await page.screenshot({path:path.join(directory,theme+'-weekly.png'),fullPage:true});
        const bad=await page.evaluate(()=>document.documentElement.scrollWidth>document.documentElement.clientWidth+2);
        if(bad)overflow.push({width,theme});
      }
    }
    const output={ok:!errors.length&&!overflow.length,features:['study_meaning','practice','phonetics_audio','learning_settings','weekly_report'],errors,overflow,directory};
    fs.writeFileSync(path.join(root,'验证','learning-ui-report.json'),JSON.stringify(output,null,2));console.log(JSON.stringify(output,null,2));
    if(!output.ok)throw Error('feature UI checks failed');
  }finally{await browser?.close();driver.stdin.end();driver.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
