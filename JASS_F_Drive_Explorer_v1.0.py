import os,sys,subprocess
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt,QDir,QThread,Signal
from PySide6.QtGui import QPixmap,QFont
from PySide6.QtWidgets import *
ROOT=Path(r'F:\\')
IMG={'.jpg','.jpeg','.png','.gif','.bmp','.webp','.tif','.tiff'}
TEXT={'.txt','.log','.md','.ini','.cfg','.csv','.json','.xml','.yaml','.yml','.py','.js','.css','.html','.htm','.rtf'}
EXCEL={'.xls','.xlsx','.xlsm','.ods','.csv'}
DOC={'.doc','.docx','.odt','.rtf'}
VIDEO={'.mp4','.mkv','.avi','.mov','.wmv','.webm'}
AUDIO={'.mp3','.wav','.flac','.m4a','.aac','.ogg'}
ARCH={'.zip','.7z','.rar','.tar','.gz','.bz2'}
def cat(p):
 e=p.suffix.lower(); return 'Images' if e in IMG else 'PDF' if e=='.pdf' else 'Excel / Data' if e in EXCEL else 'Documents' if e in DOC else 'Text' if e in TEXT else 'Video' if e in VIDEO else 'Audio' if e in AUDIO else 'Archives' if e in ARCH else 'Other'
def size(n):
 for u in ['B','KB','MB','GB','TB']:
  if n<1024 or u=='TB': return f'{n:.1f} {u}'
  n/=1024
def trash(p):
 try:
  from send2trash import send2trash; send2trash(str(p)); return True
 except Exception:return False
class Worker(QThread):
 done=Signal(object)
 def run(self):
  s=[0,0,0,0,0,0]
  try:
   for b,d,fs in os.walk(ROOT,followlinks=False):
    s[1]+=len(d)
    for f in fs:
     try:
      p=Path(b)/f;n=p.stat().st_size;s[0]+=1;s[2]+=n;c=cat(p);s[3]+=c=='PDF';s[4]+=c=='Images';s[5]+=c=='Excel / Data'
     except OSError:pass
  except OSError:pass
  self.done.emit(s)
class Editor(QDialog):
 def __init__(self,p,parent=None):
  super().__init__(parent);self.p=p;self.setWindowTitle('Edit — '+p.name);self.resize(900,650);l=QVBoxLayout(self);self.e=QTextEdit();self.e.setFont(QFont('Consolas',10));self.e.setPlainText(p.read_text(encoding='utf-8',errors='replace'));l.addWidget(self.e);b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(self.save);b.rejected.connect(self.reject);l.addWidget(b)
 def save(self):
  try:self.p.write_text(self.e.toPlainText(),encoding='utf-8');self.accept()
  except Exception as e:QMessageBox.critical(self,'Save failed',str(e))
