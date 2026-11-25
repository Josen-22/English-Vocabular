"""Line-oriented test bridge. Never reads the user's real vocabulary database."""
from datetime import date,timedelta
from pathlib import Path
import json
import logging
import sys
from io import BytesIO

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bridge import Bridge
import bridge as bridge_module
from desktop import load_html
from lookup import LookupResult,Sense
from store import Store
import pronunciation


def main():
    logging.disable(logging.CRITICAL)
    sys.stdout.reconfigure(encoding='utf-8')
    home=Path(sys.argv[1]);home.mkdir(parents=True,exist_ok=True)
    store=Store(home/'数据'/'单词本.sqlite3')
    samples=[('retain','v.','保持；保留'),('moisture','n.','水分；湿气'),('firm','n. / adj.','公司；坚固的'),
        ('abolish','v.','废除；取消'),('genuine','adj.','真正的；真诚的'),('refine','v.','提纯；改进'),
        ('subtle','adj.','微妙的'),('deprivation','n.','剥夺；匮乏'),('amass','v.','积累'),('cane','n.','茎；手杖'),
        ('alpha','n.','希腊字母第一位'),('beta','n.','希腊字母第二位')]
    if not store.words():
        for n,(word,pos,meaning) in enumerate(samples):
            ident=store.save_word(word,meaning,pos=pos,source='界面验收样本',notes='测试备注')
            if n<7:
                with store.conn:
                    store.conn.execute('UPDATE words SET mastery=?,due=?,last_review=? WHERE id=?',
                        (n%6,str(date.today()-timedelta(days=1)),str(date.today()-timedelta(days=3)),ident))
                    store.conn.execute('''INSERT INTO reviews(word_id,word,reviewed,direction,result)
                        VALUES(?,?,?,?,?)''',(ident,word,str(date.today()-timedelta(days=3)),'英译中','认识' if n%2 else '不认识'))
    store.close()
    bridge_module.fetch_youdao=lambda word:LookupResult(word,word,(Sense('adj.','有韧性的；能迅速恢复的'),),'https://dict.youdao.com/w/eng/'+word+'/','[rɪˈzɪliənt]','[rɪˈzɪliənt]')
    class AudioSample(BytesIO):
        url='https://dict.youdao.com/dictvoice'
    pronunciation.urlopen=lambda request,timeout:AudioSample(b'ID3'+b'\x00'*100)
    frontend=home/'frontend.html';frontend.write_text(load_html(),encoding='utf-8')
    api=Bridge(home)
    print(json.dumps({'ready':True,'url':frontend.as_uri()}),flush=True)
    for line in sys.stdin:
        data=json.loads(line)
        print(json.dumps({'id':data['id'],'result':api.call(data['action'],data.get('payload'))},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
