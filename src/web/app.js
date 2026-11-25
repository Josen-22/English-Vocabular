'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const state={page:'study',prefs:{theme:'clean',view:'cards',sort:'added_desc',filter:'all'},
    boot:null,words:[],draft:null,draftVersion:0,lookupToken:0,listToken:0,detailId:null,
    preview:null,quizId:null,quizAnswer:'',revealed:false,answering:false,ready:false,context:'daily',practice:null};
  let extras;
  let toastTimer,searchTimer,confirmResolve;
  function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
  function toast(text,error=false){$('toast').textContent=text;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,error?6500:4000);}
  async function rpc(action,payload={}){
    if(!window.pywebview?.api)throw Error('尚未连接本地程序，请从第二版桌面程序打开。');
    const result=await window.pywebview.api.call(action,payload);
    if(!result?.ok)throw Error(result?.error||'操作未完成，请重试。');
    return result.data;
  }
  function safe(fn){return async event=>{try{await fn(event);}catch(e){toast(e.message,true);}};}
  async function busy(button,fn){if(button.disabled)return;button.disabled=true;try{return await fn();}finally{if(button.isConnected)button.disabled=false;}}
  function confirmAction(title,message){
    $('confirm-title').textContent=title;$('confirm-message').textContent=message;
    $('confirm-dialog').showModal();
    return new Promise(resolve=>confirmResolve=resolve);
  }
  function closeConfirm(value){$('confirm-dialog').close();const resolve=confirmResolve;confirmResolve=null;if(resolve)resolve(value);}
  $('confirm-yes').addEventListener('click',()=>closeConfirm(true));
  $('confirm-no').addEventListener('click',()=>closeConfirm(false));
  $('confirm-dialog').addEventListener('cancel',()=>{const r=confirmResolve;confirmResolve=null;if(r)r(false);});
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>$(b.dataset.close).close()));
  $('preview-dialog').addEventListener('close',()=>state.preview=null);
  function navigate(page){
    extras?.stopAudio();
    state.page=page;
    for(const name of ['study','lookup','library','report'])$(name+'-page').hidden=name!==page;
    document.querySelectorAll('[data-nav]').forEach(b=>{const active=b.dataset.nav===page;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    if(page==='library')refreshLibrary().catch(e=>toast(e.message,true));
    if(page==='study'&&state.boot)renderStudy();
    if(page==='lookup')$('query').focus();
    if(page==='report')extras.loadReport().catch(e=>toast(e.message,true));
  }
  document.querySelectorAll('[data-nav]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.nav)));
  $('library-add').addEventListener('click',()=>navigate('lookup'));
  $('quick-lookup-button').addEventListener('click',()=>{const q=$('quick-word').value.trim();navigate('lookup');if(q){$('query').value=q;performLookup().catch(e=>toast(e.message,true));}});
  $('quick-word').addEventListener('keydown',e=>{if(e.key==='Enter')$('quick-lookup-button').click();});
  function applyPreferences(prefs){
    state.prefs={...state.prefs,...prefs};document.body.dataset.theme=state.prefs.theme;
    $('theme-select').value=state.prefs.theme;$('sort-select').value=state.prefs.sort;
    $('cards-view').setAttribute('aria-pressed',String(state.prefs.view==='cards'));
    $('table-view').setAttribute('aria-pressed',String(state.prefs.view==='table'));
    document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b.dataset.filter===state.prefs.filter));
  }
  async function savePreferences(changes){applyPreferences(changes);await rpc('preferences',changes);}
  $('theme-select').addEventListener('change',safe(async()=>{await savePreferences({theme:$('theme-select').value});}));
  $('sort-select').addEventListener('change',safe(async()=>{await savePreferences({sort:$('sort-select').value});await refreshLibrary();}));
  for(const view of ['cards','table'])$(view+'-view').addEventListener('click',safe(async()=>{await savePreferences({view});renderLibrary();}));
  document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',safe(async()=>{await savePreferences({filter:b.dataset.filter});await refreshLibrary();})));
  $('library-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>refreshLibrary().catch(e=>toast(e.message,true)),140);});
  $('reset-library').addEventListener('click',safe(async()=>{$('library-search').value='';await savePreferences({filter:'all'});await refreshLibrary();}));
  document.querySelectorAll('[data-sort]').forEach(b=>b.addEventListener('click',safe(async()=>{
    const reverse={az:'za',added_desc:'added_asc',mastery_asc:'mastery_desc'};
    const key=b.dataset.sort;await savePreferences({sort:state.prefs.sort===key?(reverse[key]||key):key});await refreshLibrary();
  })));
  async function bootstrap(initial=false){
    const boot=await rpc('bootstrap');const changed=state.boot&&state.boot.today!==boot.today;
    state.boot=boot;if(initial)applyPreferences(boot.preferences);
    const date=new Date(boot.today+'T12:00:00');
    $('date-label').textContent=new Intl.DateTimeFormat('zh-CN',{month:'long',day:'numeric',weekday:'long'}).format(date);
    $('side-count').textContent=boot.stats.total+' 个已收录词条';
    $('library-summary').textContent='共 '+boot.stats.total+' 个词条 · '+boot.stats.new+' 个未测新词 · '+boot.stats.due+' 个到期旧词';
    $('connection-status').textContent='本地单词本 · 学习记录即时保存';
    renderDistribution();
    if(changed){if(state.context==='daily'){state.quizId=null;state.revealed=false;state.quizAnswer='';}toast('新的一天，可以开始今天的每日抽测。');}
    extras?.renderPracticeActions();
    if(initial||changed)renderStudy();
    return boot;
  }
  function renderDistribution(){
    const container=$('distribution');container.replaceChildren();
    for(const [key,label] of [['new','未测新词'],['weak','薄弱词'],['learning','学习中'],['mastered','已掌握']]){
      const b=node('button');b.style.setProperty('--group-color','var(--'+key+')');b.append(node('span','',label),node('strong','',state.boot.distribution[key]));
      b.addEventListener('click',safe(async()=>{await savePreferences({filter:key});await refreshLibrary();}));container.append(b);
    }
  }
  async function refreshLibrary(){
    if(!state.ready)return;
    const token=++state.listToken;
    const rows=await rpc('words',{search:$('library-search').value,filter:state.prefs.filter,sort:state.prefs.sort});
    if(token!==state.listToken)return;state.words=rows;renderLibrary();
  }
  function rate(w){return w.attempts?Math.round(w.correct/w.attempts*100)+'%':'未测试';}
  function mastery(w){const wrapper=node('span','mastery-segments');wrapper.setAttribute('aria-label','掌握度 '+w.mastery+' / 5');for(let i=0;i<5;i++)wrapper.append(node('span',i<w.mastery?'filled':''));return wrapper;}
  function renderLibrary(){
    const rows=state.words,cards=$('word-cards'),tbody=$('word-table').querySelector('tbody');cards.replaceChildren();tbody.replaceChildren();
    $('word-cards').hidden=state.prefs.view!=='cards'||!rows.length;
    $('word-table-wrap').hidden=state.prefs.view!=='table'||!rows.length;
    $('library-empty').hidden=!!rows.length;
    $('result-count').textContent='显示 '+rows.length+' / '+(state.boot?.stats.total||0)+' 个词条';
    $('sort-hint').textContent=state.prefs.sort==='accuracy'?'未测试词条排在末尾；薄弱词指已测且掌握度 ≤ 1。':'';
    for(const w of rows){
      if(state.prefs.view==='cards'){
        const card=node('button','word-card');card.setAttribute('aria-label','查看 '+w.word+' 的详情');
        const header=node('span','word-card-header');header.append(node('span','word-card-title',w.word),node('span','word-card-pos',w.pos));
        const footer=node('span','word-card-footer'),m=node('span','mastery-row');m.append(node('span','',w.is_new?'未测新词':'掌握度 '+w.mastery+' / 5'),mastery(w));
        const meta=node('span','card-meta');meta.append(node('span','',w.attempts?'正确率 '+rate(w)+' · '+w.attempts+' 次':'等待第一次抽测'),node('span','',(w.is_due?'已到期 · ':'复习 ')+w.due));
        footer.append(m,meta);card.append(header,node('span','word-card-meaning',w.study_meaning?'抽测：'+w.study_meaning:w.meaning),footer);
        card.addEventListener('click',safe(()=>showDetail(w.id)));cards.append(card);
      }else{
        const tr=node('tr'),wordCell=node('td'),button=node('button','',w.word);button.addEventListener('click',safe(()=>showDetail(w.id)));wordCell.append(button,node('div','muted small',w.pos));
        const meaning=node('td');meaning.append(node('span','table-meaning',w.meaning));
        tr.append(wordCell,meaning,node('td','',w.mastery+' / 5'),node('td','',rate(w)),node('td','',w.attempts),node('td','',w.due),node('td','',w.added));tbody.append(tr);
      }
    }
  }
  function invalidateLookup(){state.lookupToken++;$('lookup-button').disabled=false;$('lookup-button').textContent='有道查词';$('requery-button').disabled=false;state.preview=null;if($('preview-dialog').open)$('preview-dialog').close();}
  $('query').addEventListener('input',invalidateLookup);
  for(const id of ['edit-word','edit-pos','edit-meaning','edit-source','edit-notes'])$(id).addEventListener('input',()=>state.draftVersion++);
  function draftFromForm(){return {id:state.draft?.id,word:$('edit-word').value,pos:$('edit-pos').value,meaning:$('edit-meaning').value,source:$('edit-source').value,notes:$('edit-notes').value,study_meaning:$('edit-study-meaning').value,senses:$('edit-meaning').value===state.draft?.meaning?state.draft?.senses:[],uk_phonetic:state.draft?.uk_phonetic||'',us_phonetic:state.draft?.us_phonetic||''};}
  function renderDraft(word){
    state.draft={...word};state.draftVersion++;
    $('query').value=word.word;
    for(const [key,id] of [['word','edit-word'],['pos','edit-pos'],['meaning','edit-meaning'],['source','edit-source'],['notes','edit-notes']])$(id).value=word[key]||'';
    $('editor-title').textContent=word.word;$('editor-caption').textContent=word.id?(word.deleted?'已删除词条 · 保存后恢复':'编辑已有词条'):'准备收录';
    $('save-button').textContent=word.id?'保存修改':'收入单词手册';$('editor').hidden=false;$('lookup-empty').hidden=true;
    extras.renderSenses(word);
  }
  function clearEditor(){invalidateLookup();state.draft=null;state.draftVersion++;$('query').value='';$('editor').hidden=true;$('lookup-empty').hidden=false;$('lookup-feedback').textContent='';$('query').focus();}
  $('clear-editor-button').addEventListener('click',clearEditor);
  async function performLookup(refresh=false){
    const query=$('query').value.trim();if(!query){$('lookup-feedback').textContent='请先输入要查询的单词或短语。';return;}
    const token=++state.lookupToken,version=state.draftVersion;
    $('lookup-button').disabled=true;$('lookup-button').textContent='正在查询…';$('requery-button').disabled=true;
    $('lookup-feedback').textContent='正在读取有道词性与基础释义…';
    try{
      const data=await rpc('lookup',{word:query,refresh});
      if(token!==state.lookupToken)return;
      if(version!==state.draftVersion){$('lookup-feedback').textContent='查询期间内容已编辑，本次结果没有覆盖表单。';return;}
      if(refresh&&state.draft){
        state.preview={word:data.word,token,version};
        $('preview-body').replaceChildren(node('div','detail-word',data.headword||data.word.word),node('div','detail-meaning',data.word.meaning),node('p','muted small','只替换当前表单的词性、释义和来源。备注与学习进度保留，保存后才写入。'));
        $('preview-dialog').showModal();$('lookup-feedback').textContent='已查到新释义，请在预览中决定是否使用。';
      }else{
        renderDraft(data.word);
        $('lookup-feedback').textContent=data.existing?'单词本里已有这个词。原释义和学习进度已保留，可重新查询有道更新。':'已自动填好词性、释义和来源，浏览后点击收录即可。';
      }
    }catch(e){if(token===state.lookupToken)$('lookup-feedback').textContent=e.message;}
    finally{if(token===state.lookupToken){$('lookup-button').disabled=false;$('lookup-button').textContent='有道查词';$('requery-button').disabled=false;}}
  }
  $('lookup-button').addEventListener('click',()=>performLookup());
  $('query').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();performLookup();}});
  $('requery-button').addEventListener('click',()=>{$('query').value=$('edit-word').value;performLookup(true);});
  $('use-preview').addEventListener('click',()=>{
    const p=state.preview;
    if(p&&p.token===state.lookupToken&&p.version===state.draftVersion){const current=draftFromForm();renderDraft({...current,pos:p.word.pos,meaning:p.word.meaning,source:p.word.source,senses:p.word.senses,uk_phonetic:p.word.uk_phonetic,us_phonetic:p.word.us_phonetic});$('lookup-feedback').textContent='已更新表单，点击“保存修改”才会写入。';}
    $('preview-dialog').close();
  });
  $('open-web-button').addEventListener('click',safe(()=>rpc('open_dictionary',{word:$('query').value})));
  $('save-button').addEventListener('click',safe(()=>busy($('save-button'),async()=>{
    invalidateLookup();const word=await rpc('save',draftFromForm());renderDraft(word);$('lookup-feedback').textContent='已保存 '+word.word+'。';toast('已保存 '+word.word);await bootstrap();
  })));
  async function showDetail(id){
    const data=await rpc('history',{id});state.detailId=id;const w=data.word,container=$('detail-body');container.replaceChildren();
    const correct=data.reviews.filter(r=>r.result==='认识').length;
    container.append(node('div','detail-word',w.word),node('span','badge',w.pos||'词条'),node('div','detail-meaning',w.meaning));
    extras.addAudio(container,w.word,w);
    if(w.study_meaning)container.append(node('h3','history-title','抽测使用的义项'),node('p','detail-meaning',w.study_meaning));
    const fields=node('div','detail-fields');
    for(const line of ['来源：'+(w.source||'—'),'备注：'+(w.notes||'—'),'掌握度：'+w.mastery+' / 5　·　抽测 '+data.reviews.length+' 次　·　正确率 '+(data.reviews.length?Math.round(correct/data.reviews.length*100)+'%':'未测试'),'加入日期：'+w.added+'　·　下次复习：'+w.due])fields.append(node('p','',line));
    container.append(fields,node('h3','history-title','复习记录'));
    if(!data.reviews.length)container.append(node('p','muted small','还没有复习记录。'));
    for(const r of [...data.reviews].reverse()){
      const item=node('div','history-row');item.append(node('p','',r.reviewed+' · '+r.direction+' · '+r.result),node('p','muted','回答：'+(r.answer||'未记录文字回答')));if(r.notes)item.append(node('p','muted',r.notes));container.append(item);
      if(r.batch)item.append(node('p','muted small',r.batch));
    }
    $('detail-dialog').showModal();
  }
  $('detail-edit').addEventListener('click',safe(async()=>{
    const data=await rpc('history',{id:state.detailId});$('detail-dialog').close();invalidateLookup();$('query').value=data.word.word;renderDraft(data.word);navigate('lookup');
  }));
  $('detail-delete').addEventListener('click',safe(async()=>{
    const id=state.detailId;
    $('detail-dialog').close();if(!await confirmAction('删除词条','将这个词移出单词本？历史记录和已生成的题组会保留。'))return;
    await rpc('delete',{id});if(state.draft?.id===id)clearEditor();await bootstrap();await refreshLibrary();toast('已移出单词本，历史记录保留。');
  }));
  function renderStudy(){
    const container=$('study-content');container.replaceChildren();const practice=state.context==='practice';
    const questions=practice?(state.practice?.questions||[]):state.boot.questions,answered=questions.filter(q=>q.result!==null),q=questions.find(q=>q.result===null);
    extras.renderPracticeActions();
    $('study-title').textContent=practice?'把模糊的词，再走一遍。':'今天，记住一点。';
    $('study-subtitle').textContent=practice?(state.practice?.mode==='weak'?'薄弱词专项 · 随时可以暂停，之后继续。':'本轮错词复测 · 每日抽测结果保留。'):'按你的计划，一点一点记住。';
    $('study-progress').hidden=!questions.length;$('progress-label').textContent=answered.length+' / '+questions.length+' 已完成';
    document.querySelector('.progress-track').setAttribute('aria-valuemax',questions.length||10);document.querySelector('.progress-track').setAttribute('aria-valuenow',answered.length);$('progress-fill').style.width=(questions.length?answered.length/questions.length*100:0)+'%';
    $('study-summary').textContent=practice?'专项复测':questions.length?'新词 '+questions.filter(q=>q.is_new).length+' · 复习 '+questions.filter(q=>!q.is_new).length:'每日 '+(state.prefs.daily_count??10)+' 词';
    $('study-note').textContent=practice?'专项单独记录 · 评级更新掌握度 · 答完即时保存':'设置仅影响新题组 · 已生成的题目固定 · 答完即时保存';
    $('today-index').replaceChildren();for(const [i,item] of questions.slice(0,5).entries())$('today-index').append(node('li','',(i+1).toString().padStart(2,'0')+'　'+(item.kind==='spelling'&&item.result===null?'拼写练习':item.word)));
    if(!questions.length){
      const box=node('div','empty-state surface');box.append(node('span','empty-letter','Aa'),node('h2','',state.boot.stats.total?'每天一点，慢慢记牢。':'先收好第一个词。'),node('p','muted',state.boot.stats.total?'今天的十个词，会在开始后为你固定下来。':'查词收录之后，就可以开始每天的抽测。'));
      const button=node('button','primary',state.boot.stats.total?'开始今日抽测':'去查词收录');
      button.id='start-quiz-button';button.addEventListener('click',safe(()=>busy(button,async()=>{if(!state.boot.stats.total){navigate('lookup');return;}state.boot.questions=await rpc('start');renderStudy();})));box.append(button);container.append(box);return;
    }
    if(!q){
      const box=node('div','empty-state surface');box.append(node('span','empty-letter','✓'),node('h2','',practice?'这一轮专项完成了。':'今天完成了。'));
      const summary=node('div','complete-summary');for(const result of ['认识','模糊','不认识'])summary.append(node('span','',result+' '+questions.filter(q=>q.result===result).length+' 个'));box.append(summary,node('p','muted small',practice?'专项记录已保存，每日结果未改写。':'今天的记录已保存，可以再练本轮错词。'));
      const list=node('div','completion-list');for(const item of questions){const row=node('div','completion-row');row.append(node('span','',item.word),node('span','muted',item.result));list.append(row);}box.append(list);container.append(box);return;
    }
    if(q.id!==state.quizId){state.quizId=q.id;state.revealed=false;state.quizAnswer='';}
    const card=node('div','quiz-card'),top=node('div','quiz-top');top.append(node('span','badge',(q.kind==='meaning'?'看英文 · 回忆中文':'看中文 · 默写英文')+' / '+(q.is_new?'新词':'复习词')),node('span','muted small','第 '+q.ordinal+' 题 / '+questions.length));card.append(top);
    card.append(node('div','quiz-prompt'+(q.kind==='spelling'?' spelling':''),q.kind==='meaning'?q.word:q.meaning));
    if(q.kind==='meaning')extras.addAudio(card,q.word,q);
    if(q.kind==='spelling'){
      const input=node('input','quiz-input');input.id='quiz-spelling';input.placeholder='写下英文，忘记了也可以留空';input.setAttribute('aria-label','英文拼写答案');input.autocomplete='off';input.spellcheck=false;input.value=state.quizAnswer;input.disabled=state.revealed;input.addEventListener('input',()=>state.quizAnswer=input.value);input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!state.revealed){e.preventDefault();reveal.click();}});card.append(input);
    }
    const answer=node('div','quiz-answer',q.kind==='meaning'?q.meaning:'正确拼写：'+q.word);if(q.kind==='spelling')extras.addAudio(answer,q.word,q);answer.hidden=!state.revealed;card.append(answer);
    const controls=node('div','quiz-controls'),hint=node('p','quiz-hint',state.revealed?'选择掌握情况后立即保存，并进入下一题。':'先想一想，再看答案。');
    const reveal=node('button','primary',q.kind==='meaning'?'翻开释义':'检查拼写 / 忘记了');reveal.id='reveal-answer';reveal.hidden=state.revealed;
    const grades=node('div','quiz-controls');grades.style.paddingTop='0';grades.hidden=!state.revealed;
    for(const result of ['不认识','模糊','认识']){
      const button=node('button',result==='认识'?'primary':'',result);button.dataset.grade=result;
      button.addEventListener('click',safe(async()=>{
        if(state.answering)return;state.answering=true;for(const b of grades.querySelectorAll('button'))b.disabled=true;
        try{const data=await rpc(practice?'practice_answer':'answer',{id:q.id,answer:state.quizAnswer,result});if(practice)state.practice=data;else state.boot.questions=data;state.quizId=null;await bootstrap();renderStudy();}
        catch(e){await bootstrap();renderStudy();throw e;}finally{state.answering=false;}
      }));grades.append(button);
    }
    reveal.addEventListener('click',safe(()=>busy(reveal,async()=>{
      let matches=false;if(q.kind==='spelling')matches=(await rpc('check',{id:q.id,answer:state.quizAnswer,practice})).matches;
      state.revealed=true;answer.hidden=false;reveal.hidden=true;grades.hidden=false;
      if(q.kind==='spelling'){$('quiz-spelling').disabled=true;hint.textContent=(matches?'拼写一致，建议选“认识”。':'拼写不一致，建议选“不认识”。')+'其他可接受拼写可以自行修正。';}
      else hint.textContent='选择掌握情况后立即保存，并进入下一题。';
    })));
    controls.append(reveal,grades);card.append(controls,hint);container.append(card);
  }
  $('data-menu-button').addEventListener('click',()=>{const open=$('data-menu').hidden;$('data-menu').hidden=!open;$('data-menu-button').setAttribute('aria-expanded',String(open));});
  document.addEventListener('click',e=>{if(!e.target.closest('.data-tools')){$('data-menu').hidden=true;$('data-menu-button').setAttribute('aria-expanded','false');}});
  document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',safe(async()=>{
    $('data-menu').hidden=true;const action=b.dataset.action;
    if(action==='restore'&&!await confirmAction('恢复完整备份','接下来请选择备份文件。当前数据会恢复到备份时的状态；恢复前会自动保存当前数据。'))return;
    await busy($('data-menu-button'),async()=>{
      const result=await rpc(action);if(result?.cancelled)return;
      if(action==='backup')toast('完整备份已保存：\n'+result.path);
      if(action==='export')toast('Excel 已导出：\n'+result.path);
      if(action==='import')toast('新增 '+result.words+' 个词条，'+result.reviews+' 条复习记录。');
      if(action==='restore'){clearEditor();state.quizId=null;toast('已恢复，恢复前的数据另存于：\n'+result.safety);}
      await bootstrap();if(action==='restore'||action==='import')renderStudy();await refreshLibrary();
    });
  })));
  extras=window.createVocabExtras({$,state,node,rpc,safe,toast,busy,bootstrap,renderStudy,navigate,showDetail});
  let initStarted=false;
  async function initialize(){if(initStarted)return;initStarted=true;try{state.ready=true;await bootstrap(true);await refreshLibrary();document.documentElement.dataset.appReady='true';}catch(e){state.ready=false;initStarted=false;$('connection-status').textContent=e.message;toast(e.message,true);}}
  window.addEventListener('pywebviewready',initialize);
  if(window.pywebview?.api)initialize();
  setInterval(async()=>{if(!state.ready)return;try{const previous=state.boot.today;const boot=await rpc('bootstrap');if(previous!==boot.today){await bootstrap();if(state.page==='library')await refreshLibrary();}}catch(e){$('connection-status').textContent='本地连接暂时未完成，可稍后重试。';}},30000);
})();
