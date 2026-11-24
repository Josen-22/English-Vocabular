from datetime import date
from pathlib import Path
import tempfile
import ctypes
import tkinter as tk
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlparse
from queue import Queue

from store import Store
from ui import App
from lookup import LookupResult, Sense

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except (AttributeError,OSError):
    pass


class ManualWorker:
    def __init__(self):
        self.results=Queue()
        self.requests=[]

    def submit(self,token,query):
        self.requests.append((token,query))

    def close(self):
        pass


class UITests(unittest.TestCase):
    def setUp(self):
        (Path(__file__).resolve().parents[2]/'验证').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'验证')
        self.home=Path(self.temp.name)
        self.store=Store(self.home/'test.sqlite3',today=lambda:date(2026,11,24))
        self.root=tk.Tk()
        self.root.withdraw()
        self.app=App(self.root,self.store,self.home)
        self.app.lookup_worker.close()
        self.app.lookup_worker=ManualWorker()
        self.root.update_idletasks()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_editor_duplicate_search_and_browser_link(self):
        a=self.app
        a.word_var.set('come out')
        a.meaning_text.insert('1.0','出现')
        a.pos_var.set('phr.')
        a.save_editor()
        self.assertEqual(len(self.store.words()),1)
        a.word_var.set('COME OUT')
        a.detect_duplicate()
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'出现')
        a.meaning_text.delete('1.0','end')
        a.meaning_text.insert('1.0','出版')
        a.save_editor()
        self.assertEqual(self.store.words()[0]['meaning'],'出版')
        a.search_var.set('不存在')
        self.assertEqual(len(a.word_tree.get_children()),0)
        a.search_var.set('出版')
        self.assertEqual(len(a.word_tree.get_children()),1)
        a.word_var.set('come out & about')
        with patch('ui.webbrowser.open',return_value=True) as browser:
            a.open_dictionary_page()
            url=browser.call_args.args[0]
            self.assertEqual(urlparse(url).hostname,'dict.youdao.com')
            self.assertIn('come out & about',unquote(urlparse(url).path))

    def deliver(self,result=None,error=None,request=None):
        a=self.app
        token,query=request or a.lookup_worker.requests[-1]
        a.lookup_worker.results.put((token,query,result,error))
        self.root.after_cancel(a.lookup_timer)
        a.poll_lookup()

    def result(self,query='retain'):
        return LookupResult(query,query,(Sense('v.','保持；保留'),),f'https://dict.youdao.com/w/eng/{query}/')

    def test_lookup_fills_fields_but_only_save_writes_database(self):
        a=self.app
        a.word_var.set('retain')
        a.notes_text.insert('1.0','自己的备注')
        a.lookup()
        self.assertEqual(str(a.lookup_button['state']),'disabled')
        self.deliver(self.result())
        self.assertEqual(a.pos_var.get(),'v.')
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'v. 保持；保留')
        self.assertIn('有道词典',a.source_var.get())
        self.assertEqual(a.notes_text.get('1.0','end').strip(),'自己的备注')
        self.assertEqual(self.store.words(),[])
        a.save_editor()
        self.assertEqual(len(self.store.words()),1)
        self.assertEqual(self.store.words()[0]['notes'],'自己的备注')

    def test_lookup_error_and_user_edits_preserve_form(self):
        a=self.app
        a.word_var.set('retain')
        a.meaning_text.insert('1.0','已有内容')
        a.lookup()
        self.deliver(error='连接有道失败')
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'已有内容')
        self.assertIn('连接有道失败',a.lookup_status.get())
        a.lookup()
        a.meaning_text.insert('end','新的编辑')
        self.deliver(self.result())
        self.assertIn('新的编辑',a.meaning_text.get('1.0','end'))
        self.assertIn('未覆盖',a.lookup_status.get())

    def test_stale_results_are_ignored_after_word_change_clear_or_save(self):
        a=self.app
        a.word_var.set('retain')
        a.lookup()
        first=a.lookup_worker.requests[-1]
        a.word_var.set('firm')
        a.lookup()
        second=a.lookup_worker.requests[-1]
        self.deliver(self.result(),request=first)
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'')
        self.assertEqual(str(a.lookup_button['state']),'disabled')
        self.deliver(self.result('firm'),request=second)
        self.assertIn('保持',a.meaning_text.get('1.0','end'))
        a.word_var.set('retain')
        a.lookup()
        last=a.lookup_worker.requests[-1]
        a.clear_editor()
        self.deliver(self.result(),request=last)
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'')
        a.word_var.set('retain')
        a.meaning_text.insert('1.0','保存我的内容')
        a.lookup()
        last=a.lookup_worker.requests[-1]
        a.save_editor()
        self.deliver(self.result(),request=last)
        self.assertEqual(self.store.find_word('retain')['meaning'],'保存我的内容')
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'')

    def test_existing_word_is_local_and_requery_previews_before_replace(self):
        ident=self.store.save_word('retain','旧释义',notes='学习笔记')
        with self.store.conn:
            self.store.conn.execute('UPDATE words SET mastery=4 WHERE id=?',(ident,))
        a=self.app
        a.word_var.set('retain')
        a.lookup()
        self.assertEqual(a.lookup_worker.requests,[])
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'旧释义')
        a.lookup(force=True)
        self.deliver(self.result())
        self.assertIsNotNone(a.preview_window)
        self.assertEqual(a.meaning_text.get('1.0','end').strip(),'旧释义')
        actions=a.preview_window.winfo_children()[0]
        actions.winfo_children()[0].invoke()
        self.assertIn('保持',a.meaning_text.get('1.0','end'))
        self.assertEqual(self.store.find_word('retain')['meaning'],'旧释义')
        a.save_editor()
        self.assertEqual(self.store.find_word('retain')['mastery'],4)
        self.assertEqual(self.store.find_word('retain')['notes'],'学习笔记')

    def test_scaling_layout_keeps_save_button_visible_and_long_meaning_scrolls(self):
        from ui import window_size
        a=self.app
        for scale in (1,1.5,2):
            with self.subTest(scale=scale):
                self.root.tk.call('tk','scaling',scale*96/72)
                width,height,_=window_size(self.root)
                self.root.geometry(f'{width}x{height}')
                a.notebook.select(a.add_tab)
                self.root.update_idletasks()
                self.assertGreater(width,min(700*scale,self.root.winfo_screenwidth()-100*scale))
                self.assertLessEqual(height,self.root.winfo_screenheight())
                # Withdrawn windows retain geometry without stealing desktop focus.
                self.assertLessEqual(a.save_button.winfo_y()+a.save_button.winfo_height(),a.save_button.master.winfo_height())
                a.meaning_text.delete('1.0','end')
                a.meaning_text.insert('1.0','长释义\n'*200)
                a.meaning_text.yview_moveto(1)
                self.assertGreater(a.meaning_text.yview()[0],0)

    def test_both_question_flows_and_summary(self):
        for n in range(10):
            self.store.save_word(f'word {n}',f'释义 {n}')
        a=self.app
        a.start_quiz()
        kinds=set()
        for _ in range(10):
            q=a.current_question
            kinds.add(q['kind'])
            self.assertEqual(str(a.grade_buttons['认识']['state']),'disabled')
            if q['kind']=='spelling':
                a.quiz_answer.set(' '+q['word'].upper()+' ')
            a.reveal_answer()
            self.assertEqual(str(a.grade_buttons['认识']['state']),'normal')
            a.grade('认识')
            self.root.update_idletasks()
        self.assertEqual(kinds,{'meaning','spelling'})
        self.assertIsNone(a.current_question)
        self.assertEqual(len(self.store.reviews()),10)
        a.render_quiz()
        self.assertIsNone(a.current_question)


if __name__=='__main__':
    unittest.main(verbosity=2)
