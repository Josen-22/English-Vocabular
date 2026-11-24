"""A narrow in-process bridge from bundled UI to existing local services."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import RLock
import logging
import webbrowser

from excel_io import import_workbook,export_workbook
from library import select_words,distribution
from lookup import fetch_youdao,dictionary_url
from preferences import Preferences
from store import Store,spelling_matches


class Bridge:
    def __init__(self,home,store_factory=Store):
        self._home=Path(home)
        self._db=self._home/'数据'/'单词本.sqlite3'
        self._settings=Preferences(self._home/'数据'/'界面设置.json')
        self._lock=RLock()
        self._window=None
        self._store_factory=store_factory

    def call(self,action,payload=None):
        handlers={
            'bootstrap':self._bootstrap,'words':self._words,'lookup':self._lookup,
            'save':self._save,'delete':self._delete,'history':self._history,
            'start':self._start,'answer':self._answer,'check':self._check,'preferences':self._preferences,
            'backup':self._backup,'restore':self._restore,'import':self._import,
            'export':self._export,'open_dictionary':self._open_dictionary,
        }
        try:
            if action not in handlers or (payload is not None and not isinstance(payload,dict)):
                raise ValueError('不支持的操作。')
            if action=='lookup':
                return {'ok':True,'data':self._lookup(payload or {})}
            with self._lock:
                data=handlers[action](payload or {})
            return {'ok':True,'data':data}
        except Exception as exc:
            logging.exception('桌面操作失败：%s',action)
            return {'ok':False,'error':str(exc) or '操作未完成，请重试。'}

    def _store(self):
        # pywebview calls arrive on worker threads; each call owns its connection.
        return closing(self._store_factory(self._db))

    def _bootstrap(self,p):
        with self._store() as s:
            questions=[dict(q) for q in s.questions()]
            rows=s.words()
            return {'today':s.today().isoformat(),'stats':s.stats(),'distribution':distribution(rows),
                    'questions':questions,'preferences':self._settings.read()}

    def _words(self,p):
        with self._store() as s:
            return select_words(s.words(),s.today().isoformat(),p.get('search',''),p.get('filter','all'),p.get('sort','added_desc'))

    def _lookup(self,p):
        word=str(p.get('word','')).strip()
        if not p.get('refresh'):
            with self._lock,self._store() as s:
                existing=s.find_word(word)
                if existing:
                    return {'existing':True,'word':dict(existing)}
        result=fetch_youdao(word)
        return {'existing':False,'word':{'word':word,'pos':result.pos,'meaning':result.meaning,
                'source':'有道词典 · '+result.source_url,'notes':''},'headword':result.headword}

    def _save(self,p):
        with self._store() as s:
            ident=p.get('id')
            if ident is not None:
                ident=int(ident)
            ident=s.save_word(str(p.get('word','')),str(p.get('meaning','')),str(p.get('pos','')),
                              str(p.get('source','')),str(p.get('notes','')),ident)
            return dict(s.get_word(ident))

    def _delete(self,p):
        with self._store() as s:
            s.delete_word(int(p['id']))
        return True

    def _history(self,p):
        with self._store() as s:
            ident=int(p['id'])
            word=s.get_word(ident)
            if word is None:
                raise ValueError('词条不存在。')
            return {'word':dict(word),'reviews':[dict(r) for r in s.reviews(ident)]}

    def _start(self,p):
        with self._store() as s:
            return [dict(q) for q in s.start_day()]

    def _answer(self,p):
        with self._store() as s:
            q=s.conn.execute('SELECT * FROM questions WHERE id=?',(int(p['id']),)).fetchone()
            if q is None:
                raise ValueError('题目不存在。')
            s.answer(q['id'],str(p.get('answer','')),str(p['result']))
            return [dict(row) for row in s.questions()]

    def _check(self,p):
        with self._store() as s:
            q=s.conn.execute('SELECT * FROM questions WHERE id=?',(int(p['id']),)).fetchone()
            if q is None:
                raise ValueError('题目不存在。')
            return {'matches':spelling_matches(str(p.get('answer','')),q['word'])}

    def _preferences(self,p):
        return self._settings.update(p)

    def _backup(self,p):
        with self._store() as s:
            path=self._home/'备份'/('手动备份_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
            s.backup(path)
            return {'path':str(path)}

    def _dialog(self,save,kind):
        if self._window is None:
            raise ValueError('尚未连接桌面窗口。')
        import webview
        directory=self._home/'备份' if kind=='database' else self._home
        directory.mkdir(parents=True,exist_ok=True)
        types=('单词本备份 (*.sqlite3)',) if kind=='database' else ('Excel 工作簿 (*.xlsx)',)
        result=self._window.create_file_dialog(webview.FileDialog.SAVE if save else webview.FileDialog.OPEN,
                    directory=str(directory),allow_multiple=False,
                    save_filename=('单词本_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.xlsx') if save else '',file_types=types)
        if not result:
            return None
        return Path(result[0] if isinstance(result,(tuple,list)) else result)

    def _restore(self,p):
        path=self._dialog(False,'database')
        if path is None:
            return {'cancelled':True}
        with self._store() as s:
            safety=s.restore(path,self._home/'备份')
            return {'safety':str(safety)}

    def _import(self,p):
        path=self._dialog(False,'excel')
        if path is None:
            return {'cancelled':True}
        with self._store() as s:
            s.backup(self._home/'备份'/('导入前_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3'))
            return import_workbook(s,path)

    def _export(self,p):
        path=self._dialog(True,'excel')
        if path is None:
            return {'cancelled':True}
        if path.resolve()==(self._home.parent/'雅思迭代单词本.xlsx').resolve():
            raise ValueError('请使用新的文件名，保留原 Excel 存档。')
        with self._store() as s:
            export_workbook(s,path)
        return {'path':str(path)}

    def _open_dictionary(self,p):
        if not webbrowser.open(dictionary_url(str(p.get('word','')))):
            raise ValueError('无法打开系统浏览器。')
        return True
