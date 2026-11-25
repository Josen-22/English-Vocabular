"""Read the user's existing workbook; export a small, portable OOXML workbook.

The exporter uses only the standard library, so the desktop runtime does not
need Node, Excel, an office service, or formula calculation caches.
"""
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
import hashlib
import json
import os
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element, SubElement, tostring

from openpyxl import load_workbook
from store import INTERVALS, word_key

RESULT_MAP = {'正确': '认识', '认识': '认识', '模糊': '模糊',
              '错误': '不认识', '不认识': '不认识'}


def text(value):
    return '' if value is None else str(value).strip()


def iso_date(value, default=None):
    if value in (None, ''):
        return default
    if isinstance(value, (date, datetime)):
        return value.strftime('%Y-%m-%d')
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f'无法识别日期：{value}') from exc


def import_workbook(store, path):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if store.conn.execute('SELECT 1 FROM imports WHERE digest=?', (digest,)).fetchone():
        return {'words': 0, 'reviews': 0, 'existing': True}
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if not {'词库', '复习记录'} <= set(workbook.sheetnames):
            raise ValueError('需要包含“词库”和“复习记录”两个工作表。')
        word_rows = list(workbook['词库'].values)
        review_rows = list(workbook['复习记录'].values)
    finally:
        workbook.close()
    if len(word_rows) < 5 or text(word_rows[4][1]) != '单词 / 短语':
        raise ValueError('词库表头不匹配：应与原单词本格式相同，表头在第 5 行。')
    if len(review_rows) < 5 or text(review_rows[4][0]) != '日期':
        raise ValueError('复习记录表头不匹配：表头应在第 5 行。')
    count_words = count_reviews = 0
    id_map, key_map = {}, {}
    occurrences = Counter()
    with store.transaction() as conn:
        for rownum, original in enumerate(word_rows[5:], 6):
            if not any(v is not None for v in original):
                continue
            r = list(original) + [None]*15
            word, meaning = text(r[1]), text(r[3])
            if not word or not meaning:
                raise ValueError(f'词库第 {rownum} 行缺少单词或释义，已取消整次导入。')
            key = word_key(word)
            if key in key_map or (r[0] is not None and str(r[0]) in id_map):
                raise ValueError(f'词库第 {rownum} 行的单词或编号重复，已取消整次导入。')
            try:
                level = int(r[6] or 0)
                if not 0 <= level <= 5 or float(r[6] or 0) != level:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError(f'词库第 {rownum} 行掌握度应为 0—5 的整数。') from None
            added = iso_date(r[5], store.today().isoformat())
            last = iso_date(r[10])
            due = iso_date(r[11], (date.fromisoformat(last)+timedelta(days=INTERVALS[level])).isoformat()
                           if last else added)
            existing = store.find_word(word)
            if existing:
                ident = existing['id']
            else:
                ident = conn.execute('''INSERT INTO words
                    (key,word,pos,meaning,source,notes,added,mastery,last_review,due,deleted)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (key,word,text(r[2]),meaning,text(r[4]),
                    text(r[13]),added,level,last,due,int(text(r[14]) == '是'))).lastrowid
                count_words += 1
                if hasattr(store,'import_metadata') and len(word_rows[4])>=18 and text(word_rows[4][15])=='学习义项':
                    store.import_metadata(ident,text(r[15]),text(r[16]),text(r[17]))
            key_map[key] = ident
            if r[0] is not None:
                id_map[str(r[0])] = ident
        for rownum, original in enumerate(review_rows[5:], 6):
            if not any(v is not None for v in original):
                continue
            r = list(original) + [None]*8
            name = text(r[2])
            ident = key_map.get(word_key(name)) if name else id_map.get(str(r[1]))
            if ident is None:
                raise ValueError(f'复习记录第 {rownum} 行无法匹配词条：{name or r[1]}。')
            if r[1] is not None and str(r[1]) in id_map and id_map[str(r[1])] != ident:
                raise ValueError(f'复习记录第 {rownum} 行的单词与编号不一致。')
            reviewed = iso_date(r[0])
            result = RESULT_MAP.get(text(r[5]))
            if not reviewed or not result:
                raise ValueError(f'复习记录第 {rownum} 行缺少日期或包含未知结果：{r[5]}。')
            name = name or store.get_word(ident)['word']
            fields = [word_key(name), reviewed, text(r[3]), text(r[4]), result, text(r[6]), text(r[7])]
            signature = json.dumps(fields, ensure_ascii=False)
            occurrences[signature] += 1
            fingerprint = hashlib.sha256((signature+f'#{occurrences[signature]}').encode()).hexdigest()
            # Also recognize application-generated records in a re-imported export.
            matched = conn.execute('''SELECT COUNT(*) FROM reviews WHERE word_id=?
                AND reviewed=? AND direction=? AND answer=? AND result=? AND notes=? AND batch=?''',
                (ident, *fields[1:])).fetchone()[0]
            if matched >= occurrences[signature]:
                continue
            count_reviews += conn.execute('''INSERT OR IGNORE INTO reviews
                (word_id,word,reviewed,direction,answer,result,notes,batch,import_key)
                VALUES(?,?,?,?,?,?,?,?,?)''', (ident,name,*fields[1:],fingerprint)).rowcount
        conn.execute('INSERT INTO imports VALUES(?,?,?)', (digest,datetime.now().isoformat(),path.name))
    return {'words': count_words, 'reviews': count_reviews, 'existing': False}


NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def column_name(number):
    result = ''
    while number:
        number, remainder = divmod(number-1, 26)
        result = chr(65+remainder)+result
    return result


def sheet_xml(rows, widths):
    root = Element('worksheet', xmlns=NS)
    views = SubElement(root, 'sheetViews')
    view = SubElement(views, 'sheetView', workbookViewId='0')
    SubElement(view, 'pane', ySplit='5', topLeftCell='A6', activePane='bottomLeft', state='frozen')
    cols = SubElement(root, 'cols')
    for i, width in enumerate(widths, 1):
        SubElement(cols, 'col', min=str(i), max=str(i), width=str(width), customWidth='1')
    data = SubElement(root, 'sheetData')
    for rownum, row in enumerate(rows, 1):
        row_element = SubElement(data, 'row', r=str(rownum))
        if rownum == 5:
            row_element.set('ht', '26')
            row_element.set('customHeight', '1')
        for colnum, value in enumerate(row, 1):
            if value is None:
                continue
            attrs = {'r': column_name(colnum)+str(rownum), 's': '1' if rownum == 5 else '0'}
            cell = SubElement(row_element, 'c', **attrs)
            if isinstance(value, (int, float)):
                SubElement(cell, 'v').text = str(value)
            else:
                cell.set('t', 'inlineStr')
                t = SubElement(SubElement(cell, 'is'), 't', {'xml:space': 'preserve'})
                # Excel XML disallows these controls; typed text always stays text (no formulas).
                t.text = ''.join(ch for ch in str(value) if ord(ch) >= 32 or ch in '\n\r\t')
    if len(rows) >= 5:
        SubElement(root, 'autoFilter', ref=f'A5:{column_name(len(rows[4]))}{len(rows)}')
    return tostring(root, encoding='utf-8', xml_declaration=True)


def export_workbook(store, path):
    word_headers = ['编号','单词 / 短语','词性','中文释义','来源','加入日期','掌握度',
                    '抽问次数','正确次数','正确率','上次复习','下次复习','状态','备注','已删除','学习义项','英式音标','美式音标']
    review_headers = ['日期','单词编号','单词 / 短语','抽问方向','你的回答','结果','反馈 / 备注','学习批次']
    words = [['本地单词本'], ['导出日期：'+store.today().isoformat()],
             ['完整进度请使用数据库备份；本表用于查看和交换单词及复习记录。'], [], word_headers]
    for w in store.words(include_deleted=True):
        words.append([w['id'],w['word'],w['pos'],w['meaning'],w['source'],w['added'],w['mastery'],
                      w['attempts'],w['correct'],round(w['correct']/w['attempts'],4) if w['attempts'] else None,
                      w['last_review'],w['due'],'待复习' if w['due'] <= store.today().isoformat() else '未到期',
                      w['notes'],'是' if w['deleted'] else '否',
                      *[w[key] if key in w.keys() else '' for key in ('study_meaning','uk_phonetic','us_phonetic')]])
    reviews = [['复习记录'], ['认识计为正确，模糊和不认识不计为正确。'], [], [], review_headers]
    labels = {'认识': '正确', '模糊': '模糊', '不认识': '错误'}
    for r in store.reviews():
        reviews.append([r['reviewed'],r['word_id'],r['word'],r['direction'],r['answer'],
                        labels[r['result']],r['notes'],r['batch']])
    styles = f'''<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF245F58"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" xfId="0"/><xf fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.xlsx', dir=path.parent)
    os.close(fd)
    try:
        with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>''' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in (1,2)) + '</Types>')
            archive.writestr('_rels/.rels', f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            book = Element('workbook', xmlns=NS, **{'xmlns:r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'})
            sheets = SubElement(book, 'sheets')
            for i, name in enumerate(('词库','复习记录'), 1):
                SubElement(sheets, 'sheet', name=name, sheetId=str(i), **{'r:id':f'rId{i}'})
            archive.writestr('xl/workbook.xml', tostring(book, encoding='utf-8', xml_declaration=True))
            archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{REL}">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in (1,2))+'<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
            archive.writestr('xl/styles.xml', styles)
            archive.writestr('xl/worksheets/sheet1.xml', sheet_xml(words, [9,25,13,45,22,15,10,12,12,12,15,15,13,45,10,40,20,20]))
            archive.writestr('xl/worksheets/sheet2.xml', sheet_xml(reviews, [15,12,26,16,30,13,50,30]))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
