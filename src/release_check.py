"""Opt-in installed-executable check, entirely on isolated temporary data.

Creates transparent Tk windows to measure actual layout without desktop input,
and exercises the same background lookup and save flow as the product.
"""
from datetime import datetime
from pathlib import Path
import json
import sys
import tempfile
import time
import traceback
import tkinter as tk

from store import Store
from ui import App


def _inside(root, widget):
    x = widget.winfo_rootx()-root.winfo_rootx()
    y = widget.winfo_rooty()-root.winfo_rooty()
    return bool(widget.winfo_ismapped() and x>=0 and y>=0 and
                x+widget.winfo_width() <= root.winfo_width() and
                y+widget.winfo_height() <= root.winfo_height())


def run(home):
    home = Path(home)
    report = {'ok':False,'frozen':bool(getattr(sys,'frozen',False)),
              'time':datetime.now().isoformat(),'layout':[],'live_lookup':[]}
    root = app = store = None
    try:
        with tempfile.TemporaryDirectory(prefix='release_',dir=home) as temp:
            for scale in (1,1.5,2):
                root = tk.Tk()
                root.withdraw()
                root.attributes('-alpha',0)
                root.tk.call('tk','scaling',scale*96/72)
                store = Store(Path(temp)/f'layout_{scale}.sqlite3')
                app = App(root,store,temp)
                app.notebook.select(app.add_tab)
                root.deiconify()
                root.update()
                controls = {'save_visible':_inside(root,app.save_button),
                            'lookup_visible':_inside(root,app.lookup_button)}
                assert all(controls.values()),f'缩放 {scale} 时控件裁切：{controls}'
                app.meaning_text.insert('1.0','长释义测试\n'*200)
                root.update()
                app.meaning_text.yview_moveto(1)
                assert app.meaning_text.yview()[0]>0,'长释义不能滚动'
                report['layout'].append({'scale':scale,'window':[root.winfo_width(),root.winfo_height()],**controls})
                app.clear_editor()
                if scale == 2:
                    for query in ('retain','firm','come out'):
                        app.word_var.set(query)
                        app.lookup()
                        deadline=time.monotonic()+15
                        while app.pending_lookup is not None and time.monotonic()<deadline:
                            root.update()
                            time.sleep(0.01)
                        meaning=app.meaning_text.get('1.0','end').strip()
                        assert meaning,app.lookup_status.get() or '查询超时'
                        assert not store.words(search=query),'查询尚未确认就已入库'
                        report['live_lookup'].append({'query':query,'pos':app.pos_var.get(),'meaning':meaning})
                        app.save_editor()
                        assert store.find_word(query)['meaning']==meaning,'保存的释义不一致'
                    assert len(store.words())==3
                    # Exercise long dictionary meanings inside the quiz panel.
                    store.save_word('long entry','长释义；'*1000)
                    app.start_quiz()
                    while app.current_question:
                        app.reveal_answer()
                        app.grade('认识')
                    assert len(store.reviews())==4
                    report['quiz_flow']=True
                app.close()
                root = app = store = None
        report['ok']=True
    except Exception:
        report['error']=traceback.format_exc()
        if app is not None:
            app.close()
        elif root is not None:
            root.destroy()
            if store is not None:
                store.close()
    (home/'打包验收.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1
