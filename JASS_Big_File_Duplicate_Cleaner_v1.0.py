import os, sys, hashlib, shutil, threading, csv
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal, Qt, QUrl
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
QGridLayout,QGroupBox,QLabel,QPushButton,QComboBox,QListWidget,QListWidgetItem,
QCheckBox,QDoubleSpinBox,QTabWidget,QTableWidget,QTableWidgetItem,QHeaderView,
QAbstractItemView,QFileDialog,QMessageBox,QProgressBar,QTextEdit,QDialog,QDialogButtonBox)

APP="JASS Big File & Duplicate Cleaner"
SKIP_WIN=(r"\Windows",r"\Program Files",r"\Program Files (x86)",r"\ProgramData",r"\$Recycle.Bin",r"\System Volume Information")

def hsize(n):
    x=float(n)
    for u in ("B","KB","MB","GB","TB"):
        if x<1024 or u=="TB": return f"{x:.1f} {u}" if u!="B" else f"{int(x)} B"
        x/=1024

def hidden(p):
    if os.name!="nt": return False
    try:
        import ctypes
        a=ctypes.windll.kernel32.GetFileAttributesW(str(p))
        return a!=-1 and bool(a&6)
    except: return False

def skip(p, include):
    p=os.path.abspath(p)
    if os.name=="nt":
        low=p.lower()
        if not include and hidden(p): return True
        for s in SKIP_WIN:
            if low.startswith(s.lower()) or low==s.lower().replace("\\",""):
                return True
    return False

def files(roots,include,stop):
    seen=set()
    for root in roots:
        if stop.is_set(): return
        root=os.path.abspath(root)
        if os.path.isfile(root):
            yield root; continue
        for cur,dirs,names in os.walk(root,topdown=True,followlinks=False):
            if stop.is_set(): return
            dirs[:]=[d for d in dirs if not skip(os.path.join(cur,d),include)]
            for n in names:
                p=os.path.join(cur,n)
                if not include and hidden(p): continue
                k=os.path.normcase(os.path.abspath(p))
                if k not in seen:
                    seen.add(k); yield p

def sha(p,stop):
    try:
        z=hashlib.sha256()
        with open(p,"rb") as f:
            while True:
                if stop.is_set(): return None
                b=f.read(1024*1024)
                if not b: break
                z.update(b)
        return z.hexdigest()
    except: return None

class Worker(QObject):
    progress=Signal(int,str); done=Signal(object,object,int); error=Signal(str)
    def __init__(self,roots,threshold,mode,include):
        super().__init__(); self.roots=roots; self.threshold=threshold; self.mode=mode; self.include=include; self.stop_event=threading.Event()
    def stop(self): self.stop_event.set()
    def run(self):
        try:
            large=[]; count=0
            for p in files(self.roots,self.include,self.stop_event):
                if self.stop_event.is_set(): return
                try:
                    st=os.stat(p); count+=1
                    if self.mode in ("large","both") and st.st_size>=self.threshold:
                        large.append((p,st.st_size,st.st_mtime))
                    if count%200==0: self.progress.emit(5,f"Scanned {count:,} files...")
                except: pass
            groups=[]
            if self.mode in ("duplicates","both"):
                sizes={}
                for p in files(self.roots,self.include,self.stop_event):
                    try:
                        s=os.path.getsize(p)
                        if s>0: sizes.setdefault(s,[]).append(p)
                    except: pass
                cand=[g for g in sizes.values() if len(g)>1]; total=sum(map(len,cand)); done=0
                hashes={}
                for g in cand:
                    for p in g:
                        if self.stop_event.is_set(): return
                        try: s=os.path.getsize(p)
                        except: continue
                        d=sha(p,self.stop_event); done+=1
                        if d: hashes.setdefault((s,d),[]).append(p)
                        self.progress.emit(min(99,int(done*100/max(1,total))),f"Comparing duplicate candidates {done:,}/{total:,}...")
                groups=[g for g in hashes.values() if len(g)>1]
            self.done.emit(sorted(large,key=lambda x:x[1],reverse=True),groups,count)
        except Exception as e: self.error.emit(str(e))

