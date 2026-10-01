#!/usr/bin/env python3
"""JASS English–Mizo Dictionary Pro

Offline desktop dictionary built from the 1997 Lalropara Pachuau
English–Mizo Dictionary OCR source. Designed to work with a prebuilt
SQLite database, while also allowing additional EPUB/TXT/XML/PDF sources.

Install:
    pip install PySide6
Optional for PDF import:
    pip install PyMuPDF

Place english_mizo_dictionary.db beside this script for the prebuilt
16k+ entry dictionary generated from dli.language.0175_djvu.xml.
"""

import csv
import difflib
import html
import re
import sqlite3
import sys
import zipfile
import shutil
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser,
    QFileDialog, QMessageBox, QComboBox, QDialog, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QProgressBar, QCheckBox,
    QSpinBox, QFormLayout, QGroupBox
)

try:
    import fitz
except Exception:
    fitz = None

APP = "JASS English–Mizo Dictionary Pro"
HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "english_mizo_dictionary.db"
USER_DB = Path.home() / ".jass_english_mizo_dictionary" / "dictionary.db"
USER_DB.parent.mkdir(parents=True, exist_ok=True)
DB_PATH = DEFAULT_DB if DEFAULT_DB.exists() else USER_DB

POS_RE = re.compile(r"\b(n|v|vt|vi|adj|adv|prep|conj|pron|int|pro|part|aux\s*v|emp\s*pro|pref|num|abbr|phr|phrase)\b", re.I)
ENTRY_RE = re.compile(r"^([A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*){0,5})\s+\(([^)]{1,100})\)\s*(.*)$")


def norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("¬", "").strip())


def parse_paren(par):
    par = norm(par)
    parts = [x.strip() for x in par.split(';')]
    if len(parts) > 1:
        return parts[0], '; '.join(parts[1:])
    if POS_RE.search(par):
        return "", par
    return par, ""


def parse_xml_dictionary(path, progress=None):
    """Parse Internet Archive DjVuXML while preserving page/confidence."""
    tree = ET.parse(path)
    root = tree.getroot()
    objects = root.findall('.//OBJECT')
    rows = []
    current = None

    for pi, obj in enumerate(objects):
        if pi < 5:
            continue
        cols = obj.findall('.//PAGECOLUMN')
        for ci, col in enumerate(cols):
            words = col.findall('.//WORD')
            if len(words) < 15:
                continue
            for line in col.findall('.//LINE'):
                ws = line.findall('.//WORD')
                text = norm(' '.join((w.text or '').strip() for w in ws))
                if not text:
                    continue
                m = ENTRY_RE.match(text)
                candidate = None
                if m:
                    h, par, rest = m.groups()
                    pron, pos = parse_paren(par)
                    strong = (';' in par) or bool(pos)
                    if strong and len(h) <= 55 and len(h.split()) <= 6:
                        if not (not rest.strip(' .;:-—') and ';' not in par and par.lower().rstrip('.') in {
                            'n','v','vt','vi','adj','adv','prep','conj','pron','int','pro','part','pref','num','abbr'
                        }):
                            candidate = (h, pron, pos, rest)
                if candidate:
                    if current and norm(current['definition']):
                        rows.append(current)
                    h, pron, pos, rest = candidate
                    confs = []
                    xs, ys = [], []
                    for w in ws:
                        try:
                            confs.append(float(w.attrib.get('x-confidence', '0')))
                        except Exception:
                            pass
                        try:
                            c = [int(v) for v in w.attrib.get('coords','').split(',')]
                            xs.append(c[0]); ys.append(c[1])
                        except Exception:
                            pass
                    current = {
                        'headword': norm(h), 'pronunciation': norm(pron), 'pos': norm(pos),
                        'definition': norm(rest), 'book_page': max(1, pi - 4),
                        'scan_page': pi + 1, 'column_no': ci + 1,
                        'confidence': round(sum(confs)/len(confs), 1) if confs else 0,
                        'source': Path(path).name
                    }
                elif current:
                    current['definition'] += ' ' + text
            if progress and pi % 10 == 0:
                progress(pi, len(objects))
    if current and norm(current['definition']):
        rows.append(current)
    return rows


def read_text_source(path):
    return Path(path).read_text(encoding='utf-8', errors='replace')


def parse_plain_text(text, source):
    rows=[]; cur=None
    for line in text.splitlines():
        line=norm(line)
        if not line or re.fullmatch(r'-?\s*\d+\s*-?', line):
            continue
        m=ENTRY_RE.match(line)
        cand=None
        if m:
            h,par,rest=m.groups(); pron,pos=parse_paren(par)
            if ((';' in par) or pos) and len(h)<=55:
                if not (not rest.strip(' .;:-—') and ';' not in par and par.lower().rstrip('.') in {'n','v','vt','vi','adj','adv'}):
                    cand=(h,pron,pos,rest)
        if cand:
            if cur and norm(cur['definition']): rows.append(cur)
            h,pron,pos,rest=cand
            cur={'headword':norm(h),'pronunciation':norm(pron),'pos':norm(pos),'definition':norm(rest),
                 'book_page':None,'scan_page':None,'column_no':None,'confidence':0,'source':source}
        elif cur:
            cur['definition']+=' '+line
    if cur and norm(cur['definition']): rows.append(cur)
    return rows


