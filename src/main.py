"""Application entry point, usable from source or a frozen executable."""
from datetime import date
from pathlib import Path
import argparse
import ctypes
import logging
import sys
import tkinter as tk
from tkinter import messagebox

from store import Store
from ui import App

DEFAULT_HOME = Path('D:/CC聊天记录/雅思学习/本地单词本')


def main():
    parser = argparse.ArgumentParser(description='本地单词本，无账号、无 API。')
    parser.add_argument('--home', type=Path, default=DEFAULT_HOME, help='数据根目录（默认 D 盘学习目录）')
    parser.add_argument('--check-installation', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    home = args.home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    for name in ('数据','备份'):
        (home/name).mkdir(exist_ok=True)
    logging.basicConfig(filename=home/'数据'/'错误日志.log',level=logging.ERROR,encoding='utf-8')
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    if args.check_installation:
        from release_check import run
        return run(home)
    root = tk.Tk()
    root.withdraw()

    def report_error(exc_type, value, traceback):
        logging.error('界面操作失败',exc_info=(exc_type,value,traceback))
        messagebox.showerror('操作未完成',f'{value}\n\n请重试，详细信息已写入数据目录的错误日志。',parent=root)

    root.report_callback_exception = report_error
    try:
        store = Store(home/'数据'/'单词本.sqlite3')
        target = home/'备份'/('每日自动_'+date.today().isoformat()+'.sqlite3')
        if not target.exists():
            store.backup(target)
        app = App(root,store,home)
        root.deiconify()
        root.mainloop()
    except Exception:
        logging.exception('程序启动失败')
        messagebox.showerror('启动失败','无法打开单词本，请检查数据目录权限或查看“数据/错误日志.log”。',parent=root)
        root.destroy()
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