def recycle(p):
    try:
        from send2trash import send2trash
        send2trash(p); return True,"Recycle Bin"
    except ImportError: pass
    except Exception as e: return False,str(e)
    if os.name=="nt":
        try:
            import ctypes
            from ctypes import wintypes
            class SH(ctypes.Structure):
                _fields_=[("hwnd",wintypes.HWND),("wFunc",wintypes.UINT),("pFrom",wintypes.LPCWSTR),("pTo",wintypes.LPCWSTR),("fFlags",wintypes.UINT),("aborted",wintypes.BOOL),("maps",wintypes.LPVOID),("title",wintypes.LPCWSTR)]
            x=SH(); x.wFunc=3; x.pFrom=p+"\0\0"; x.fFlags=0x0040|0x0010|0x0004
            r=ctypes.windll.shell32.SHFileOperationW(ctypes.byref(x))
            return (r==0 and not x.aborted,"Recycle Bin" if r==0 else f"Error {r}")
        except Exception as e: return False,str(e)
    return False,"Recycle Bin unavailable; install send2trash"

class Help(QDialog):
    def __init__(self,p):
        super().__init__(p); self.setWindowTitle("Safety & Help"); self.resize(650,430)
        l=QVBoxLayout(self); t=QTextEdit(); t.setReadOnly(True)
        t.setHtml("<h2>JASS Big File &amp; Duplicate Cleaner v1.0</h2>"
        "<p>Scan only locations you explicitly select. Scanning never deletes anything.</p>"
        "<h3>Duplicate detection</h3><p>Files are grouped by size and then verified using SHA-256. "
        "Matching hashes mean the file contents matched when scanned.</p>"
        "<h3>Deletion</h3><p>The normal action sends selected files to the Recycle Bin when available. "
        "Permanent deletion is a separate action with an extra confirmation.</p>"
        "<h3>USB</h3><p>Select the USB drive or a folder on it. Keep the drive connected while working.</p>")
        l.addWidget(t); b=QDialogButtonBox(QDialogButtonBox.Close); b.rejected.connect(self.reject); l.addWidget(b)