def import_source(path, progress=None):
    ext=Path(path).suffix.lower()
    if ext=='.xml' and 'djvu' in Path(path).name.lower():
        return parse_xml_dictionary(path, progress)
    if ext in {'.txt','.md'}:
        return parse_plain_text(read_text_source(path), Path(path).name)
    if ext=='.epub':
        chunks=[]
        with zipfile.ZipFile(path) as z:
            names=z.namelist()
            cont=ET.fromstring(z.read('META-INF/container.xml'))
            rootfile=next((e.attrib.get('full-path') for e in cont.iter() if e.tag.lower().endswith('rootfile')),None)
            if not rootfile: raise RuntimeError('EPUB package document not found.')
            opf=ET.fromstring(z.read(rootfile))
            base=Path(rootfile).parent.as_posix()
            manifest={}
            for e in opf.iter():
                if e.tag.lower().endswith('item'):
                    manifest[e.attrib.get('id')]=(e.attrib.get('href',''),e.attrib.get('media-type',''))
            spine=[]
            for e in opf.iter():
                if e.tag.lower().endswith('itemref') and e.attrib.get('idref') in manifest:
                    spine.append(manifest[e.attrib['idref']][0])
            for href in spine:
                name=(Path(base)/href).as_posix().replace('%20',' ')
                if name in names:
                    raw=z.read(name).decode('utf-8','ignore')
                    raw=re.sub(r'(?is)<script.*?</script>|<style.*?</style>','',raw)
                    raw=re.sub(r'(?i)</(p|div|li|h[1-6]|br)>','\n',raw)
                    raw=re.sub(r'<[^>]+>',' ',raw)
                    chunks.append(html.unescape(raw))
        return parse_plain_text('\n'.join(chunks),Path(path).name)
    if ext=='.pdf':
        if fitz is None: raise RuntimeError('PDF import requires PyMuPDF: pip install PyMuPDF')
        doc=fitz.open(path); chunks=[p.get_text('text') for p in doc]; doc.close()
        return parse_plain_text('\n'.join(chunks),Path(path).name)
    raise RuntimeError('Supported imports: DjVuXML, TXT, EPUB and PDF.')


