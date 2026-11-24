"""Version two desktop entry point; all assets are bundled and local."""
from datetime import date
from pathlib import Path
import argparse
import ctypes
import logging
import sys

from bridge import Bridge
from store import Store

DEFAULT_HOME=Path('D:/CC聊天记录/雅思学习/本地单词本')


def asset_path():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'web'/'index.html'


def load_html():
    path=asset_path()
    return path.read_text(encoding='utf-8').replace('<!--APP_STYLE-->',
        '<style>'+path.with_name('app.css').read_text(encoding='utf-8')+'</style>').replace('<!--APP_SCRIPT-->',
        '<script>'+path.with_name('app.js').read_text(encoding='utf-8')+'</script>')


def main():
    parser=argparse.ArgumentParser(description='本地单词本第二版 · 三种主题与词库排序')
    parser.add_argument('--home',type=Path,default=DEFAULT_HOME)
    parser.add_argument('--check-installation',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    home=args.home.resolve()
    for folder in ('数据','备份','验证'):
        (home/folder).mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=home/'数据'/'第二版错误日志.log',encoding='utf-8',level=logging.ERROR)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError,OSError):
        pass
    if args.check_installation:
        from verify_v2 import run
        return run(home)
    store=Store(home/'数据'/'单词本.sqlite3')
    try:
        backup=home/'备份'/('第二版启动_'+date.today().isoformat()+'.sqlite3')
        if not backup.exists():
            store.backup(backup)
    finally:
        store.close()
    import webview
    bridge=Bridge(home)
    bridge._window=webview.create_window('本地单词本 · 第二版',html=load_html(),js_api=bridge,
                 width=1160,height=820,min_size=(760,580),background_color='#f3f6f4',text_select=True)
    try:
        webview.start(gui='edgechromium',debug=False,private_mode=True)
    except Exception:
        logging.exception('第二版窗口启动失败')
        raise
    return 0


if __name__=='__main__':
    sys.exit(main())
