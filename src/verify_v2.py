"""Exercise the actual WebView2 runtime, bridge and live Youdao fetch in isolation."""
from datetime import datetime
from pathlib import Path
import json
import sys
import tempfile
import time
import traceback

from bridge import Bridge
from desktop import load_html,resource_path
from store import Store


def run(home):
    import webview
    home=Path(home)
    report={'ok':False,'frozen':bool(getattr(sys,'frozen',False)),'time':datetime.now().isoformat(),'themes':[]}
    temporary=tempfile.TemporaryDirectory(prefix='webview-check_',dir=home/'验证')
    test_home=Path(temporary.name)
    s=Store(test_home/'数据'/'单词本.sqlite3')
    for word in ('alpha','beta','gamma'):
        s.save_word(word,'验收词条')
    s.close()
    bridge=Bridge(test_home)
    window=webview.create_window('第二版隔离验收',html=load_html(),js_api=bridge,
                    width=1120,height=800,min_size=(760,580),hidden=True,focus=False)
    bridge._window=window

    def wait_js(expression,seconds=20):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if window.evaluate_js(expression):return
            time.sleep(.1)
        raise RuntimeError('窗口验收超时：'+expression)

    def check():
        try:
            wait_js("document.documentElement.dataset.appReady === 'true'")
            report['bridge_ready']=True
            wait_js("document.querySelector('.brand-mark').complete && document.querySelector('.brand-mark').naturalWidth===256")
            report['brand_icon_loaded']=True
            report['native_icon_size']=[window.native.Icon.Width,window.native.Icon.Height]
            assert window.native.Icon.Width>0
            # Hidden windows pause animation frames; measure final palette values.
            window.evaluate_js("document.body.style.transition='none'")
            for theme in ('clean','paper','focus'):
                window.evaluate_js("document.getElementById('theme-select').value="+json.dumps(theme)+";document.getElementById('theme-select').dispatchEvent(new Event('change'))")
                deadline=time.monotonic()+5
                while bridge._settings.read()['theme']!=theme and time.monotonic()<deadline:time.sleep(.05)
                assert bridge._settings.read()['theme']==theme
                time.sleep(.25)
                report['themes'].append({'theme':theme,'background':window.evaluate_js('getComputedStyle(document.body).backgroundColor')})
            assert len({theme['background'] for theme in report['themes']})==3
            window.evaluate_js("document.querySelector('[data-nav=lookup]').click();document.getElementById('query').value='retain';document.getElementById('lookup-button').click()")
            wait_js("!document.getElementById('editor').hidden && document.getElementById('edit-meaning').value.length>0",15)
            report['live_lookup']=window.evaluate_js("({word:document.getElementById('edit-word').value,meaning:document.getElementById('edit-meaning').value})")
            assert '保留' in report['live_lookup']['meaning']
            window.evaluate_js("document.getElementById('edit-study-meaning').value='v. 保留'")
            window.evaluate_js("document.getElementById('save-button').click()")
            wait_js("document.getElementById('lookup-feedback').textContent.includes('已保存')")
            assert len(bridge.call('words')['data'])==4
            stored=next(w for w in bridge.call('words')['data'] if w['word']=='retain')
            assert stored['study_meaning']=='v. 保留' and stored['uk_phonetic'] and stored['us_phonetic']
            report['learning_meaning_and_phonetics']=True
            window.evaluate_js("document.querySelector('[data-nav=library]').click();document.getElementById('sort-select').value='az';document.getElementById('sort-select').dispatchEvent(new Event('change'))")
            wait_js("document.querySelector('.word-card-title')?.textContent === 'alpha'")
            report['sort_verified']=True
            window.evaluate_js("document.getElementById('table-view').click()")
            wait_js("!document.getElementById('word-table-wrap').hidden && document.querySelectorAll('#word-table tbody tr').length===4")
            report['table_verified']=True
            assert bridge._settings.read()['view']=='table'
            window.evaluate_js("document.getElementById('open-settings').click();document.getElementById('setting-count').value='2';document.getElementById('setting-meaning').value='100';document.getElementById('setting-audio-cache').checked=true;document.getElementById('save-settings').click()")
            wait_js("!document.getElementById('settings-dialog').open")
            assert bridge._settings.read()['daily_count']==2
            report['learning_settings_verified']=True
            for accent in ('uk','us'):
                audio=bridge.call('pronounce',{'word':'retain','accent':accent})
                assert audio['ok'] and audio['data']['audio']
            from unittest.mock import patch
            from urllib.error import URLError
            with patch('pronunciation.urlopen',side_effect=URLError('offline')):
                audio=bridge.call('pronounce',{'word':'retain','accent':'uk'})
                assert audio['ok'] and audio['data']['cached']
            # Offline decoding requires neither visible media playback nor sound output.
            window.evaluate_js("window.__audioDecoded=null;window.__decodeContext=new OfflineAudioContext(1,1,44100);window.__decodeContext.decodeAudioData(Uint8Array.from(atob("+json.dumps(audio['data']['audio'])+"),c=>c.charCodeAt(0)).buffer).then(b=>window.__audioDecoded=b.duration>0).catch(e=>{window.__audioDecoded=false;window.__audioError=e.message})")
            wait_js('window.__audioDecoded !== null',10)
            assert window.evaluate_js('window.__audioDecoded === true')
            report['audio_fetch_cache_and_decode']=True
            window.evaluate_js("document.querySelector('[data-nav=study]').click();document.getElementById('start-quiz-button').click()")
            wait_js("document.getElementById('reveal-answer')!==null")
            assert len(bridge.call('bootstrap')['data']['questions'])==2
            for index,result in enumerate(('不认识','认识')):
                window.evaluate_js("document.getElementById('reveal-answer').click()")
                wait_js("Array.from(document.querySelectorAll('[data-grade]')).some(b=>b.offsetParent!==null)")
                window.evaluate_js("document.querySelector('[data-grade="+result+"]').click()")
                wait_js("document.getElementById('progress-label').textContent.startsWith('"+str(index+1)+" /')")
            report['quiz_verified']=True
            daily=bridge.call('bootstrap')['data']['questions']
            window.evaluate_js("document.getElementById('practice-wrong').click()")
            wait_js("document.getElementById('study-title').textContent.includes('模糊') && document.getElementById('reveal-answer')!==null")
            window.evaluate_js("document.getElementById('reveal-answer').click()")
            wait_js("Array.from(document.querySelectorAll('[data-grade]')).some(b=>b.offsetParent!==null)")
            window.evaluate_js("document.querySelector('[data-grade=认识]').click()")
            wait_js("document.getElementById('study-content').textContent.includes('这一轮专项完成了')")
            assert daily==bridge.call('bootstrap')['data']['questions']
            report['practice_independent']=True
            window.evaluate_js("document.querySelector('[data-nav=report]').click()")
            wait_js("document.querySelectorAll('.activity-row').length===7")
            weekly=bridge.call('weekly')['data']
            assert weekly['attempts']==3 and weekly['practice_attempts']==1
            report['weekly_report_verified']=True
            report['settings_persisted']=bridge.call('bootstrap')['data']['preferences']
            report['ok']=True
        except Exception:
            report['error']=traceback.format_exc()
            try:report['page_status']=window.evaluate_js("({status:document.getElementById('connection-status')?.textContent,lookup:document.getElementById('lookup-feedback')?.textContent,toast:document.getElementById('toast')?.textContent})")
            except Exception:pass
        finally:
            (home/'验证'/'第二版打包验收.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            window.destroy()
    try:
        webview.start(check,gui='edgechromium',debug=False,private_mode=True,icon=str(resource_path('assets/vocab-icon.ico')))
    finally:
        temporary.cleanup()
    return 0 if report['ok'] else 1
