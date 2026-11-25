"""Keep existing learning data on D:, with a per-user fallback on other PCs."""
from pathlib import Path
import os

DEFAULT_HOME=Path('D:/CC聊天记录/雅思学习/本地单词本')


def default_home():
    if DEFAULT_HOME.exists() or Path('D:/').is_dir():
        return DEFAULT_HOME
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'EnglishVocabular'