class Main(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(APP+" v1.0"); self.resize(1250,760)
        self.large=[]; self.dups=[]; self.thread=None; self.worker=None
        self.setStyleSheet("""QMainWindow{background:#f5f7fa} QGroupBox{font-weight:600;border:1px solid #d5dbe4;border-radius:8px;margin-top:10px;padding-top:10px;background:white} QPushButton{padding:7px 13px;border:1px solid #cbd3df;border-radius:6px;background:white} QPushButton:hover{background:#eef3f9} QLineEdit,QComboBox,QDoubleSpinBox{padding:6px;border:1px solid #cbd3df;border-radius:6px;background:white} QTableWidget{background:white;border:1px solid #d5dbe4} QHeaderView::section{background:#eef2f6;padding:7px;border:0;border-bottom:1px solid #d5dbe4}""")
        c=QWidget(); self.setCentralWidget(c); root=QVBoxLayout(c)
        title=QLabel("JASS Big File & Duplicate Cleaner  v1.0"); title.setFont(QFont("Segoe UI",20,QFont.Bold)); root.addWidget(title)
        root.addWidget(QLabel("Find large files and selectively remove duplicates from hard disks and USB drives."))
        box=QGroupBox("Scan Locations"); g=QGridLayout(box)
        self.drives=QComboBox(); self.refresh_drives(); g.addWidget(QLabel("Drive:"),0,0); g.addWidget(self.drives,0,1)
        add=QPushButton("Add Folder..."); add.clicked.connect(self.add); g.addWidget(add,0,2)
        self.loc=QListWidget(); self.loc.setMaximumHeight(85); g.addWidget(self.loc,1,0,1,3)
        rem=QPushButton("Remove Location"); rem.clicked.connect(lambda:self.loc.takeItem(self.loc.currentRow()) if self.loc.currentRow()>=0 else None); g.addWidget(rem,2,0)
        self.hidden=QCheckBox("Include hidden/system files"); g.addWidget(self.hidden,2,1); root.addWidget(box)
        s=QGroupBox("Scan Settings"); sg=QGridLayout(s)
        self.threshold=QDoubleSpinBox(); self.threshold.setRange(1,999999); self.threshold.setValue(500); self.threshold.setDecimals(0); self.threshold.setSuffix(" MB")
        sg.addWidget(QLabel("Large-file threshold:"),0,0); sg.addWidget(self.threshold,0,1)
        self.mode=QComboBox(); self.mode.addItem("Large files + duplicates","both"); self.mode.addItem("Large files only","large"); self.mode.addItem("Duplicates only","duplicates"); sg.addWidget(QLabel("Mode:"),0,2); sg.addWidget(self.mode,0,3)
        self.scan=QPushButton("Start Scan"); self.scan.clicked.connect(self.start); sg.addWidget(self.scan,1,0)
        self.stop=QPushButton("Stop"); self.stop.setEnabled(False); self.stop.clicked.connect(self.stop_scan); sg.addWidget(self.stop,1,1)
        clear=QPushButton("Clear Results"); clear.clicked.connect(self.clear); sg.addWidget(clear,1,2); root.addWidget(s)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1)
        self.lt=QTableWidget(0,4); self.lt.setHorizontalHeaderLabels(["Select","Size","Modified","Path"]); self.setup(self.lt); self.tabs.addTab(self.tab(self.lt,"large"),"Large Files")
        self.dt=QTableWidget(0,5); self.dt.setHorizontalHeaderLabels(["Select","Group","Size","Copies","Path"]); self.setup(self.dt); self.tabs.addTab(self.tab(self.dt,"dup"),"Duplicate Files")
        self.summary=QLabel("Ready. Add a folder or drive and start a scan."); root.addWidget(self.summary); self.prog=QProgressBar(); root.addWidget(self.prog)
        self.statusBar().showMessage("Ready")
        a=self.menuBar().addAction("About / Safety"); a.triggered.connect(lambda:Help(self).exec())

    def setup(self,t):
        t.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents); t.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents)
        if t.columnCount()>2: t.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents)
        if t.columnCount()>3: t.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(t.columnCount()-1,QHeaderView.Stretch); t.setSelectionBehavior(QAbstractItemView.SelectRows); t.setEditTriggers(QAbstractItemView.NoEditTriggers); t.doubleClicked.connect(lambda:self.open_folder(t))

    def tab(self,t,kind):
        w=QWidget(); l=QVBoxLayout(w); b=QHBoxLayout()
        for txt,fn in [("Select All",lambda:self.allcheck(t,True)),("Select None",lambda:self.allcheck(t,False)),("Open Folder",lambda:self.open_folder(t)),("Recycle Selected",lambda:self.remove(t,False)),("Permanent Delete...",lambda:self.remove(t,True)),("Export CSV",lambda:self.export(t,kind))]:
            q=QPushButton(txt); q.clicked.connect(fn); b.addWidget(q)
        b.addStretch(); l.addLayout(b); l.addWidget(t); return w

    def refresh_drives(self):
        self.drives.clear()
        if os.name=="nt":
            import string,ctypes
            for x in string.ascii_uppercase:
                r=x+":\\"
                if os.path.exists(r):
                    try: free=shutil.disk_usage(r).free
                    except: free=0
                    typ="Disk"
                    try: typ="USB/Removable" if ctypes.windll.kernel32.GetDriveTypeW(r)==2 else "Local Disk"
                    except: pass
                    self.drives.addItem(f"{r} — {typ} — {hsize(free)} free",r)
        else: self.drives.addItem("/","/")

    def add(self):
        p=QFileDialog.getExistingDirectory(self,"Choose folder or USB drive")
        if p and p not in [self.loc.item(i).data(Qt.UserRole) for i in range(self.loc.count())]:
            q=QListWidgetItem(p); q.setData(Qt.UserRole,p); self.loc.addItem(q)

    def roots(self): return [self.loc.item(i).data(Qt.UserRole) for i in range(self.loc.count())]

    def start(self):
        r=self.roots()
        if not r: QMessageBox.information(self,"No location","Add at least one folder or drive."); return
        self.clear(); self.thread=QThread(); self.worker=Worker(r,int(self.threshold.value()*1024*1024),self.mode.currentData(),self.hidden.isChecked())
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.progress.connect(lambda n,s:(self.prog.setValue(n),self.statusBar().showMessage(s)))
        self.worker.done.connect(self.finish); self.worker.error.connect(lambda e:QMessageBox.critical(self,"Scan Error",e))
        self.worker.done.connect(self.thread.quit); self.worker.error.connect(self.thread.quit); self.thread.finished.connect(self.thread_done)
        self.scan.setEnabled(False); self.stop.setEnabled(True); self.thread.start()

    def stop_scan(self):
        if self.worker: self.worker.stop(); self.stop.setEnabled(False); self.statusBar().showMessage("Stopping...")

    def thread_done(self):
        self.scan.setEnabled(True); self.stop.setEnabled(False); self.worker=None; self.thread=None

    def finish(self,large,groups,n):
        self.large=large; self.dups=groups; self.fill_large(); self.fill_dup(); waste=sum((len(g)-1)*os.path.getsize(g[0]) for g in groups if g and os.path.exists(g[0]))
        self.summary.setText(f"Scanned {n:,} files • Large files: {len(large):,} • Duplicate groups: {len(groups):,} • Potential duplicate space: {hsize(waste)}"); self.prog.setValue(100); self.statusBar().showMessage("Scan complete")

    def cell(self,p): 
        x=QTableWidgetItem(); x.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable); x.setCheckState(Qt.Unchecked); x.setData(Qt.UserRole,p); return x

    def fill_large(self):
        t=self.lt; t.setRowCount(0)
        for p,s,m in self.large:
            r=t.rowCount(); t.insertRow(r); t.setItem(r,0,self.cell(p)); t.setItem(r,1,QTableWidgetItem(hsize(s))); t.setItem(r,2,QTableWidgetItem(datetime.fromtimestamp(m).strftime("%Y-%m-%d %H:%M"))); t.setItem(r,3,QTableWidgetItem(p))

    def fill_dup(self):
        t=self.dt; t.setRowCount(0)
        for gi,g in enumerate(self.dups,1):
            try:s=os.path.getsize(g[0])
            except:continue
            for p in g:
                r=t.rowCount(); t.insertRow(r); t.setItem(r,0,self.cell(p)); t.setItem(r,1,QTableWidgetItem(f"Group {gi}")); t.setItem(r,2,QTableWidgetItem(hsize(s))); t.setItem(r,3,QTableWidgetItem(str(len(g)))); t.setItem(r,4,QTableWidgetItem(p))

    def allcheck(self,t,v):
        for r in range(t.rowCount()): t.item(r,0).setCheckState(Qt.Checked if v else Qt.Unchecked)

    def selected(self,t):
        return [t.item(r,0).data(Qt.UserRole) for r in range(t.rowCount()) if t.item(r,0).checkState()==Qt.Checked]

    def remove(self,t,permanent):
        ps=list(dict.fromkeys(self.selected(t)))
        if not ps: QMessageBox.information(self,"Nothing selected","Select files first."); return
        msg=f"Remove {len(ps):,} selected file(s)?"
        if permanent: msg+="\n\nPERMANENT deletion cannot normally be undone."
        else: msg+="\n\nThey will be sent to the Recycle Bin when possible."
        if QMessageBox.warning(self,"Confirm deletion",msg,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        ok=0; fail=[]
        for p in ps:
            if not os.path.exists(p): continue
            if permanent:
                try: os.remove(p); ok+=1
                except Exception as e: fail.append(f"{p}: {e}")
            else:
                good,why=recycle(p)
                if good: ok+=1
                else: fail.append(f"{p}: {why}")
        text=f"Removed: {ok:,}\nFailed: {len(fail):,}"
        if fail:text+="\n\n"+"\n".join(fail[:10])
        QMessageBox.warning(self,"Cleanup result",text) if fail else QMessageBox.information(self,"Cleanup complete",text)
        self.clear()

    def clear(self):
        self.large=[]; self.dups=[]; self.lt.setRowCount(0); self.dt.setRowCount(0); self.prog.setValue(0); self.summary.setText("Ready. Add a folder or drive and start a scan.")

    def open_folder(self,t):
        r=t.currentRow()
        if r<0:return
        p=t.item(r,0).data(Qt.UserRole); QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(p)))

    def export(self,t,kind):
        p,_=QFileDialog.getSaveFileName(self,"Export CSV",f"jass_{kind}_results.csv","CSV Files (*.csv)")
        if not p:return
        with open(p,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f); w.writerow([t.horizontalHeaderItem(i).text() for i in range(t.columnCount())])
            for r in range(t.rowCount()):
                w.writerow(["Selected" if t.item(r,0).checkState()==Qt.Checked else ""]+[t.item(r,c).text() for c in range(1,t.columnCount())])
        QMessageBox.information(self,"Export complete",f"Saved:\n{p}")

if __name__=="__main__":
    app=QApplication(sys.argv); app.setApplicationName(APP); w=Main(); w.show(); sys.exit(app.exec())