class DB:
    def __init__(self, path=DB_PATH):
        self.path=Path(path)
        self.con=sqlite3.connect(self.path)
        self.ensure()
    def ensure(self):
        c=self.con.cursor()
        # Empty DB gets the full schema. Existing prebuilt DB gets auxiliary tables.
        c.execute('''CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY, headword TEXT NOT NULL, pronunciation TEXT DEFAULT '',
            pos TEXT DEFAULT '', definition TEXT NOT NULL, book_page INTEGER, scan_page INTEGER,
            column_no INTEGER, confidence REAL DEFAULT 0, order_ok INTEGER DEFAULT 1,
            source TEXT DEFAULT '', favorite INTEGER DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_entries_headword ON entries(headword COLLATE NOCASE)')
        c.execute('''CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER, headword TEXT, opened TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)''')
        c.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
            headword, pronunciation, pos, definition, content='entries', content_rowid='id', tokenize='unicode61')''')
        # Populate FTS if it is empty and entries exist.
        n=c.execute('SELECT COUNT(*) FROM entries_fts').fetchone()[0]
        if n==0 and c.execute('SELECT COUNT(*) FROM entries').fetchone()[0]:
            c.execute("INSERT INTO entries_fts(rowid,headword,pronunciation,pos,definition) SELECT id,headword,pronunciation,pos,definition FROM entries")
        self.con.commit()
    def count(self): return self.con.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
    def insert_many(self,rows):
        cur=self.con.cursor(); start=self.count()+1
        data=[]
        for i,r in enumerate(rows,start):
            data.append((i,r.get('headword',''),r.get('pronunciation',''),r.get('pos',''),r.get('definition',''),r.get('book_page'),r.get('scan_page'),r.get('column_no'),r.get('confidence',0),1,r.get('source','')))
        cur.executemany('''INSERT INTO entries(id,headword,pronunciation,pos,definition,book_page,scan_page,column_no,confidence,order_ok,source)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)''',data)
        cur.execute("INSERT INTO entries_fts(rowid,headword,pronunciation,pos,definition) SELECT id,headword,pronunciation,pos,definition FROM entries WHERE id>=?",(start,))
        self.con.commit(); return len(data)
    def exact(self,q):
        return self.con.execute('SELECT id,headword,pronunciation,pos,definition,book_page,scan_page,confidence,source FROM entries WHERE headword=? COLLATE NOCASE ORDER BY id',(q,)).fetchall()
    def prefix(self,q,limit=120):
        return self.con.execute('SELECT id,headword,pronunciation,pos,definition,book_page,scan_page,confidence,source FROM entries WHERE headword LIKE ? COLLATE NOCASE ORDER BY headword LIMIT ?', (q+'%',limit)).fetchall()
    def search_all(self,q,limit=120):
        return self.con.execute('''SELECT id,headword,pronunciation,pos,definition,book_page,scan_page,confidence,source FROM entries
            WHERE headword LIKE ? COLLATE NOCASE OR pronunciation LIKE ? COLLATE NOCASE OR definition LIKE ? COLLATE NOCASE
            ORDER BY headword LIMIT ?''',(f'%{q}%',f'%{q}%',f'%{q}%',limit)).fetchall()
    def fts(self,q,limit=120):
        safe=' '.join(re.findall(r'[\wÀ-ž]+',q,flags=re.UNICODE))
        if not safe: return []
        try:
            return self.con.execute('''SELECT e.id,e.headword,e.pronunciation,e.pos,e.definition,e.book_page,e.scan_page,e.confidence,e.source
                FROM entries_fts f JOIN entries e ON e.id=f.rowid WHERE entries_fts MATCH ? LIMIT ?''',(safe+'*',limit)).fetchall()
        except sqlite3.Error: return self.search_all(q,limit)
    def favorites(self):
        return self.con.execute('SELECT id,headword,pronunciation,pos,definition,book_page,scan_page,confidence,source FROM entries WHERE favorite=1 ORDER BY headword').fetchall()
    def toggle_favorite(self,eid):
        cur=self.con.execute('SELECT favorite FROM entries WHERE id=?',(eid,)); row=cur.fetchone()
        if not row:return False
        state=not bool(row[0]); self.con.execute('UPDATE entries SET favorite=? WHERE id=?',(int(state),eid)); self.con.commit(); return state
    def is_favorite(self,eid):
        r=self.con.execute('SELECT favorite FROM entries WHERE id=?',(eid,)).fetchone(); return bool(r and r[0])
    def history(self):
        return self.con.execute('''SELECT e.id,e.headword,e.pronunciation,e.pos,e.definition,e.book_page,e.scan_page,e.confidence,e.source
            FROM history h JOIN entries e ON e.id=h.entry_id ORDER BY h.id DESC LIMIT 100''').fetchall()
    def add_history(self,eid,head):
        self.con.execute('INSERT INTO history(entry_id,headword,opened) VALUES(?,?,?)',(eid,head,datetime.now().isoformat(timespec='seconds')))
        self.con.commit()
    def headwords(self): return [r[0] for r in self.con.execute('SELECT DISTINCT headword FROM entries ORDER BY headword')]
    def copy_definition(self):
        if not self.current:return
        _,h,pron,pos,definition,page,scan,conf,source=self.current
        lines=[h]
        if pron: lines.append(f'/{pron}/')
        if pos: lines.append(pos)
        lines.append(definition)
        QApplication.clipboard().setText('\\n'.join(lines))
        self.statusBar().showMessage('Definition copied to clipboard',2500)

    def change_font(self,delta):
        self.set_font(max(12,min(32,self.font_size+delta)))

    def set_font(self,size):
        self.font_size=size
        if self.current:self.display(self.current)

    def toggle_theme(self):
        self.dark=not self.dark
        self.style()
        self.statusBar().showMessage('Dark theme enabled' if self.dark else 'Light theme enabled',2000)

    def random_word(self):
        if not self.all_heads:
            QMessageBox.information(self,'Random Word','The dictionary is empty.'); return
        word=random.choice(self.all_heads)
        self.query.setText(word); self.mode.setCurrentText('Exact English'); self.lookup()

    def statistics(self):
        n=self.db.count(); fav=len(self.db.favorites()); hist=len(self.db.history())
        try:
            srcs=self.db.con.execute("SELECT source,COUNT(*) FROM entries GROUP BY source ORDER BY COUNT(*) DESC").fetchall()
        except Exception: srcs=[]
        d=QDialog(self); d.setWindowTitle('Dictionary Statistics'); d.resize(620,480); l=QVBoxLayout(d)
        l.addWidget(QLabel(f'<h2>English–Mizo Dictionary</h2><p><b>{n:,}</b> indexed entries<br><b>{len(self.all_heads):,}</b> unique headwords<br><b>{fav:,}</b> favorites<br><b>{hist:,}</b> recent history records</p>'))
        box=QGroupBox('Sources'); bl=QVBoxLayout(box)
        if srcs:
            for name,count in srcs[:20]: bl.addWidget(QLabel(f'{count:,}  —  {name or "Local"}'))
        else: bl.addWidget(QLabel('No source information available.'))
        l.addWidget(box,1)
        bb=QDialogButtonBox(QDialogButtonBox.Close); bb.rejected.connect(d.reject); l.addWidget(bb); d.exec()

    def backup_database(self):
        if not self.db.path.exists():
            QMessageBox.warning(self,'Backup','Database file does not exist yet.'); return
        path,_=QFileDialog.getSaveFileName(self,'Backup Dictionary Database',str(Path.home()/'english_mizo_dictionary_backup.db'),'SQLite database (*.db)')
        if not path:return
        try:
            self.db.con.commit(); shutil.copy2(self.db.path,path)
            QMessageBox.information(self,'Backup complete',f'Backup saved to:\\n{path}')
        except Exception as e: QMessageBox.critical(self,'Backup failed',str(e))

    def clear(self):
        self.con.execute('DELETE FROM entries'); self.con.execute('DELETE FROM entries_fts'); self.con.execute('DELETE FROM history'); self.con.commit()
    def close(self): self.con.close()


