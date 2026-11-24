"""Chinese desktop vocabulary book with explicit, asynchronous Youdao lookup."""
from datetime import datetime
from pathlib import Path
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from queue import Empty
import webbrowser

from excel_io import import_workbook, export_workbook
from store import spelling_matches
from lookup import DictionaryError, LookupWorker, dictionary_url, fetch_youdao, normalize_query

BG = '#F5F4EF'
INK = '#243B38'
ACCENT = '#245F58'


def window_size(root, width=1000, height=820):
    """Tk fonts use points; window geometry uses physical pixels on Windows."""
    scale = max(1.0, root.winfo_fpixels('1i') / 96)
    available_w = max(400, root.winfo_screenwidth()-round(50*scale))
    available_h = max(400, root.winfo_screenheight()-round(85*scale))
    return min(round(width*scale),available_w), min(round(height*scale),available_h), scale


class ScrollPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self,background=BG,highlightthickness=0,width=1,height=1)
        bar = ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y')
        self.canvas.pack(side='left',fill='both',expand=True)
        self.body = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda event:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',self.resize_body)

    def resize_body(self, event):
        self.canvas.itemconfigure(self.item,width=max(1,event.width))

class App:
    def __init__(self, root, store, home):
        self.root, self.store, self.home = root, store, Path(home)
        self.edit_id = None
        self.current_question = None
        self.quiz_day = store.today()
        self.revealed = False
        self.closed = False
        self.lookup_generation = 0
        self.pending_lookup = None
        self.preview_window = None
        self.lookup_worker = LookupWorker(lambda query:fetch_youdao(query))
        self.status = tk.StringVar(value='所有学习记录均保存在本机。')
        root.title('本地单词本 · 有道版')
        width,height,self.scale = window_size(root)
        root.geometry(f'{width}x{height}')
        root.minsize(min(width,round(740*self.scale)), min(height,round(590*self.scale)))
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 11), background=BG, foreground=INK)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG)
        style.configure('Muted.TLabel', foreground='#667772')
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 25, 'bold'))
        style.configure('Heading.TLabel', font=('Microsoft YaHei UI', 17, 'bold'))
        style.configure('Word.TLabel', font=('Microsoft YaHei UI', 25, 'bold'))
        style.configure('TButton', padding=(15, 9))
        style.configure('Primary.TButton', background=ACCENT, foreground='white')
        style.map('Primary.TButton', background=[('active', '#34766B'), ('disabled', '#A8B8B2')])
        style.configure('TNotebook', borderwidth=0, tabmargins=(0, 0, 0, 10))
        style.configure('TNotebook.Tab', padding=(25, 12))
        style.map('TNotebook.Tab', background=[('selected', '#E2ECE5')])
        style.configure('Treeview', rowheight=round(34*self.scale), background='white', fieldbackground='white', font=('Microsoft YaHei UI', 10))
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10, 'bold'), padding=8)
        shell = ttk.Frame(root, padding=(28, 22))
        shell.pack(fill='both', expand=True)
        shell.columnconfigure(0,weight=1)
        shell.rowconfigure(2,weight=1)
        head = ttk.Frame(shell)
        head.grid(row=0,column=0,sticky='ew')
        ttk.Label(head, text='本地单词本', style='Title.TLabel').pack(side='left')
        ttk.Label(head, text='查一个词，记一点进步。', style='Muted.TLabel').pack(side='right', pady=12)
        self.stats_var = tk.StringVar()
        stats_label = ttk.Label(shell, textvariable=self.stats_var, style='Muted.TLabel')
        stats_label.grid(row=1,column=0,sticky='ew',pady=(8,18))
        stats_label.bind('<Configure>',lambda event:stats_label.configure(wraplength=max(100,event.width)))
        self.notebook = ttk.Notebook(shell)
        self.notebook.grid(row=2,column=0,sticky='nsew')
        self.quiz_tab, self.add_tab, self.list_tab = [ttk.Frame(self.notebook, padding=(15,12)) for _ in range(3)]
        for frame, title in zip((self.quiz_tab,self.add_tab,self.list_tab), ('今日抽测','查词收录','我的单词本')):
            self.notebook.add(frame, text=title)
        self.build_editor()
        self.build_list()
        footer = ttk.Frame(shell)
        footer.grid(row=3,column=0,sticky='ew',pady=(14,0))
        footer.columnconfigure(0,weight=1)
        status_label = ttk.Label(footer, textvariable=self.status, style='Muted.TLabel')
        status_label.grid(row=0,column=0,sticky='ew',padx=(0,10))
        status_label.bind('<Configure>',lambda event:status_label.configure(wraplength=max(100,event.width)))
        ttk.Button(footer, text='数据与备份 ▾', command=self.show_data_menu).grid(row=0,column=1)
        self.menu = tk.Menu(root, tearoff=False, font=('Microsoft YaHei UI',11))
        for label, command in [('导入 Excel 单词本…',self.import_file),('导出 Excel…',self.export_file),
                               ('完整备份…',self.backup_file),('从备份恢复…',self.restore_file),
                               ('打开数据文件夹',self.open_data_folder),('使用说明',self.show_help)]:
            self.menu.add_command(label=label, command=command)
        self.notebook.bind('<<NotebookTabChanged>>', self.tab_changed)
        root.bind_all('<MouseWheel>',self.scroll_wheel)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_stats()
        self.refresh_list()
        self.render_quiz()
        self.timer = root.after(15000, self.check_day)
        self.lookup_timer = root.after(80,self.poll_lookup)

    def scroll_wheel(self, event):
        widget = self.root.winfo_containing(event.x_root,event.y_root)
        if isinstance(widget,tk.Text):
            return  # Text widgets keep their own scrolling.
        while widget is not None:
            if isinstance(widget,ScrollPanel):
                widget.canvas.yview_scroll(-int(event.delta/120),'units')
                return
            widget = getattr(widget,'master',None)

    def refresh_stats(self):
        s = self.store.stats()
        self.stats_var.set(f'{self.store.today():%Y年%m月%d日}    ·    共 {s["total"]} 个词    ·    未测新词 {s["new"]} 个    ·    到期旧词 {s["due"]} 个')

    def tab_changed(self, event=None):
        self.check_day(reschedule=False)
        if self.notebook.select() == str(self.list_tab):
            self.refresh_list()

    def check_day(self, reschedule=True):
        if self.quiz_day != self.store.today():
            self.quiz_day = self.store.today()
            self.refresh_stats()
            self.render_quiz()
            self.status.set('新的一天，可以开始今天的 10 词抽测。')
        if reschedule:
            self.timer = self.root.after(15000, self.check_day)

    def build_editor(self):
        actions = ttk.Frame(self.add_tab)
        actions.pack(side='bottom',fill='x',pady=(10,0))
        self.save_button = ttk.Button(actions,text='收入单词本',style='Primary.TButton',command=self.save_editor)
        self.save_button.pack(side='left')
        ttk.Button(actions,text='新建 / 清空',command=self.clear_editor).pack(side='left',padx=12)
        self.editor_panel = ScrollPanel(self.add_tab)
        self.editor_panel.pack(fill='both',expand=True)
        body = self.editor_panel.body
        ttk.Label(body, text='查一个词，一键收进来', style='Heading.TLabel').pack(anchor='w', pady=(0,12))
        self.editor_title = tk.StringVar(value='新词条')
        ttk.Label(body, textvariable=self.editor_title, style='Muted.TLabel').pack(anchor='w')
        form = ttk.Frame(body)
        form.pack(fill='both', expand=True, pady=10,padx=(0,10))
        form.columnconfigure(1, weight=1)
        self.word_var, self.pos_var, self.source_var = tk.StringVar(),tk.StringVar(),tk.StringVar()
        ttk.Label(form,text='单词 / 短语 *').grid(row=0,column=0,sticky='nw',padx=(0,18),pady=8)
        word_row = ttk.Frame(form)
        word_row.grid(row=0,column=1,sticky='ew')
        self.word_entry = ttk.Entry(word_row,textvariable=self.word_var,font=('Microsoft YaHei UI',14),width=15)
        self.word_entry.pack(side='left',fill='x',expand=True,ipady=5)
        self.word_entry.bind('<FocusOut>',self.detect_duplicate)
        self.word_entry.bind('<Return>',lambda event:self.lookup())
        self.lookup_button = ttk.Button(word_row,text='有道查词',style='Primary.TButton',command=self.lookup)
        self.lookup_button.pack(side='left',padx=(10,0))
        links = ttk.Frame(form)
        links.grid(row=1,column=1,sticky='ew',pady=(4,8))
        self.requery_button = ttk.Button(links,text='重新查询有道',command=lambda:self.lookup(force=True))
        self.requery_button.pack(side='left')
        ttk.Button(links,text='查看有道原网页 ↗',command=self.open_dictionary_page).pack(side='left',padx=(8,0))
        self.lookup_status = tk.StringVar(value='输入单词或短语后查词，软件会自动填好词性与释义。')
        hint = ttk.Label(form,textvariable=self.lookup_status,style='Muted.TLabel')
        hint.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(0,12))
        hint.bind('<Configure>',lambda event:hint.configure(wraplength=max(100,event.width)))
        ttk.Label(form,text='词性').grid(row=3,column=0,sticky='w',pady=8)
        ttk.Entry(form,textvariable=self.pos_var).grid(row=3,column=1,sticky='ew',ipady=4)
        ttk.Label(form,text='中文释义 *').grid(row=4,column=0,sticky='nw',pady=8)
        meaning_box = ttk.Frame(form)
        meaning_box.grid(row=4,column=1,sticky='nsew',pady=5)
        self.meaning_text = tk.Text(meaning_box,height=5,width=20,wrap='word',font=('Microsoft YaHei UI',12),relief='solid',bd=1)
        meaning_scroll = ttk.Scrollbar(meaning_box,command=self.meaning_text.yview)
        self.meaning_text.configure(yscrollcommand=meaning_scroll.set)
        meaning_scroll.pack(side='right',fill='y')
        self.meaning_text.pack(side='left',fill='both',expand=True)
        ttk.Label(form,text='来源').grid(row=5,column=0,sticky='w',pady=8)
        ttk.Entry(form,textvariable=self.source_var).grid(row=5,column=1,sticky='ew',ipady=4)
        ttk.Label(form,text='备注').grid(row=6,column=0,sticky='nw',pady=8)
        self.notes_text = tk.Text(form,height=3,width=20,wrap='word',font=('Microsoft YaHei UI',11),relief='solid',bd=1)
        self.notes_text.grid(row=6,column=1,sticky='nsew',pady=5)
        self.word_var.trace_add('write',self.invalidate_lookup)

    def invalidate_lookup(self, *args):
        self.lookup_generation += 1
        self.pending_lookup = None
        self.lookup_status.set('')
        self.lookup_button.configure(text='有道查词',state='normal')
        self.requery_button.configure(state='normal')
        if self.preview_window is not None:
            self.preview_window.destroy()
            self.preview_window = None

    def editor_signature(self):
        return (self.word_var.get(), self.pos_var.get(), self.source_var.get(),
                self.meaning_text.get('1.0','end').strip(),self.notes_text.get('1.0','end').strip(),self.edit_id)

    def clear_editor(self):
        self.invalidate_lookup()
        self.edit_id = None
        self.editor_title.set('新词条')
        for var in (self.word_var,self.pos_var,self.source_var):
            var.set('')
        for widget in (self.meaning_text,self.notes_text):
            widget.delete('1.0','end')
        self.word_entry.focus_set()
        self.save_button.configure(text='收入单词本')

    def load_editor(self, ident):
        self.invalidate_lookup()
        w = self.store.get_word(ident)
        self.edit_id = ident
        self.word_var.set(w['word'])
        self.pos_var.set(w['pos'])
        self.source_var.set(w['source'])
        for widget, value in ((self.meaning_text,w['meaning']),(self.notes_text,w['notes'])):
            widget.delete('1.0','end')
            widget.insert('1.0',value)
        self.editor_title.set('编辑已有词条' + ('（保存后恢复到单词本）' if w['deleted'] else ''))
        self.save_button.configure(text='保存修改')
        self.lookup_status.set('已打开本地词条；如需更新释义，点击“重新查询有道”。')
        self.notebook.select(self.add_tab)

    def detect_duplicate(self, event=None):
        w = self.store.find_word(self.word_var.get())
        if w and w['id'] != self.edit_id:
            if self.meaning_text.get('1.0','end').strip() or self.edit_id is not None:
                self.status.set('这个单词已存在；保存时可打开已有词条，请先保留正在编辑的内容。')
            else:
                self.load_editor(w['id'])
                self.status.set('已打开已有词条，可修改释义和备注。')

    def lookup(self, force=False):
        try:
            word = normalize_query(self.word_var.get())
        except DictionaryError as exc:
            self.lookup_status.set(str(exc))
            return
        existing = self.store.find_word(word)
        if existing and existing['id'] != self.edit_id:
            if (self.meaning_text.get('1.0','end').strip() or self.edit_id is not None) and not messagebox.askyesno(
                    '已有词条','该词已存在，是否打开它？当前未保存的输入会被替换。',parent=self.root):
                return
            self.load_editor(existing['id'])
        if existing and not force:
            self.lookup_status.set('单词本中已有这个词，已保留原释义和学习进度。可点击“重新查询有道”。')
            return
        self.invalidate_lookup()
        token = self.lookup_generation
        self.pending_lookup = (token,word,self.editor_signature(),bool(existing or force))
        self.lookup_button.configure(text='正在查询…',state='disabled')
        self.requery_button.configure(state='disabled')
        self.lookup_status.set('正在连接有道词典，自动读取词性与基础释义…')
        self.lookup_worker.submit(token,word)

    def poll_lookup(self):
        if self.closed:
            return
        while True:
            try:
                token,word,result,error = self.lookup_worker.results.get_nowait()
            except Empty:
                break
            pending = self.pending_lookup
            if pending is None or token != pending[0]:
                continue
            self.pending_lookup = None
            self.lookup_button.configure(text='有道查词',state='normal')
            self.requery_button.configure(state='normal')
            if pending[2] != self.editor_signature():
                self.lookup_status.set('查询期间内容已编辑，本次结果未覆盖表单。需要时请重新查询。')
            elif error:
                self.lookup_status.set(error)
            elif pending[3] and self.meaning_text.get('1.0','end').strip():
                self.show_lookup_preview(result,token,pending[2])
            else:
                self.apply_lookup_result(result)
        self.lookup_timer = self.root.after(80,self.poll_lookup)

    def apply_lookup_result(self, result):
        self.pos_var.set(result.pos)
        self.meaning_text.delete('1.0','end')
        self.meaning_text.insert('1.0',result.meaning)
        self.meaning_text.yview_moveto(0)
        self.source_var.set('有道词典 · '+result.source_url)
        self.lookup_status.set('词性与释义已自动填好。浏览后点击“收入单词本”或“保存修改”即可。')
        self.status.set(f'已查到 {result.headword}，尚未保存。')

    def show_lookup_preview(self, result, token, signature):
        window = self.preview_window = tk.Toplevel(self.root)
        window.title('有道新释义 · '+result.headword)
        width,height,_ = window_size(self.root,720,540)
        window.geometry(f'{width}x{height}')
        window.transient(self.root)
        actions = ttk.Frame(window,padding=12)
        actions.pack(side='bottom',fill='x')

        def dismiss():
            window.destroy()
            if self.preview_window == window:
                self.preview_window = None

        def replace():
            if token == self.lookup_generation and signature == self.editor_signature():
                self.apply_lookup_result(result)
            dismiss()

        ttk.Button(actions,text='使用这些释义',style='Primary.TButton',command=replace).pack(side='left')
        ttk.Button(actions,text='保留原内容',command=dismiss).pack(side='right')
        box = tk.Text(window,wrap='word',font=('Microsoft YaHei UI',12),padx=18,pady=16)
        scroll = ttk.Scrollbar(window,command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        box.pack(fill='both',expand=True)
        box.insert('1.0',f'{result.headword}\n\n{result.meaning}\n\n来源：{result.source_url}\n\n使用后只更新表单中的词性、释义和来源；备注及学习记录保留。点击主窗口的“保存修改”才会写入。')
        box.configure(state='disabled')
        window.protocol('WM_DELETE_WINDOW',dismiss)

    def open_dictionary_page(self):
        try:
            url = dictionary_url(self.word_var.get())
        except DictionaryError as exc:
            self.lookup_status.set(str(exc))
            return
        if not webbrowser.open(url):
            messagebox.showerror('未能打开浏览器','请检查系统默认浏览器设置。',parent=self.root)
        else:
            self.status.set('已在浏览器打开有道原词条。自动填入请点击“有道查词”。')

    def save_editor(self):
        self.invalidate_lookup()
        duplicate = self.store.find_word(self.word_var.get())
        if duplicate and duplicate['id'] != self.edit_id:
            if messagebox.askyesno('已有词条','该词已经存在。是否打开已有词条？当前未保存的输入将被替换。',parent=self.root):
                self.load_editor(duplicate['id'])
            return
        try:
            ident = self.store.save_word(self.word_var.get(),self.meaning_text.get('1.0','end'),
                                        self.pos_var.get(),self.source_var.get(),self.notes_text.get('1.0','end'),self.edit_id)
        except Exception as exc:
            messagebox.showerror('未能保存',str(exc),parent=self.root)
            return
        word = self.store.get_word(ident)['word']
        self.clear_editor()
        self.refresh_stats()
        self.refresh_list()
        self.status.set(f'已保存 {word}。')
        if not self.store.questions():
            self.render_quiz()

    def build_list(self):
        top = ttk.Frame(self.list_tab)
        top.pack(fill='x',pady=(0,12))
        ttk.Label(top,text='我的单词本',style='Heading.TLabel').pack(side='left')
        self.search_var = tk.StringVar()
        ttk.Entry(top,textvariable=self.search_var,width=30).pack(side='right',ipady=5)
        ttk.Label(top,text='搜索词条 / 释义  ',style='Muted.TLabel').pack(side='right')
        self.search_var.trace_add('write',lambda *args:self.refresh_list())
        columns = ('word','meaning','mastery','attempts','due')
        table = ttk.Frame(self.list_tab)
        table.pack(fill='both',expand=True)
        self.word_tree = ttk.Treeview(table,columns=columns,show='headings',selectmode='browse')
        for col,label,width in zip(columns,('单词 / 短语','中文释义','掌握度','抽测次数','下次复习'),(170,320,80,90,115)):
            self.word_tree.heading(col,text=label)
            self.word_tree.column(col,width=round(width*self.scale),minwidth=60,stretch=(col in ('word','meaning')))
        scroll = ttk.Scrollbar(table,orient='vertical',command=self.word_tree.yview)
        horizontal = ttk.Scrollbar(table,orient='horizontal',command=self.word_tree.xview)
        self.word_tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom',fill='x')
        self.word_tree.pack(side='left',fill='both',expand=True)
        scroll.pack(side='right',fill='y')
        self.word_tree.bind('<Double-1>',lambda event:self.edit_selected())
        actions = ttk.Frame(self.list_tab)
        actions.pack(fill='x',pady=(12,0))
        ttk.Button(actions,text='编辑选中词',command=self.edit_selected).pack(side='left')
        ttk.Button(actions,text='查看详情与历史',command=self.show_history).pack(side='left',padx=10)
        ttk.Button(actions,text='删除词条',command=self.delete_selected).pack(side='right')
        self.list_count = tk.StringVar()
        ttk.Label(actions,textvariable=self.list_count,style='Muted.TLabel').pack(side='left',padx=12)

    def refresh_list(self):
        selection = self.word_tree.selection()
        self.word_tree.delete(*self.word_tree.get_children())
        rows = self.store.words(self.search_var.get())
        for r in rows:
            self.word_tree.insert('', 'end', iid=str(r['id']), values=(r['word'],r['meaning'].replace('\n',' '),
                                 f'{r["mastery"]} / 5',r['attempts'],r['due']))
        if selection and self.word_tree.exists(selection[0]):
            self.word_tree.selection_set(selection)
        self.list_count.set(f'{len(rows)} 个词')

    def selected_id(self):
        selected = self.word_tree.selection()
        if not selected:
            messagebox.showinfo('选择词条','请先选中一个词条。',parent=self.root)
            return None
        return int(selected[0])

    def edit_selected(self):
        ident = self.selected_id()
        if ident is not None:
            self.load_editor(ident)

    def delete_selected(self):
        ident = self.selected_id()
        if ident is None:
            return
        w = self.store.get_word(ident)
        if messagebox.askyesno('删除词条',f'将“{w["word"]}”从单词本移除？\n历史记录和已经生成的每日题组会保留。',parent=self.root):
            self.store.delete_word(ident)
            if self.edit_id == ident:
                self.clear_editor()
            self.refresh_list()
            self.refresh_stats()
            self.status.set(f'已移除 {w["word"]}，历史记录保留。')

    def show_history(self):
        ident = self.selected_id()
        if ident is None:
            return
        w, reviews = self.store.get_word(ident),self.store.reviews(ident)
        window = tk.Toplevel(self.root)
        window.title(w['word']+' · 详情与历史')
        width,height,_ = window_size(self.root,780,550)
        window.geometry(f'{width}x{height}')
        box = tk.Text(window,wrap='word',font=('Microsoft YaHei UI',12),padx=22,pady=20)
        scroll = ttk.Scrollbar(window,command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        box.pack(fill='both',expand=True)
        correct = sum(r['result']=='认识' for r in reviews)
        rate = f'{correct/len(reviews):.0%}' if reviews else '尚未抽测'
        box.insert('end',f'{w["word"]}   {w["pos"]}\n\n{w["meaning"]}\n\n来源：{w["source"] or "—"}\n备注：{w["notes"] or "—"}\n加入日期：{w["added"]}\n掌握度：{w["mastery"]}/5    正确率：{rate}\n下次复习：{w["due"]}\n\n复习记录\n'+'─'*35+'\n')
        for r in reversed(reviews):
            box.insert('end',f'\n{r["reviewed"]}  {r["direction"]}  ·  {r["result"]}\n回答：{r["answer"] or "（未记录文字回答）"}\n')
            if r['notes']:
                box.insert('end',f'备注：{r["notes"]}\n')
        if not reviews:
            box.insert('end','\n还没有复习记录。')
        box.configure(state='disabled')

    def render_quiz(self):
        for child in self.quiz_tab.winfo_children():
            child.destroy()
        self.quiz_panel = ScrollPanel(self.quiz_tab)
        self.quiz_panel.pack(fill='both',expand=True)
        body = self.quiz_panel.body
        self.current_question = None
        self.revealed = False
        questions = self.store.questions()
        ttk.Label(body,text='今日 10 词',style='Heading.TLabel').pack(anchor='w')
        if not questions:
            ttk.Label(body,text='每天一点，慢慢记牢。',style='Word.TLabel').pack(pady=(35,16))
            ttk.Label(body,text='默认 5 个新词 + 5 个旧词，词义回忆与英文拼写各半。',style='Muted.TLabel',wraplength=round(650*self.scale)).pack()
            ttk.Label(body,text='旧词优先复习到期、薄弱的词；数量不足时自动补足。',style='Muted.TLabel',wraplength=round(650*self.scale)).pack(pady=8)
            if self.store.stats()['total']:
                ttk.Button(body,text='开始今日抽测',style='Primary.TButton',command=self.start_quiz).pack(pady=28)
            else:
                ttk.Button(body,text='先收录一个单词',style='Primary.TButton',command=lambda:self.notebook.select(self.add_tab)).pack(pady=28)
                ttk.Label(body,text='也可从右下角“数据与备份”导入原 Excel。',style='Muted.TLabel').pack()
            return
        answered = [q for q in questions if q['result'] is not None]
        ttk.Label(body,text=f'已完成 {len(answered)} / {len(questions)}    ·    今日题组已保存，随时可以关闭后继续。',style='Muted.TLabel',wraplength=round(650*self.scale)).pack(anchor='w',pady=(8,12))
        ttk.Progressbar(body,maximum=len(questions),value=len(answered)).pack(fill='x',pady=(0,20))
        remaining = [q for q in questions if q['result'] is None]
        if not remaining:
            correct = sum(q['result']=='认识' for q in questions)
            fuzzy = sum(q['result']=='模糊' for q in questions)
            ttk.Label(body,text='今天完成了。',style='Word.TLabel').pack(pady=(12,8))
            ttk.Label(body,text=f'认识 {correct} 个   ·   模糊 {fuzzy} 个   ·   不认识 {len(questions)-correct-fuzzy} 个',style='Muted.TLabel').pack(pady=(0,16))
            frame = ttk.Frame(body)
            frame.pack(fill='both',expand=True)
            result_tree = ttk.Treeview(frame,columns=('word','kind','result'),show='headings',height=6)
            for col,label,width in [('word','单词',280),('kind','题型',180),('result','掌握情况',150)]:
                result_tree.heading(col,text=label)
                result_tree.column(col,width=round(width*self.scale))
            bar = ttk.Scrollbar(frame,command=result_tree.yview)
            result_tree.configure(yscrollcommand=bar.set)
            result_tree.pack(side='left',fill='both',expand=True)
            bar.pack(side='right',fill='y')
            for q in questions:
                result_tree.insert('','end',values=(q['word'],'词义回忆' if q['kind']=='meaning' else '英文拼写',q['result']))
            return
        q = self.current_question = remaining[0]
        meaning = q['kind']=='meaning'
        label = ('看英文 · 回忆中文' if meaning else '看中文 · 默写英文') + ('    /    新词' if q['is_new'] else '    /    复习词')
        ttk.Label(body,text=f'第 {q["ordinal"]} 题    {label}',style='Muted.TLabel').pack(anchor='w')
        prompt_box = ttk.Frame(body)
        prompt_box.pack(fill='x',pady=(18,12))
        prompt = ttk.Label(prompt_box,text=q['word'] if meaning else q['meaning'],
                           style='Word.TLabel' if meaning else 'TLabel',wraplength=round(760*self.scale),justify='left')
        prompt.pack(fill='x')
        prompt_box.bind('<Configure>',lambda event:prompt.configure(wraplength=max(100,event.width-20)))
        self.quiz_answer = tk.StringVar()
        if not meaning:
            self.answer_entry = ttk.Entry(body,textvariable=self.quiz_answer,font=('Microsoft YaHei UI',17),justify='center',width=15)
            self.answer_entry.pack(fill='x',padx=20,ipady=8,pady=(0,12))
            self.answer_entry.bind('<Return>',lambda event:self.reveal_answer())
            self.answer_entry.focus_set()
        self.reveal_button = ttk.Button(body,text='翻开释义' if meaning else '检查拼写 / 忘记了',style='Primary.TButton',command=self.reveal_answer)
        self.reveal_button.pack(pady=6)
        self.answer_label = ttk.Label(body,text='',wraplength=round(760*self.scale),justify='left',font=('Microsoft YaHei UI',12))
        self.answer_label.pack(fill='x',pady=(12,8))
        self.answer_label.bind('<Configure>',lambda event:self.answer_label.configure(wraplength=max(100,event.width-20)))
        self.grade_frame = ttk.Frame(body)
        self.grade_frame.pack(pady=10)
        self.grade_buttons = {}
        for result in ('不认识','模糊','认识'):
            button = ttk.Button(self.grade_frame,text=result,command=lambda r=result:self.grade(r),state='disabled')
            button.pack(side='left',padx=8)
            self.grade_buttons[result] = button
        self.quiz_hint = ttk.Label(body,text='翻开答案后选择掌握情况，选定即保存并进入下一题。',style='Muted.TLabel',wraplength=round(760*self.scale))
        self.quiz_hint.pack(fill='x',pady=(6,0))
        self.quiz_hint.bind('<Configure>',lambda event:self.quiz_hint.configure(wraplength=max(100,event.width-20)))

    def start_quiz(self):
        self.store.start_day()
        self.render_quiz()

    def reveal_answer(self):
        q = self.current_question
        if q is None or self.revealed:
            return
        self.revealed = True
        if q['kind']=='meaning':
            self.answer_label.configure(text=q['meaning'])
        else:
            match = spelling_matches(self.quiz_answer.get(),q['word'])
            self.answer_entry.configure(state='disabled')
            self.answer_label.configure(text=f'正确拼写：{q["word"]}')
            self.quiz_hint.configure(text=('拼写一致，建议选“认识”。' if match else '拼写不一致，建议选“不认识”。')+'如属于其他可接受拼写，可自行修正判定。')
            self.grade_buttons['认识' if match else '不认识'].configure(style='Primary.TButton')
        self.reveal_button.configure(state='disabled')
        for button in self.grade_buttons.values():
            button.configure(state='normal')

    def grade(self, result):
        if self.current_question is None or not self.revealed:
            return
        try:
            q = self.current_question
            self.store.answer(q['id'],self.quiz_answer.get(),result)
            self.status.set(f'已保存 {q["word"]}：{result}。')
        except Exception as exc:
            messagebox.showerror('未能记录',str(exc),parent=self.root)
        self.refresh_stats()
        self.render_quiz()

    def show_data_menu(self):
        self.menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.root,title='导入原 Excel 单词本',initialdir=self.home.parent,filetypes=[('Excel 单词本','*.xlsx')])
        if not path:
            return
        try:
            safety = self.home/'备份'/('导入前_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
            self.store.backup(safety)
            result = import_workbook(self.store,path)
            self.refresh_stats()
            self.refresh_list()
            self.render_quiz()
            messagebox.showinfo('导入完成',f'新增 {result["words"]} 个词条，新增 {result["reviews"]} 条复习记录。\n已有内容自动跳过，原 Excel 文件未修改。',parent=self.root)
        except Exception as exc:
            messagebox.showerror('导入失败',f'{exc}\n\n此次导入未写入任何数据。',parent=self.root)

    def export_file(self):
        path = filedialog.asksaveasfilename(parent=self.root,title='导出单词和复习记录',initialdir=self.home,initialfile='单词本_'+self.store.today().isoformat()+'.xlsx',defaultextension='.xlsx',filetypes=[('Excel 工作簿','*.xlsx')])
        if path:
            try:
                if Path(path).resolve() == (self.home.parent/'雅思迭代单词本.xlsx').resolve():
                    raise ValueError('请使用新的文件名，保留原 Excel 存档。')
                export_workbook(self.store,path)
                self.status.set('Excel 已导出。完整题组进度请使用“完整备份”。')
                messagebox.showinfo('导出完成',f'已保存到：\n{path}',parent=self.root)
            except Exception as exc:
                messagebox.showerror('导出失败',str(exc),parent=self.root)

    def backup_file(self):
        path = filedialog.asksaveasfilename(parent=self.root,title='完整备份',initialdir=self.home/'备份',initialfile='单词本_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3',defaultextension='.sqlite3',filetypes=[('单词本完整备份','*.sqlite3')])
        if path:
            try:
                self.store.backup(path)
                messagebox.showinfo('备份完成','词条、历史记录和每日进度已全部备份。',parent=self.root)
            except Exception as exc:
                messagebox.showerror('备份失败',str(exc),parent=self.root)

    def restore_file(self):
        path = filedialog.askopenfilename(parent=self.root,title='选择完整备份',initialdir=self.home/'备份',filetypes=[('单词本完整备份','*.sqlite3')])
        if path and messagebox.askyesno('恢复完整备份','当前数据将恢复到所选备份的状态。\n恢复前会自动另存一份当前数据，是否继续？',parent=self.root):
            try:
                safety = self.store.restore(path,self.home/'备份')
                self.clear_editor()
                self.refresh_stats()
                self.refresh_list()
                self.render_quiz()
                messagebox.showinfo('恢复完成',f'已恢复。恢复前的数据另存于：\n{safety}',parent=self.root)
            except Exception as exc:
                messagebox.showerror('恢复失败',str(exc),parent=self.root)

    def open_data_folder(self):
        os.startfile(self.store.path.parent)

    def show_help(self):
        messagebox.showinfo('使用说明','1. 查词收录：输入单词，点击“有道查词”或按回车，自动填好词性和释义后点击“收入单词本”。\n2. 已有词条保留原内容；点击“重新查询有道”可预览新释义并决定是否替换。\n3. 今日抽测：翻开答案后选择掌握情况，即时保存。\n4. 我的单词本：搜索、双击编辑，或查看详情与历史。\n5. 数据与备份：导入 / 导出 Excel，完整备份与恢复。\n\n长内容可以滚动查看。只有主动查词时联网，不接入 AI，不需要 API 密钥。',parent=self.root)

    def close(self):
        self.closed = True
        self.lookup_worker.close()
        self.invalidate_lookup()
        self.root.after_cancel(self.lookup_timer)
        self.root.after_cancel(self.timer)
        self.store.close()
        self.root.destroy()