class Main(QMainWindow):
 def __init__(self):
  super().__init__();self.setWindowTitle('JASS F: DRIVE EXPLORER');self.resize(1450,850);self.cur=ROOT;self.hist=[];self.hi=-1;self.worker=None;self.ui();self.style();self.nav(ROOT)
 def ui(self):
  c=QWidget();self.setCentralWidget(c);L=QVBoxLayout(c);L.setContentsMargins(12,12,12,8)
  r=QHBoxLayout();t=QLabel('JASS F: DRIVE  •  FILE EXPLORER');t.setObjectName('title');r.addWidget(t);r.addStretch();self.search=QLineEdit();self.search.setPlaceholderText('Search all of F:\\ ...');self.search.returnPressed.connect(self.search_all);r.addWidget(self.search);q=QPushButton('SEARCH');q.clicked.connect(self.search_all);r.addWidget(q);L.addLayout(r)
  cards=QHBoxLayout();self.cards=[]
  for n,v in [('FILES','0'),('FOLDERS','0'),('TOTAL SIZE','0 B'),('PDF','0'),('IMAGES','0'),('EXCEL / DATA','0')]:
   f=QFrame();f.setObjectName('card');x=QVBoxLayout(f);a=QLabel(n);a.setObjectName('cl');b=QLabel(v);b.setObjectName('cv');x.addWidget(a);x.addWidget(b);f.val=b;cards.addWidget(f);self.cards.append(f)
  L.addLayout(cards)
  bar=QHBoxLayout()
  for n,fn in [('←',self.back),('→',self.forward),('↑ UP',self.up),('REFRESH',self.refresh),('NEW FOLDER',self.newfolder),('RENAME',self.rename),('DELETE',self.delete),('OPEN',self.open),('EDIT',self.edit),('PROPERTIES',self.properties)]:
   b=QPushButton(n);b.clicked.connect(fn);bar.addWidget(b)
  bar.addStretch();self.filter=QComboBox();self.filter.addItems(['All types','Images','PDF','Excel / Data','Documents','Text','Video','Audio','Archives','Other']);self.filter.currentTextChanged.connect(self.refresh_files);bar.addWidget(self.filter);L.addLayout(bar)
  self.crumb=QLabel();self.crumb.setObjectName('crumb');L.addWidget(self.crumb)
  sp=QSplitter(Qt.Horizontal);L.addWidget(sp,1)
  self.model=QFileSystemModel();self.model.setFilter(QDir.AllDirs|QDir.NoDotAndDotDot);self.model.setRootPath(str(ROOT));self.tree=QTreeView();self.tree.setModel(self.model);self.tree.setRootIndex(self.model.index(str(ROOT)));self.tree.clicked.connect(lambda i:self.nav(Path(self.model.filePath(i))));sp.addWidget(self.tree)
  mid=QWidget();ml=QVBoxLayout(mid);self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['TYPE','NAME','SIZE','MODIFIED','LOCATION']);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.Stretch);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.table.doubleClicked.connect(self.double);self.table.itemSelectionChanged.connect(self.preview);self.table.setContextMenuPolicy(Qt.CustomContextMenu);self.table.customContextMenuRequested.connect(self.menu);ml.addWidget(self.table);sp.addWidget(mid)
  pv=QFrame();pv.setObjectName('preview');pl=QVBoxLayout(pv);self.pt=QLabel('PREVIEW');self.pt.setObjectName('pt');pl.addWidget(self.pt);self.prev=QLabel('Select a file or folder');self.prev.setAlignment(Qt.AlignCenter);self.prev.setWordWrap(True);pl.addWidget(self.prev,1);sp.addWidget(pv);sp.setSizes([280,700,400]);self.statusBar().showMessage('Ready')
 def style(self):
  self.setStyleSheet('''QWidget{background:#0b1016;color:#d7e2ea;font-family:"Segoe UI"}#title{color:#39e6ff;font-size:22px;font-weight:700}#crumb{color:#6deaff;padding:6px;background:#101923;border:1px solid #1c3947}#card,#preview{background:#101923;border:1px solid #214452;border-radius:8px}#cl{color:#7895a3;font-size:10px;font-weight:700}#cv{color:#39e6ff;font-size:20px;font-weight:700}#pt{color:#39e6ff;font-weight:700;font-size:14px}QPushButton{background:#111d27;border:1px solid #285467;padding:7px 11px;border-radius:5px}QPushButton:hover{background:#173141;border-color:#39e6ff}QLineEdit,QComboBox{background:#0e171f;border:1px solid #285467;padding:7px;border-radius:5px}QTableWidget,QTreeView{background:#0d141b;border:1px solid #1d3a48}QTableWidget::item:selected,QTreeView::item:selected{background:#16465a;color:white}QHeaderView::section{background:#101d27;color:#70dff0;padding:6px}''')
 def nav(self,p,add=True):
  if not p.is_dir():return
  if add:
   self.hist=self.hist[:self.hi+1];self.hist.append(p);self.hi+=1
  self.cur=p;self.crumb.setText(str(p));self.refresh_files();self.refresh_stats()
 def back(self):
  if self.hi>0:self.hi-=1;self.nav(self.hist[self.hi],False)
 def forward(self):
  if self.hi<len(self.hist)-1:self.hi+=1;self.nav(self.hist[self.hi],False)
 def up(self):
  if self.cur!=ROOT:self.nav(self.cur.parent)
 def refresh(self):self.refresh_files();self.refresh_stats()
 def refresh_stats(self):
  if self.worker and self.worker.isRunning():return
  self.worker=Worker();self.worker.done.connect(self.stats);self.worker.start()
 def stats(self,s):
  for f,v in zip(self.cards,[f'{s[0]:,}',f'{s[1]:,}',size(s[2]),f'{s[3]:,}',f'{s[4]:,}',f'{s[5]:,}']):f.val.setText(v)
 def refresh_files(self):
  self.table.setRowCount(0)
  try: es=sorted(self.cur.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))
  except OSError:return
  fl=self.filter.currentText()
  for p in es:
   if p.is_file() and fl!='All types' and cat(p)!=fl:continue
   row=self.table.rowCount();self.table.insertRow(row);st=None
   try:st=p.stat()
   except OSError:pass
   vals=['FOLDER' if p.is_dir() else cat(p),p.name,'—' if p.is_dir() else size(st.st_size) if st else '?',datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M') if st else '?',str(p.parent)]
   for col,v in enumerate(vals):
    it=QTableWidgetItem(v);it.setData(Qt.UserRole,str(p));self.table.setItem(row,col,it)
  self.statusBar().showMessage(f'{self.table.rowCount():,} items')
 def selected(self):return [Path(self.table.item(i.row(),1).data(Qt.UserRole)) for i in self.table.selectionModel().selectedRows()]
 def double(self,i):
  p=Path(self.table.item(i.row(),1).data(Qt.UserRole));self.nav(p) if p.is_dir() else self.openpath(p)
 def openpath(self,p):
  try:os.startfile(str(p))
  except Exception as e:QMessageBox.critical(self,'Open failed',str(e))
 def open(self):
  x=self.selected()
  if x:self.openpath(x[0])
 def edit(self):
  x=self.selected()
  if x:
   p=x[0]
   if p.is_file() and p.suffix.lower() in TEXT: 
    if Editor(p,self).exec():self.refresh_files()
   else:self.openpath(p)
 def newfolder(self):
  n,ok=QInputDialog.getText(self,'New Folder','Folder name:')
  if ok and n.strip():
   try:(self.cur/n.strip()).mkdir();self.refresh()
   except Exception as e:QMessageBox.critical(self,'Create failed',str(e))
 def rename(self):
  x=self.selected()
  if len(x)!=1:return
  n,ok=QInputDialog.getText(self,'Rename','New name:',text=x[0].name)
  if ok and n.strip() and n.strip()!=x[0].name:
   try:x[0].rename(x[0].with_name(n.strip()));self.refresh()
   except Exception as e:QMessageBox.critical(self,'Rename failed',str(e))
 def delete(self):
  x=self.selected()
  if not x:return
  if QMessageBox.question(self,'Confirm Delete',f'Send {len(x)} item(s) to Recycle Bin?',QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
  bad=[str(p) for p in x if not trash(p)]
  if bad:QMessageBox.warning(self,'Delete warning','Install Send2Trash with:\npy -m pip install Send2Trash\n\nFailed:\n'+'\n'.join(bad[:20]))
  self.refresh()
 def properties(self):
  x=self.selected()
  if not x:return
  p=x[0];st=None
  try:st=p.stat()
  except:pass
  text=f'Name: {p.name}\n\nType: {"Folder" if p.is_dir() else cat(p)}\n\nLocation: {p.parent}\n\nSize: {size(st.st_size) if st and p.is_file() else "—"}\n\nModified: {datetime.fromtimestamp(st.st_mtime) if st else "—"}'
  QMessageBox.information(self,'Properties',text)
 def preview(self):
  x=self.selected()
  if not x:self.prev.setText('Select a file or folder');self.prev.setPixmap(QPixmap());return
  p=x[0];self.pt.setText(p.name)
  if p.is_dir():self.prev.setPixmap(QPixmap());self.prev.setText(f'FOLDER\n\n{p}');return
  if p.suffix.lower() in IMG:
   q=QPixmap(str(p))
   if not q.isNull():self.prev.setPixmap(q.scaled(420,560,Qt.KeepAspectRatio,Qt.SmoothTransformation));return
  if p.suffix.lower()=='.pdf':
   try:
    import fitz;d=fitz.open(str(p));im=QPixmap();im.loadFromData(d[0].get_pixmap(matrix=fitz.Matrix(1.2,1.2),alpha=False).tobytes('png'));d.close();self.prev.setPixmap(im.scaled(420,560,Qt.KeepAspectRatio,Qt.SmoothTransformation));return
   except:pass
  if p.suffix.lower() in TEXT:
   try:self.prev.setPixmap(QPixmap());self.prev.setText(p.read_text(encoding='utf-8',errors='replace')[:10000]);self.prev.setAlignment(Qt.AlignLeft|Qt.AlignTop);return
   except:pass
  self.prev.setPixmap(QPixmap());self.prev.setText(f'{cat(p)}\n\n{size(p.stat().st_size) if p.exists() else "?"}\n\n{p}');self.prev.setAlignment(Qt.AlignCenter)
 def search_all(self):
  q=self.search.text().strip().lower();self.table.setRowCount(0)
  if not q:return self.nav(ROOT)
  fl=self.filter.currentText();n=0
  for b,d,fs in os.walk(ROOT,followlinks=False):
   for f in fs:
    p=Path(b)/f
    if q in f.lower() and (fl=='All types' or cat(p)==fl):
     row=self.table.rowCount();self.table.insertRow(row);n+=1
     try:st=p.stat()
     except:st=None
     vals=[cat(p),p.name,size(st.st_size) if st else '?',datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M') if st else '?',str(p.parent)]
     for c,v in enumerate(vals):it=QTableWidgetItem(v);it.setData(Qt.UserRole,str(p));self.table.setItem(row,c,it)
  self.crumb.setText(f'SEARCH RESULTS  •  {n:,} matches');self.statusBar().showMessage(f'{n:,} results')
 def menu(self,pos):
  m=QMenu(self);a=m.addAction('Open');b=m.addAction('Edit');m.addSeparator();c=m.addAction('Rename');d=m.addAction('Delete to Recycle Bin');e=m.addAction('Properties');x=m.exec(self.table.viewport().mapToGlobal(pos))
  if x==a:self.open()
  elif x==b:self.edit()
  elif x==c:self.rename()
  elif x==d:self.delete()
  elif x==e:self.properties()
 def keyPressEvent(self,e):
  if e.key()==Qt.Key_F2:self.rename()
  elif e.key()==Qt.Key_Delete:self.delete()
  elif e.key()==Qt.Key_F5:self.refresh()
  elif e.key()==Qt.Key_Backspace:self.up()
  else:super().keyPressEvent(e)
def main():
 app=QApplication(sys.argv);w=Main();w.show();sys.exit(app.exec())
if __name__=='__main__':main()