class ImportPreview(QDialog):
    def __init__(self,parent,rows):
        super().__init__(parent); self.rows=rows; self.setWindowTitle('Import Preview'); self.resize(1050,700)
        lay=QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>{len(rows):,}</b> dictionary records detected. Review before importing.'))
        self.table=QTableWidget(len(rows),4); self.table.setHorizontalHeaderLabels(['Import','English','Pronunciation / POS','Mizo definition'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i,r in enumerate(rows):
            x=QTableWidgetItem(); x.setCheckState(Qt.Checked); self.table.setItem(i,0,x)
            self.table.setItem(i,1,QTableWidgetItem(r.get('headword','')))
            self.table.setItem(i,2,QTableWidgetItem(' • '.join(filter(None,[r.get('pronunciation',''),r.get('pos','')]))))
            self.table.setItem(i,3,QTableWidgetItem(r.get('definition','')))
        lay.addWidget(self.table,1)
        bar=QHBoxLayout(); a=QPushButton('Select All'); a.clicked.connect(lambda:self.select(True)); bar.addWidget(a); b=QPushButton('Select None'); b.clicked.connect(lambda:self.select(False)); bar.addWidget(b); bar.addStretch(); self.info=QLabel(); bar.addWidget(self.info); lay.addLayout(bar)
        bb=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); lay.addWidget(bb)
        self.update_info()
        self.table.itemChanged.connect(lambda *_:self.update_info())
    def select(self,state):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()): self.table.item(r,0).setCheckState(Qt.Checked if state else Qt.Unchecked)
        self.table.blockSignals(False); self.update_info()
    def update_info(self): self.info.setText(f"{sum(self.table.item(r,0).checkState()==Qt.Checked for r in range(self.table.rowCount())):,} selected")
    def selected(self):
        out=[]
        for i,r in enumerate(self.rows):
            if self.table.item(i,0).checkState()==Qt.Checked: out.append(r)
        return out


