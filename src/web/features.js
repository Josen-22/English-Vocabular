'use strict';
window.createVocabExtras=({$,state,node,rpc,safe,toast,busy,bootstrap,renderStudy,navigate,showDetail})=>{
  let player=null,audioToken=0,senseToken=0,senseTimer;
  function stopAudio(){audioToken++;if(player){player.pause();player=null;}}
  function addAudio(container,word,metadata={}){
    const row=node('div','audio-line');
    for(const [accent,label,key] of [['uk','英式','uk_phonetic'],['us','美式','us_phonetic']]){
      const group=node('span','audio-group');if(metadata[key])group.append(node('span','phonetic',label+' '+metadata[key]));
      const button=node('button','audio-button',label+'发音');button.type='button';button.dataset.accent=accent;
      button.addEventListener('click',safe(()=>busy(button,async()=>{
        stopAudio();const token=audioToken;button.textContent='读取中…';
        try{
          const result=await rpc('pronounce',{word,accent});if(token!==audioToken)return;
          player=new Audio('data:'+result.mime+';base64,'+result.audio);
          try{await player.play();}catch(e){throw Error('发音未能播放，请再点击一次，或检查系统音量。');}
          if(result.cached)toast('使用本地缓存播放。');
        }finally{button.textContent=label+'发音';}
      })));group.append(button);row.append(group);
    }
    container.append(row);return row;
  }
  function renderSenses(word){
    senseToken++;
    const options=$('sense-options');options.replaceChildren();
    $('edit-study-meaning').value=word.study_meaning||'';
    const selected=new Set((word.study_meaning||'').split('\n').map(s=>s.trim()));
    for(const s of word.senses||[]){
      if(!s||typeof s.meaning!=='string')continue;
      const value=(s.pos?s.pos+' ':'')+s.meaning;
      const label=node('label','sense-option'),check=node('input');check.type='checkbox';check.value=value;check.checked=selected.has(value);
      check.addEventListener('change',()=>{
        $('edit-study-meaning').value=Array.from(options.querySelectorAll('input:checked')).map(c=>c.value).join('\n');state.draftVersion++;
      });label.append(check,node('span','',value));options.append(label);
    }
    $('editor-audio').replaceChildren();addAudio($('editor-audio'),word.word,word);
  }
  $('edit-study-meaning').addEventListener('input',()=>{
    state.draftVersion++;const selected=new Set($('edit-study-meaning').value.split('\n').map(s=>s.trim()));
    $('sense-options').querySelectorAll('input').forEach(c=>c.checked=selected.has(c.value));
  });
  $('reset-study-meaning').addEventListener('click',()=>{$('edit-study-meaning').value='';$('sense-options').querySelectorAll('input').forEach(c=>c.checked=false);state.draftVersion++;});
  for(const id of ['edit-meaning','edit-pos'])$(id).addEventListener('input',()=>{
    clearTimeout(senseTimer);const token=++senseToken;
    senseTimer=setTimeout(async()=>{
      try{
        const senses=await rpc('senses',{meaning:$('edit-meaning').value,pos:$('edit-pos').value});
        if(token!==senseToken||!state.draft)return;
        const current={...state.draft,senses,study_meaning:$('edit-study-meaning').value};state.draft.senses=senses;renderSenses(current);
      }catch(e){toast(e.message,true);}
    },220);
  });
  function settingPreview(){
    const count=Number($('setting-count').value)||0,n=Number($('setting-new').value),m=Number($('setting-meaning').value);
    $('new-ratio-label').textContent=n+'% 新词 / '+(100-n)+'% 旧词';
    $('meaning-ratio-label').textContent=m+'% 词义 / '+(100-m)+'% 拼写';
    const newCount=Math.floor((count*n+50)/100),meaningCount=Math.floor((count*m+50)/100);
    $('setting-preview').textContent='计划 '+count+' 个词：新词 '+newCount+'、旧词 '+(count-newCount)+'；词义 '+meaningCount+'、拼写 '+(count-meaningCount)+'。词库不足时按现有词补足。';
  }
  $('open-settings').addEventListener('click',()=>{
    $('setting-count').value=state.prefs.daily_count??10;$('setting-new').value=state.prefs.new_percent??50;
    $('setting-meaning').value=state.prefs.meaning_percent??50;$('setting-audio-cache').checked=!!state.prefs.audio_cache;
    settingPreview();$('settings-dialog').showModal();
  });
  for(const id of ['setting-count','setting-new','setting-meaning'])$(id).addEventListener('input',settingPreview);
  $('save-settings').addEventListener('click',safe(()=>busy($('save-settings'),async()=>{
    const count=Number($('setting-count').value);
    if(!Number.isInteger(count)||count<1||count>50)throw Error('每日数量请填写 1—50 的整数。');
    const changes={daily_count:count,new_percent:Number($('setting-new').value),meaning_percent:Number($('setting-meaning').value),audio_cache:$('setting-audio-cache').checked};
    const prefs=await rpc('preferences',changes);Object.assign(state.prefs,prefs);$('settings-dialog').close();
    await bootstrap();renderStudy();toast('学习设置已保存。已经生成的题组保持固定。');
  })));
  async function startPractice(mode){
    const session=await rpc('practice_start',{mode});
    if(!session){toast(mode==='weak'?'目前没有需要练习的薄弱词。':'本轮没有模糊或不认识的词，继续保持。');return;}
    state.practice=session;state.context='practice';state.quizId=null;state.revealed=false;state.quizAnswer='';navigate('study');
  }
  $('practice-wrong').addEventListener('click',safe(()=>busy($('practice-wrong'),()=>startPractice('daily_wrong'))));
  $('practice-weak').addEventListener('click',safe(()=>busy($('practice-weak'),()=>startPractice('weak'))));
  $('resume-practice').addEventListener('click',safe(async()=>{
    const session=await rpc('practice_get');if(!session){toast('没有未完成的专项练习。');return;}
    state.practice=session;state.context='practice';state.quizId=null;state.revealed=false;state.quizAnswer='';navigate('study');
  }));
  $('back-daily').addEventListener('click',()=>{state.context='daily';state.quizId=null;state.revealed=false;state.quizAnswer='';renderStudy();});
  function renderPracticeActions(){
    if(!state.boot)return;
    const daily=state.boot.questions;
    $('back-daily').hidden=state.context!=='practice';
    $('practice-wrong').hidden=state.context==='practice'||!daily.length||daily.some(q=>q.result===null);
    $('practice-weak').disabled=!state.boot.distribution.weak;
    $('resume-practice').hidden=state.context==='practice'||!state.boot.practice;
    $('practice-caption').textContent=state.context==='practice'?'专项单独记录，每日抽测结果保留。':'';
  }
  async function loadReport(){
    const r=await rpc('weekly');$('report-period').textContent=r.start+' 至 '+r.end+' · 最近 7 个本机自然日';
    const root=$('report-content');root.replaceChildren();
    const stats=node('div','weekly-stats');
    for(const [label,value,unit] of [['学习天数',r.study_days,'天'],['复习词数（去重）',r.reviewed_words,'词'],['作答次数',r.attempts,'次'],['完成每日题组',r.completed_daily,'组']]){
      const item=node('div','weekly-stat surface');item.append(node('span','muted small',label),node('strong','',value),node('span','muted small',unit));stats.append(item);
    }root.append(stats);
    const split=node('div','weekly-columns');
    const activity=node('section','weekly-panel surface');activity.append(node('h3','','这一周的学习足迹'),node('p','muted small','每条代表当天作答次数，含每日抽测和专项复测。'));
    const maximum=Math.max(1,...r.days.map(d=>d.attempts));
    for(const day of r.days){
      const row=node('div','activity-row'),track=node('div','activity-track'),bar=node('span');bar.style.width=(day.attempts/maximum*100)+'%';track.append(bar);
      row.append(node('span','small',day.day.slice(5).replace('-','/')),track,node('strong','small',day.attempts+' 次'));activity.append(row);
    }
    const accuracy=node('section','weekly-panel surface');accuracy.append(node('h3','','词义与拼写，分别看看'));
    for(const [key,label] of [['meaning','词义回忆'],['spelling','英文拼写']]){
      const a=r.accuracy[key],item=node('div','accuracy-line');
      item.append(node('span','',label),node('strong','',a.rate===null?'暂无记录':Math.round(a.rate*100)+'%'),node('span','muted small',a.attempts?'认识 '+a.correct+' / 作答 '+a.attempts+' 次':'尚无该题型记录'));accuracy.append(item);
    }
    accuracy.append(node('p','muted small','专项作答 '+r.practice_attempts+' 次；未标明词义/拼写的旧记录 '+r.other_attempts+' 次，不纳入这两种正确率。'));
    split.append(activity,accuracy);root.append(split);
    const mistakes=node('section','weekly-panel surface');mistakes.append(node('h3','','值得再看一眼的词'),node('p','muted small','模糊和不认识都计入待巩固；按本周出现次数排列。'));
    if(!r.missed.length)mistakes.append(node('p','weekly-empty muted',r.attempts?'本周暂时没有待巩固记录。':'这一周还没有学习记录。完成抽测后，这里会自然积累。'));
    for(const m of r.missed){
      const row=node('div','weekly-mistake'),button=node('button','word-link',m.word);button.addEventListener('click',safe(()=>showDetail(m.word_id)));
      row.append(button,node('span','muted small','模糊 '+m.fuzzy+' · 不认识 '+m.wrong),node('span','badge',m.misses+' 次'));mistakes.append(row);
    }root.append(mistakes);
  }
  $('refresh-report').addEventListener('click',safe(()=>busy($('refresh-report'),loadReport)));
  window.addEventListener('beforeunload',stopAudio);
  return {renderSenses,addAudio,stopAudio,renderPracticeActions,loadReport};
};
