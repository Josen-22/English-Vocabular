const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const readline=require('node:readline');
const path=require('node:path');
const fs=require('node:fs');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const directory=path.join(root,'验证','ui-'+Date.now());fs.mkdirSync(directory,{recursive:true});
  const python=process.env.VOCAB_TEST_PYTHON||'python';
  const driver=spawn(python,[path.join(root,'src','tests','bridge_driver.py'),directory],{stdio:['pipe','pipe','inherit'],windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  let readyResolve;const ready=new Promise(r=>readyResolve=r),pending=new Map();let seq=0;
  readline.createInterface({input:driver.stdout}).on('line',line=>{
    const data=JSON.parse(line);if(data.ready){readyResolve(data);return;}
    pending.get(data.id)?.(data.result);pending.delete(data.id);
  });
  driver.on('exit',code=>{if(code)console.error('bridge driver exit',code);});
  let browser;
  try{
    const info=await ready;browser=await chromium.launch({channel:'msedge',headless:true});
    const page=await browser.newPage({viewport:{width:1160,height:900}});page.setDefaultTimeout(12000);
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const requests=[];page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
    await page.exposeFunction('nativeCall',(action,payload)=>new Promise(resolve=>{
      const id=++seq;pending.set(id,resolve);driver.stdin.write(JSON.stringify({id,action,payload})+'\n');
    }));
    await page.addInitScript(()=>{window.pywebview={api:{call:(action,payload)=>window.nativeCall(action,payload)}};});
    await page.goto(info.url);await page.waitForFunction(()=>document.documentElement.dataset.appReady==='true');
    const checks=[];
    for(const theme of ['clean','paper','focus']){
      await page.selectOption('#theme-select',theme);
      await page.locator('[data-nav=lookup]').click();await page.fill('#query','resilient');await page.locator('#lookup-button').click();
      await page.waitForFunction(()=>!document.getElementById('editor').hidden);
      await page.fill('#edit-notes','跨主题保留的备注');
      for(const other of ['clean','paper','focus']){
        await page.selectOption('#theme-select',other);
        if(await page.inputValue('#edit-notes')!=='跨主题保留的备注')throw Error('theme switch lost draft');
      }
      await page.selectOption('#theme-select',theme);await page.locator('#save-button').click();
      await page.waitForFunction(()=>document.getElementById('lookup-feedback').textContent.includes('已保存'));
      await page.locator('[data-nav=library]').click();await page.selectOption('#sort-select','az');
      await page.waitForFunction(()=>document.querySelector('.word-card-title')?.textContent==='abolish');
      await page.screenshot({path:path.join(directory,theme+'-library.png'),fullPage:true});
      await page.locator('#table-view').click();await page.waitForFunction(()=>!document.getElementById('word-table-wrap').hidden);
      await page.fill('#library-search','湿气');await page.waitForFunction(()=>document.querySelectorAll('#word-table tbody tr').length===1);
      await page.locator('#word-table tbody button').click();await page.locator('#detail-dialog').waitFor();
      if(!(await page.locator('#detail-body').textContent()).includes('moisture'))throw Error('detail mismatch');
      await page.locator('[data-close=detail-dialog]').click();
      await page.fill('#library-search','');await page.locator('#cards-view').click();
      await page.locator('[data-filter=new]').click();
      const expectedNew=await page.evaluate(async()=>(await window.pywebview.api.call('words',{filter:'new'})).data.length);
      await page.waitForFunction(n=>document.querySelectorAll('.word-card').length===n,expectedNew);
      await page.locator('[data-filter=all]').click();
      await page.locator('[data-nav=study]').click();
      if(await page.locator('#start-quiz-button').count())await page.locator('#start-quiz-button').click();
      await page.locator('#reveal-answer').waitFor();
      const spelling=page.locator('#quiz-spelling');if(await spelling.count())await spelling.fill('any answer');
      const before=await page.locator('#progress-label').textContent();
      await page.locator('#reveal-answer').click();await page.locator('[data-grade=认识]').click();
      await page.waitForFunction(previous=>document.getElementById('progress-label').textContent!==previous,before);
      checks.push(theme);
    }
    const overflow=[];
    for(const width of [760,1024,1440]){
      await page.setViewportSize({width,height:900});
      for(const theme of ['clean','paper','focus']){
        await page.selectOption('#theme-select',theme);
        for(const section of ['study','lookup','library']){
          await page.locator('[data-nav='+section+']').click();
          await page.waitForTimeout(60);
          const bad=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
          if(bad.scroll>bad.width+2)overflow.push({width,theme,section,...bad});
        }
      }
    }
    await page.selectOption('#theme-select','paper');
    await page.waitForTimeout(150);await page.reload();await page.waitForFunction(()=>document.documentElement.dataset.appReady==='true');
    if(await page.getAttribute('body','data-theme')!=='paper')throw Error('theme not persisted');
    const report={ok:!errors.length&&!overflow.length&&!requests.length,themes:checks,errors,overflow,externalRequests:requests,directory};
    fs.writeFileSync(path.join(root,'验证','frontend-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));if(!report.ok)throw Error('frontend checks failed');
  }finally{await browser?.close();driver.stdin.end();driver.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