class Dictionary(QMainWindow):
    def __init__(self):
        super().__init__(); self.db=DB(); self.rows=[]; self.current=None; self.all_heads=[]
        self.setWindowTitle(APP + ' Pro'); self.resize(1360,880); self.setMinimumSize(1050,680); self.build(); self.style(); self.refresh(); self.welcome()
    def build(self):
        self.menu()
        c=QWidget(); self.setCentralWidget(c)
        root=QVBoxLayout(c); root.setContentsMargins(28,22,28,20); root.setSpacing(14)

        head=QHBoxLayout(); brand=QVBoxLayout()
        self.title=QLabel('English  →  Mizo'); self.title.setObjectName('title'); brand.addWidget(self.title)
        self.subtitle=QLabel('JASS Dictionary • offline • source-aware • fast'); self.subtitle.setObjectName('muted'); brand.addWidget(self.subtitle)
        head.addLayout(brand); head.addStretch()

        self.randomBtn=QPushButton('🎲 Random Word'); self.randomBtn.clicked.connect(self.random_word); head.addWidget(self.randomBtn)
        self.importBtn=QPushButton('＋ Import Source'); self.importBtn.clicked.connect(self.import_source); head.addWidget(self.importBtn)
        self.themeBtn=QPushButton('☾'); self.themeBtn.setFixedSize(44,40); self.themeBtn.setToolTip('Toggle light / dark theme'); self.themeBtn.clicked.connect(self.toggle_theme); head.addWidget(self.themeBtn)
        root.addLayout(head)

        search=QHBoxLayout()
        self.query=QLineEdit(); self.query.setPlaceholderText('Search English word, phrase, pronunciation, or Mizo meaning…'); self.query.setMinimumHeight(54); self.query.setClearButtonEnabled(True); search.addWidget(self.query,1)
        self.mode=QComboBox(); self.mode.addItems(['Smart lookup','Exact English','English starts with','Mizo → English','Search all text']); self.mode.setFixedWidth(180); search.addWidget(self.mode)
        self.lookupBtn=QPushButton('LOOK UP'); self.lookupBtn.setMinimumHeight(54); self.lookupBtn.clicked.connect(self.lookup); search.addWidget(self.lookupBtn)
        root.addLayout(search)

        split=QSplitter(Qt.Horizontal)

        left=QWidget(); ll=QVBoxLayout(left); ll.setContentsMargins(0,0,8,0)
        self.section=QLabel('Suggestions'); self.section.setObjectName('section'); ll.addWidget(self.section)
        self.list=QListWidget(); self.list.setSpacing(2)
        self.list.itemClicked.connect(lambda i:self.display(i.data(Qt.UserRole)))
        self.list.itemDoubleClicked.connect(lambda i:self.display(i.data(Qt.UserRole)))
        ll.addWidget(self.list,1)

        qbar=QHBoxLayout()
        for label,tip,fn in [('★','Favorites',self.favorites),('🕘','History',self.history),('A–Z','Browse',self.browse)]:
            x=QPushButton(label); x.setToolTip(tip); x.clicked.connect(fn); qbar.addWidget(x)
        ll.addLayout(qbar); split.addWidget(left)

        right=QWidget(); rr=QVBoxLayout(right); rr.setContentsMargins(8,0,0,0)
        card=QWidget(); card.setObjectName('card'); cl=QVBoxLayout(card); cl.setContentsMargins(30,25,30,20)

        top=QHBoxLayout()
        self.word=QLabel('English–Mizo'); self.word.setObjectName('word'); top.addWidget(self.word,1)
        self.pos=QLabel(''); self.pos.setObjectName('pos'); top.addWidget(self.pos)
        self.star=QPushButton('☆'); self.star.setFixedSize(46,42); self.star.setToolTip('Add to favorites'); self.star.clicked.connect(self.favorite); top.addWidget(self.star)
        cl.addLayout(top)

        pbar=QHBoxLayout()
        self.pron=QLabel(''); self.pron.setObjectName('pron'); pbar.addWidget(self.pron,1)
        self.copyBtn=QPushButton('Copy'); self.copyBtn.setToolTip('Copy current entry'); self.copyBtn.clicked.connect(self.copy_definition); pbar.addWidget(self.copyBtn)
        self.smallerBtn=QPushButton('A−'); self.smallerBtn.setFixedWidth(45); self.smallerBtn.clicked.connect(lambda:self.change_font(-1)); pbar.addWidget(self.smallerBtn)
        self.largerBtn=QPushButton('A+'); self.largerBtn.setFixedWidth(45); self.largerBtn.clicked.connect(lambda:self.change_font(1)); pbar.addWidget(self.largerBtn)
        cl.addLayout(pbar)

        self.defn=QTextBrowser(); self.defn.setObjectName('definition'); self.defn.setOpenExternalLinks(False); self.defn.setReadOnly(True); cl.addWidget(self.defn,1)
        self.source=QLabel(''); self.source.setObjectName('source'); self.source.setWordWrap(True); cl.addWidget(self.source)
        rr.addWidget(card,1)

        nav=QHBoxLayout()
        self.prevBtn=QPushButton('← Previous'); self.prevBtn.clicked.connect(self.prev); nav.addWidget(self.prevBtn)
        nav.addStretch()
        self.resultPos=QLabel(''); self.resultPos.setObjectName('muted'); nav.addWidget(self.resultPos)
        nav.addStretch()
        self.nextBtn=QPushButton('Next →'); self.nextBtn.clicked.connect(self.next); nav.addWidget(self.nextBtn)
        rr.addLayout(nav)

        split.addWidget(right); split.setSizes([410,920]); root.addWidget(split,1)

        foot=QHBoxLayout()
        for label,fn in [('★ Favorites',self.favorites),('🕘 History',self.history),('A–Z Browse',self.browse),('ⓘ Statistics',self.statistics)]:
            x=QPushButton(label); x.clicked.connect(fn); foot.addWidget(x)
        foot.addStretch(); self.dbstat=QLabel(); self.dbstat.setObjectName('muted'); foot.addWidget(self.dbstat); root.addLayout(foot)

        self.query.returnPressed.connect(self.lookup); self.query.textChanged.connect(self.live)
        QShortcut(QKeySequence('Ctrl+L'),self,activated=self.focus)
        QShortcut(QKeySequence('Ctrl+O'),self,activated=self.import_source)
        QShortcut(QKeySequence('Ctrl+Shift+C'),self,activated=self.copy_definition)
        QShortcut(QKeySequence('Ctrl+D'),self,activated=self.favorite)
        QShortcut(QKeySequence('Ctrl+Shift+R'),self,activated=self.random_word)
        QShortcut(QKeySequence('Left'),self,activated=self.prev); QShortcut(QKeySequence('Right'),self,activated=self.next)
        QShortcut(QKeySequence('Ctrl++'),self,activated=lambda:self.change_font(1))
        QShortcut(QKeySequence('Ctrl+-'),self,activated=lambda:self.change_font(-1))
        QShortcut(QKeySequence('Ctrl+0'),self,activated=lambda:self.set_font(18))
        self.font_size=18; self.dark=False

    def menu(self):
        m=self.menuBar().addMenu('&Dictionary')
        for text,shortcut,fn in [
            ('Import Source…','Ctrl+O',self.import_source),
            ('Random Word','Ctrl+Shift+R',self.random_word),
            ('Export CSV…','',self.export),
            ('Backup Database…','',self.backup_database)
        ]:
            a=QAction(text,self)
            if shortcut:a.setShortcut(shortcut)
            a.triggered.connect(fn); m.addAction(a)
        m.addSeparator()
        for text,fn in [('Clear Database…',self.clear),('Exit',self.close)]:
            a=QAction(text,self); a.triggered.connect(fn); m.addAction(a)

        v=self.menuBar().addMenu('&View')
        for text,fn in [('Favorites',self.favorites),('History',self.history),('A–Z Browse',self.browse),('Statistics',self.statistics),('Focus Search',self.focus)]:
            a=QAction(text,self); a.triggered.connect(fn); v.addAction(a)

        tools=self.menuBar().addMenu('&Tools')
        for text,shortcut,fn in [
            ('Copy Definition','Ctrl+Shift+C',self.copy_definition),
            ('Larger Text','Ctrl++',lambda:self.change_font(1)),
            ('Smaller Text','Ctrl+-',lambda:self.change_font(-1)),
            ('Reset Text Size','Ctrl+0',lambda:self.set_font(18)),
            ('Toggle Dark Theme','',self.toggle_theme)
        ]:
            a=QAction(text,self)
            if shortcut:a.setShortcut(shortcut)
            a.triggered.connect(fn); tools.addAction(a)

        h=self.menuBar().addMenu('&Help')
        a=QAction('About Dictionary',self); a.triggered.connect(self.about); h.addAction(a)
        a=QAction('Supported Imports',self)
        a.triggered.connect(lambda:QMessageBox.information(
            self,'Imports',
            'Built-in: DjVuXML, TXT, EPUB, PDF.\n\n'
            'PDF requires PyMuPDF.\n'
            'The supplied DjVuXML is preferred because it preserves page and OCR-confidence information.\n\n'
            'DRM-protected books are not supported.'
        )); h.addAction(a)

    def style(self):
        if self.dark:
            css = """
            QMainWindow,QWidget{background:#15181d;color:#e9edf2;font-family:"Segoe UI","Noto Sans",sans-serif;font-size:14px}
            QMenuBar{background:#1b1f25;border-bottom:1px solid #303640;padding:4px;color:#e9edf2}
            QMenu{background:#20252c;border:1px solid #3a424d;color:#e9edf2}
            QLineEdit,QComboBox,QPushButton{background:#20252c;color:#edf1f5;border:1px solid #3b444f;border-radius:10px;padding:9px 12px}
            QPushButton:hover{background:#2a313a} QLineEdit:focus,QComboBox:focus{border:1px solid #8295ad}
            #title{font-size:30px;font-weight:750} #muted,#source{color:#9da7b4}
            #section{font-size:16px;font-weight:650;padding:4px}
            QListWidget{background:#1c2127;color:#e9edf2;border:1px solid #343c46;border-radius:13px;padding:7px}
            QListWidget::item{padding:12px;border-radius:8px}
            QListWidget::item:selected{background:#303945;color:#fff}
            #card{background:#1c2127;border:1px solid #343c46;border-radius:18px}
            #word{font-size:38px;font-weight:760;color:#fff}
            #pos{color:#aab6c6;font-size:15px;padding:7px}
            #pron{color:#aeb8c5;font-size:16px;padding:3px 0 10px}
            #definition{background:transparent;color:#e9edf2;border:0;font-size:17px}
            #source{padding-top:8px}
            """
            self.themeBtn.setText('☀')
        else:
            css = """
            QMainWindow,QWidget{background:#f5f6f8;color:#20242a;font-family:"Segoe UI","Noto Sans",sans-serif;font-size:14px}
            QMenuBar{background:#fff;border-bottom:1px solid #e0e4e9;padding:4px}
            QMenu{background:#fff;border:1px solid #dfe3e8}
            QLineEdit,QComboBox,QPushButton{background:#fff;color:#20242a;border:1px solid #d5dbe2;border-radius:10px;padding:9px 12px}
            QPushButton:hover{background:#edf1f5} QLineEdit:focus,QComboBox:focus{border:1px solid #8495ad}
            #title{font-size:30px;font-weight:750} #muted,#source{color:#77808c}
            #section{font-size:16px;font-weight:650;padding:4px}
            QListWidget{background:#fff;border:1px solid #e0e4e9;border-radius:13px;padding:7px}
            QListWidget::item{padding:12px;border-radius:8px}
            QListWidget::item:selected{background:#e6ebf3;color:#20242a}
            #card{background:#fff;border:1px solid #e0e4e9;border-radius:18px}
            #word{font-size:38px;font-weight:760} #pos{color:#65758b;font-size:15px;padding:7px}
            #pron{color:#66707c;font-size:16px;padding:3px 0 10px}
            #definition{background:transparent;border:0;font-size:17px}
            #source{padding-top:8px}
            """
            self.themeBtn.setText('☾')
        self.setStyleSheet(css)

    def refresh(self):
        n=self.db.count(); self.dbstat.setText(f'{n:,} entries  •  {self.db.path}')
        self.all_heads=self.db.headwords()
    def welcome(self):
        self.word.setText('English → Mizo'); self.pron.setText(''); self.pos.setText(''); self.star.setText('☆')
        n=self.db.count();
        self.defn.setHtml(f'''<h2>Welcome</h2><p>Your dictionary contains <b>{n:,}</b> indexed entries.</p><p>Type an English word above. The dictionary supports exact lookup, prefix suggestions, full-text search, Mizo meaning search, favorites, history and A–Z browsing.</p><p><b>Source-aware:</b> entries imported from the supplied DjVuXML retain the scanned book page and OCR confidence where available.</p>'''); self.source.setText('')
    def focus(self): self.query.setFocus(); self.query.selectAll()
    def live(self,text):
        if len(text.strip())>=2: self.lookup(live=True)
    def lookup(self,live=False):
        q=self.query.text().strip(); self.list.clear(); self.rows=[]
        if not q:
            self.section.setText('Suggestions'); self.welcome(); return
        mode=self.mode.currentText()
        if mode=='Exact English': rows=self.db.exact(q)
        elif mode=='English starts with': rows=self.db.prefix(q)
        elif mode=='Mizo → English': rows=self.db.search_all(q)
        elif mode=='Search all text': rows=self.db.fts(q)
        else:
            rows=self.db.exact(q)
            if not rows: rows=self.db.prefix(q,100)
            if not rows: rows=self.db.fts(q,100)
            if not rows: rows=self.db.search_all(q,100)
            if not rows:
                close=difflib.get_close_matches(q,self.all_heads,n=12,cutoff=.62)
                rows=[r for h in close for r in self.db.exact(h)]
        self.rows=rows
        for r in rows:
            item=QListWidgetItem(); item.setData(Qt.UserRole,r); item.setText(r[1] + (f"   • {r[3]}" if r[3] else '')); self.list.addItem(item)
        self.section.setText(f'{len(rows):,} result'+('s' if len(rows)!=1 else ''))
        if rows:
            self.list.setCurrentRow(0); self.display(rows[0])
        else:
            self.word.setText(q); self.pos.setText(''); self.pron.setText(''); self.star.setText('☆'); self.defn.setHtml('<h3>No match</h3><p>Try another spelling, use <b>Search all text</b>, or check the A–Z list.</p>'); self.source.setText('')
    def display(self,r):
        if not r:return
        self.current=r
        eid,h,pron,pos,definition,page,scan,conf,source=r
        self.word.setText(h); self.pos.setText(pos or '')
        self.pron.setText(f'/ {pron} /' if pron else 'Pronunciation not recorded')
        d=html.escape(definition).replace('\\n','<br>')
        d=re.sub(r'\\b(eg\\.?|e\\.g\\.?|syn\\.?|ant\\.?|see|compare)\\b',r'<b>\\1</b>',d,flags=re.I)
        self.defn.setHtml(f'<div style="font-size:{self.font_size}px;line-height:1.72">{d}</div>')
        parts=[]
        if page: parts.append(f'Book page {page}')
        if scan: parts.append(f'Scan page {scan}')
        if conf: parts.append(f'OCR confidence {conf:.0f}%')
        parts.append(source or 'Local database')
        self.source.setText('  •  '.join(parts))
        self.star.setText('★' if self.db.is_favorite(eid) else '☆')
        self.db.add_history(eid,h)
        i=self.list.currentRow(); n=self.list.count()
        self.resultPos.setText(f'{i+1} of {n}' if n else '')
        self.prevBtn.setEnabled(i>0); self.nextBtn.setEnabled(0<=i<n-1)

    def current_row_index(self): return self.list.currentRow()
    def prev(self):
        i=self.current_row_index()
        if i>0:
            self.list.setCurrentRow(i-1); self.display(self.list.currentItem().data(Qt.UserRole))
    def next(self):
        i=self.current_row_index()
        if 0<=i<self.list.count()-1:
            self.list.setCurrentRow(i+1); self.display(self.list.currentItem().data(Qt.UserRole))
    def favorite(self):
        if self.current:
            state=self.db.toggle_favorite(self.current[0]); self.star.setText('★' if state else '☆')
    def favorites(self): self.show_rows(self.db.favorites(),'★ Favorites')
    def history(self): self.show_rows(self.db.history(),'🕘 History')
    def show_rows(self,rows,title):
        self.rows=rows; self.list.clear(); self.section.setText(f'{title}  •  {len(rows):,}')
        for r in rows:
            i=QListWidgetItem(r[1]+(f'  •  {r[3]}' if r[3] else '')); i.setData(Qt.UserRole,r); self.list.addItem(i)
        if rows:
            self.list.setCurrentRow(0); self.display(rows[0])
        else:
            self.resultPos.setText(''); self.prevBtn.setEnabled(False); self.nextBtn.setEnabled(False)
    def browse(self):
        d=QDialog(self); d.setWindowTitle('A–Z Dictionary Browser'); d.resize(800,600); l=QVBoxLayout(d)
        row=QHBoxLayout(); combo=QComboBox(); combo.addItem('All'); combo.addItems(list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')); row.addWidget(combo); s=QLineEdit(); s.setPlaceholderText('Filter headwords…'); row.addWidget(s,1); l.addLayout(row)
        lw=QListWidget(); l.addWidget(lw,1)
        def fill():
            prefix='' if combo.currentText()=='All' else combo.currentText(); term=s.text().casefold(); lw.clear()
            for h in self.all_heads:
                if prefix and not h.upper().startswith(prefix): continue
                if term and term not in h.casefold(): continue
                lw.addItem(h)
        combo.currentTextChanged.connect(fill); s.textChanged.connect(fill); lw.itemDoubleClicked.connect(lambda i:(self.query.setText(i.text()),d.accept(),self.lookup()))
        fill(); d.exec()
    def import_source(self):
        path,_=QFileDialog.getOpenFileName(self,'Import Dictionary Source',str(Path.home()),'Dictionary sources (*.xml *.txt *.epub *.pdf);;All files (*)')
        if not path:return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try: rows=import_source(path)
        except Exception as e:
            QApplication.restoreOverrideCursor(); QMessageBox.critical(self,'Import failed',str(e)); return
        QApplication.restoreOverrideCursor()
        if not rows: QMessageBox.warning(self,'No entries','No dictionary-style entries were detected.'); return
        dlg=ImportPreview(self,rows)
        if dlg.exec()==QDialog.Accepted:
            selected=dlg.selected();
            if selected:
                n=self.db.insert_many(selected); self.refresh(); QMessageBox.information(self,'Import complete',f'Imported {n:,} entries.\n\nDatabase now contains {self.db.count():,} entries.')
    def export(self):
        if not self.db.count():return
        path,_=QFileDialog.getSaveFileName(self,'Export CSV',str(Path.home()/'english_mizo_dictionary.csv'),'CSV (*.csv)')
        if not path:return
        rows=self.db.con.execute('SELECT headword,pronunciation,pos,definition,book_page,scan_page,confidence,source FROM entries ORDER BY headword')
        with open(path,'w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f); w.writerow(['English','Pronunciation','Part of Speech','Mizo / Definition','Book Page','Scan Page','OCR Confidence','Source']); w.writerows(rows)
        QMessageBox.information(self,'Export complete',f'Saved to:\n{path}')
    def copy_definition(self):
        if not self.current:
            return
        _, h, pron, pos, definition, page, scan, conf, source = self.current
        lines = [h]
        if pron:
            lines.append(f"/{pron}/")
        if pos:
            lines.append(pos)
        lines.append(definition)
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Definition copied to clipboard", 2500)

    def change_font(self, delta):
        self.set_font(max(12, min(32, self.font_size + delta)))

    def set_font(self, size):
        self.font_size = size
        if self.current:
            self.display(self.current)

    def toggle_theme(self):
        self.dark = not self.dark
        self.style()
        self.statusBar().showMessage(
            "Dark theme enabled" if self.dark else "Light theme enabled", 2000
        )

    def random_word(self):
        if not self.all_heads:
            QMessageBox.information(self, "Random Word", "The dictionary is empty.")
            return
        word = random.choice(self.all_heads)
        self.query.setText(word)
        self.mode.setCurrentText("Exact English")
        self.lookup()

    def statistics(self):
        n = self.db.count()
        fav = len(self.db.favorites())
        hist = len(self.db.history())
        try:
            srcs = self.db.con.execute(
                "SELECT source, COUNT(*) FROM entries "
                "GROUP BY source ORDER BY COUNT(*) DESC"
            ).fetchall()
        except Exception:
            srcs = []

        d = QDialog(self)
        d.setWindowTitle("Dictionary Statistics")
        d.resize(620, 480)
        l = QVBoxLayout(d)
        l.addWidget(QLabel(
            f"<h2>English–Mizo Dictionary</h2>"
            f"<p><b>{n:,}</b> indexed entries<br>"
            f"<b>{len(self.all_heads):,}</b> unique headwords<br>"
            f"<b>{fav:,}</b> favorites<br>"
            f"<b>{hist:,}</b> recent history records</p>"
        ))

        box = QGroupBox("Sources")
        bl = QVBoxLayout(box)
        if srcs:
            for name, count in srcs[:20]:
                bl.addWidget(QLabel(f"{count:,}  —  {name or 'Local'}"))
        else:
            bl.addWidget(QLabel("No source information available."))
        l.addWidget(box, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        l.addWidget(bb)
        d.exec()

    def backup_database(self):
        if not self.db.path.exists():
            QMessageBox.warning(self, "Backup", "Database file does not exist yet.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Backup Dictionary Database",
            str(Path.home() / "english_mizo_dictionary_backup.db"),
            "SQLite database (*.db)"
        )
        if not path:
            return

        try:
            self.db.con.commit()
            shutil.copy2(self.db.path, path)
            QMessageBox.information(
                self, "Backup complete", f"Backup saved to:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Backup failed", str(e))

    def clear(self):
        if QMessageBox.question(self,'Clear database','Delete all dictionary entries, favorites and history?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.db.clear(); self.refresh(); self.list.clear(); self.welcome()
    def about(self):
        QMessageBox.information(self,'About',f'<b>{APP}</b><p>A local-first English–Mizo dictionary interface built around the supplied 1997 dictionary OCR. No AI, internet connection or heavy ML framework is required.</p><p>Database: {self.db.path}</p><p>Use the DjVuXML source when you want page and OCR-confidence provenance.</p>')
    def closeEvent(self,e): self.db.close(); e.accept()


def main():
    app=QApplication(sys.argv); app.setApplicationName(APP); app.setStyle('Fusion'); win=Dictionary(); win.show(); sys.exit(app.exec())
if __name__=='__main__': main()
