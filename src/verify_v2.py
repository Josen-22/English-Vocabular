"""Exercise the actual WebView2 runtime, bridge and live Youdao fetch in isolation."""
from datetime import datetime
from pathlib import Path
import json
import sys
import tempfile
import time
import traceback

from bridge import Bridge
from desktop import load_html
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
            window.evaluate_js("document.getElementById('save-button').click()")
            wait_js("document.getElementById('lookup-feedback').textContent.includes('已保存')")
            assert len(bridge.call('words')['data'])==4
            window.evaluate_js("document.querySelector('[data-nav=library]').click();document.getElementById('sort-select').value='az';document.getElementById('sort-select').dispatchEvent(new Event('change'))")
            wait_js("document.querySelector('.word-card-title')?.textContent === 'alpha'")
            report['sort_verified']=True
            window.evaluate_js("document.getElementById('table-view').click()")
            wait_js("!document.getElementById('word-table-wrap').hidden && document.querySelectorAll('#word-table tbody tr').length===4")
            report['table_verified']=True
            assert bridge._settings.read()['view']=='table'
            window.evaluate_js("document.querySelector('[data-nav=study]').click();document.getElementById('start-quiz-button').click()")
            wait_js("document.getElementById('reveal-answer')!==null")
            window.evaluate_js("document.getElementById('reveal-answer').click()")
            wait_js("Array.from(document.querySelectorAll('[data-grade]')).some(b=>b.offsetParent!==null)")
            window.evaluate_js("document.querySelector('[data-grade=认识]').click()")
            wait_js("document.getElementById('progress-label').textContent.startsWith('1 /')")
            report['quiz_verified']=True
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
        webview.start(check,gui='edgechromium',debug=False,private_mode=True)
    finally:
        temporary.cleanup()
    return 0 if report['ok'] else 1
