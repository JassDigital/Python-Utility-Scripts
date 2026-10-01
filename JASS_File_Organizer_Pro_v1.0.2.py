import os, sys, csv, json, hashlib, shutil
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QObject, Signal, QSettings, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QProgressBar,
    QFileDialog, QMessageBox, QTabWidget, QGroupBox, QTextEdit, QDialog,
    QDialogButtonBox, QSplitter, QListWidget, QListWidgetItem, QStatusBar
)

APP = "JASS File Organizer Pro"
VERSION = "1.0"

CATEGORIES = {
    "Images": {".jpg",".jpeg",".png",".gif",".bmp",".webp",".tif",".tiff",".svg",".ico",".heic"},
    "Videos": {".mp4",".mkv",".avi",".mov",".wmv",".webm",".m4v",".mpeg",".mpg",".3gp"},
    "Audio": {".mp3",".wav",".flac",".aac",".ogg",".m4a",".wma",".opus"},
    "Documents": {".pdf",".doc",".docx",".odt",".rtf",".txt",".md",".tex"},
    "Spreadsheets": {".xls",".xlsx",".xlsm",".csv",".ods",".tsv"},
    "Presentations": {".ppt",".pptx",".pptm",".odp"},
    "Archives": {".zip",".7z",".rar",".tar",".gz",".bz2",".xz",".iso"},
    "Code": {".py",".js",".ts",".jsx",".tsx",".html",".css",".java",".c",".cpp",".h",".hpp",".rs",".go",".php",".sql",".ps1",".bat",".sh"},
    "Databases": {".db",".sqlite",".sqlite3",".mdb",".accdb"},
    "Fonts": {".ttf",".otf",".woff",".woff2"},
    "Executables": {".exe",".msi",".appx",".msix"},
    "Design": {".psd",".ai",".eps",".blend",".fig"},
    "Subtitles": {".srt",".ass",".vtt",".ssa"},
}
EXT_TO_CAT = {e:c for c, es in CATEGORIES.items() for e in es}

def size_text(n):
    n=float(n)
    for u in ("B","KB","MB","GB","TB"):
        if n < 1024 or u=="TB":
            return f"{n:.1f} {u}"
        n/=1024

def category(p):
    return EXT_TO_CAT.get(Path(p).suffix.lower(), "Other")

def hash_file(p, stop):
    h=hashlib.sha256()
    try:
        with open(p,"rb") as f:
            while True:
                if stop.is_set(): return None
                b=f.read(1024*1024)
                if not b: return h.hexdigest()
                h.update(b)
    except OSError:
        return None

class Scanner(QObject):
    progress=Signal(int,str)
    finished=Signal(object)
    failed=Signal(str)
    def __init__(self, root, recursive, hidden, excludes, large_mb, duplicates, empty, stop):
        super().__init__()
        self.root=Path(root); self.recursive=recursive; self.hidden=hidden
        self.excludes={x.strip().lower() for x in excludes if x.strip()}
        self.large=int(large_mb*1024*1024); self.duplicates=duplicates
        self.empty=empty; self.stop=stop
    def run(self):
        try:
            rows=[]; empties=[]; count=0
            iterator=self.root.rglob("*") if self.recursive else self.root.glob("*")
            for p in iterator:
                if self.stop.is_set(): return
                try:
                    if any(part.lower() in self.excludes for part in p.parts): continue
                    if not self.hidden and p.name.startswith("."): continue
                    if p.is_dir():
                        if self.empty and not any(p.iterdir()):
                            empties.append(str(p))
                        continue
                    if p.is_file():
                        st=p.stat(); count+=1
                        rows.append({
                            "path":str(p), "name":p.name, "size":st.st_size,
                            "modified":datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                            "extension":p.suffix.lower() or "[none]",
                            "category":category(p),
                            "large":st.st_size>=self.large
                        })
                        if count%100==0:
                            self.progress.emit(0,f"Scanned {count:,} files...")
                except (OSError, PermissionError): pass
            dup=[]
            if self.duplicates:
                by_size=defaultdict(list)
                for r in rows:
                    if r["size"]>0: by_size[r["size"]].append(r["path"])
                candidates=[v for v in by_size.values() if len(v)>1]
                total=sum(len(x) for x in candidates); done=0
                hashed=defaultdict(list)
                for group in candidates:
                    for p in group:
                        if self.stop.is_set(): return
                        h=hash_file(p,self.stop); done+=1
                        if h: hashed[(os.path.getsize(p),h)].append(p)
                        self.progress.emit(min(99,int(done*100/max(1,total))),f"Checking duplicates {done:,}/{total:,}")
                dup=[v for v in hashed.values() if len(v)>1]
            self.finished.emit({"rows":rows,"duplicates":dup,"empty":empties})
        except Exception as e:
            self.failed.emit(str(e))

class HelpDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent); self.setWindowTitle("About & Safety"); self.resize(680,500)
        l=QVBoxLayout(self); t=QTextEdit(); t.setReadOnly(True)
        t.setHtml(f"""
        <h2>{APP} v{VERSION}</h2>
        <p>A single-file PySide6 file management utility for Windows, hard disks and USB drives.</p>
        <h3>Safety</h3>
        <ul>
        <li>Scanning is read-only.</li>
        <li>Organizing shows a preview before changes are made.</li>
        <li>Existing destination files are never silently overwritten.</li>
        <li>Moves can be undone from the operation log while the source/destination remain available.</li>
        <li>Duplicate detection uses size followed by SHA-256 content verification.</li>
        </ul>
        <h3>Typical workflow</h3>
        <p>Select a folder → Scan → review files → choose an organization mode → Preview → Apply.</p>
        """); l.addWidget(t)
        b=QDialogButtonBox(QDialogButtonBox.Close); b.rejected.connect(self.reject); l.addWidget(b)

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP} v{VERSION}"); self.resize(1350,820)
        self.settings=QSettings("JASS","FileOrganizerPro")
        self.rows=[]; self.duplicates=[]; self.empty=[]; self.history=[]
        self.thread=None; self.worker=None; self.stop=None
        self.build_ui(); self.load_settings()

    def build_ui(self):
        self.setStyleSheet("""
        QMainWindow{background:#f4f6f9}
        QGroupBox{background:white;border:1px solid #d5dbe3;border-radius:10px;margin-top:12px;padding:12px;font-weight:600}
        QPushButton{background:white;border:1px solid #c8d0da;border-radius:7px;padding:8px 14px}
        QPushButton:hover{background:#edf3f9}
        QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox{background:white;border:1px solid #c8d0da;border-radius:6px;padding:7px}
        QTableWidget{background:white;border:1px solid #d5dbe3;gridline-color:#e6e9ee}
        QHeaderView::section{background:#e9eef4;padding:8px;border:0}
        QTabWidget::pane{background:white;border:1px solid #d5dbe3}
        """)
        central=QWidget(); self.setCentralWidget(central); root=QVBoxLayout(central)
        title=QLabel(f"📁 {APP}"); title.setFont(QFont("Segoe UI",22,QFont.Bold)); root.addWidget(title)
        sub=QLabel("Organize, inspect, find duplicates and clean your folders safely.")
        sub.setStyleSheet("color:#64748b;font-size:13px"); root.addWidget(sub)

        loc=QGroupBox("1  Choose Location"); g=QGridLayout(loc)
        self.path=QLineEdit(); self.path.setPlaceholderText("Choose a folder, hard disk or USB drive...")
        browse=QPushButton("Browse…"); browse.clicked.connect(self.browse)
        self.scan_btn=QPushButton("🔍 Scan"); self.scan_btn.clicked.connect(self.scan)
        g.addWidget(self.path,0,0,1,3); g.addWidget(browse,0,3); g.addWidget(self.scan_btn,0,4)
        self.recursive=QCheckBox("Scan subfolders"); self.recursive.setChecked(True)
        self.hidden=QCheckBox("Include hidden files")
        self.excludes=QLineEdit(); self.excludes.setPlaceholderText("Excluded folder names, comma-separated: Windows, .git, node_modules")
        g.addWidget(self.recursive,1,0); g.addWidget(self.hidden,1,1); g.addWidget(self.excludes,1,2,1,3)
        root.addWidget(loc)

        settings=QGroupBox("2  Organization Settings"); sg=QGridLayout(settings)
        self.mode=QComboBox(); self.mode.addItems(["By Category","By Extension","By Year","By Year + Category"])
        self.action=QComboBox(); self.action.addItems(["Move files","Copy files"])
        self.large=QDoubleSpinBox(); self.large.setRange(1,999999); self.large.setValue(500); self.large.setSuffix(" MB")
        self.finddup=QCheckBox("Find exact duplicates"); self.finddup.setChecked(True)
        self.findempty=QCheckBox("Find empty folders"); self.findempty.setChecked(True)
        sg.addWidget(QLabel("Organize by:"),0,0); sg.addWidget(self.mode,0,1)
        sg.addWidget(QLabel("Operation:"),0,2); sg.addWidget(self.action,0,3)
        sg.addWidget(QLabel("Large-file threshold:"),0,4); sg.addWidget(self.large,0,5)
        sg.addWidget(self.finddup,1,0,1,2); sg.addWidget(self.findempty,1,2,1,2)
        root.addWidget(settings)

        self.progress=QProgressBar(); self.progress.setValue(0); root.addWidget(self.progress)
        self.status=QLabel("Ready."); root.addWidget(self.status)

        self.tabs=QTabWidget(); root.addWidget(self.tabs,1)
        self.filetab=self.make_file_tab(); self.duptab=self.make_dup_tab(); self.statustab=self.make_status_tab()
        self.tabs.addTab(self.filetab,"📄 Files")
        self.tabs.addTab(self.duptab,"♻ Duplicates")
        self.tabs.addTab(self.statustab,"📊 Statistics")

        bar=self.addToolBar("Tools")
        for text,fn in [("Preview Organization",self.preview),("Apply Selected",self.apply_selected),
                        ("Undo Last Operation",self.undo_last),("Export CSV",self.export_csv),
                        ("Open Folder",self.open_folder),("Clear",self.clear)]:
            a=QAction(text,self); a.triggered.connect(fn); bar.addAction(a)
        helpa=QAction("About / Safety",self); helpa.triggered.connect(lambda:HelpDialog(self).exec()); bar.addAction(helpa)
        self.setStatusBar(QStatusBar())

    def make_table(self,headers):
        t=QTableWidget(0,len(headers)); t.setHorizontalHeaderLabels(headers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows); t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers); t.setSortingEnabled(True)
        t.horizontalHeader().setStretchLastSection(True)
        for i in range(len(headers)-1): t.horizontalHeader().setSectionResizeMode(i,QHeaderView.ResizeToContents)
        return t

    def make_file_tab(self):
        w=QWidget(); l=QVBoxLayout(w); b=QHBoxLayout()
        self.filter=QLineEdit(); self.filter.setPlaceholderText("Filter by name, path, extension or category…"); self.filter.textChanged.connect(self.filter_files)
        b.addWidget(self.filter); b.addWidget(QPushButton("Select All",clicked=lambda:self.select_visible(True))); b.addWidget(QPushButton("None",clicked=lambda:self.select_visible(False)))
        l.addLayout(b)
        self.table=self.make_table(["Select","Name","Size","Category","Extension","Modified","Path"])
        self.table.itemClicked.connect(self.toggle_row_checkbox)
        l.addWidget(self.table); return w

    def make_dup_tab(self):
        w=QWidget(); l=QVBoxLayout(w)
        self.duptable=self.make_table(["Select","Group","Size","Path"])
        self.duptable.itemClicked.connect(self.toggle_dup_row_checkbox)
        l.addWidget(self.duptable)
        note=QLabel("For each duplicate group, normally keep one copy and select the other copies for removal/moving.")
        note.setStyleSheet("color:#64748b;padding:6px"); l.addWidget(note); return w

    def make_status_tab(self):
        w=QWidget(); l=QVBoxLayout(w); self.stats=QTextEdit(); self.stats.setReadOnly(True); l.addWidget(self.stats); return w

    def load_settings(self):
        self.path.setText(self.settings.value("last_path",""))

    def closeEvent(self,e):
        self.settings.setValue("last_path",self.path.text()); e.accept()

    def browse(self):
        p=QFileDialog.getExistingDirectory(self,"Choose folder or drive",self.path.text() or os.path.expanduser("~"))
        if p:self.path.setText(p)

    def scan(self):
        p=Path(self.path.text().strip())
        if not p.is_dir(): QMessageBox.warning(self,"Invalid location","Choose an existing folder or drive."); return
        self.clear(False); self.stop=__import__("threading").Event()
        self.thread=QThread(); self.worker=Scanner(p,self.recursive.isChecked(),self.hidden.isChecked(),self.excludes.text().split(","),self.large.value(),self.finddup.isChecked(),self.findempty.isChecked(),self.stop)
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.scan_progress); self.worker.finished.connect(self.scan_finished); self.worker.failed.connect(self.scan_failed)
        self.worker.finished.connect(self.thread.quit); self.worker.failed.connect(self.thread.quit); self.thread.finished.connect(self.scan_thread_done)
        self.scan_btn.setEnabled(False); self.thread.start()

    def scan_progress(self,n,msg): self.progress.setValue(n); self.status.setText(msg)

    def scan_finished(self,data):
        self.rows=data["rows"]; self.duplicates=data["duplicates"]; self.empty=data["empty"]
        self.populate_files(); self.populate_dups(); self.statistics()
        self.progress.setValue(100); self.status.setText(f"Scan complete: {len(self.rows):,} files • {len(self.duplicates):,} duplicate groups • {len(self.empty):,} empty folders")

    def scan_failed(self,e): QMessageBox.critical(self,"Scan error",e); self.status.setText("Scan failed.")

    def scan_thread_done(self):
        self.scan_btn.setEnabled(True); self.thread=None; self.worker=None

    def checkitem(self,path,checked=False):
        x=QTableWidgetItem()
        x.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        x.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        x.setData(Qt.UserRole, path)
        return x

    def toggle_row_checkbox(self, item):
        """Clicking anywhere on a file row toggles its checkbox."""
        if item is None:
            return
        row = item.row()
        cb = self.table.item(row, 0)
        if cb is None:
            return
        # Clicking the checkbox itself is already handled by Qt.
        # For clicks in other columns, toggle the row's checkbox.
        if item.column() != 0:
            cb.setCheckState(Qt.Unchecked if cb.checkState() == Qt.Checked else Qt.Checked)

    def sync_selected_rows(self):
        """Turn normal table row selection into checked files."""
        for idx in self.table.selectionModel().selectedRows():
            self.table.item(idx.row(), 0).setCheckState(Qt.Checked)

    def populate_files(self):
        self.table.setSortingEnabled(False); self.table.setRowCount(0)
        for r in self.rows:
            i=self.table.rowCount(); self.table.insertRow(i)
            self.table.setItem(i,0,self.checkitem(r["path"]))
            self.table.setItem(i,1,QTableWidgetItem(r["name"])); self.table.setItem(i,2,QTableWidgetItem(size_text(r["size"])))
            self.table.setItem(i,3,QTableWidgetItem(r["category"])); self.table.setItem(i,4,QTableWidgetItem(r["extension"]))
            self.table.setItem(i,5,QTableWidgetItem(r["modified"])); self.table.setItem(i,6,QTableWidgetItem(r["path"]))
            if r["large"]:
                for c in range(1,7): self.table.item(i,c).setBackground(QColor("#fff3cd"))
        self.table.setSortingEnabled(True); self.filter_files(self.filter.text())

    def populate_dups(self):
        self.duptable.setSortingEnabled(False); self.duptable.setRowCount(0)
        for gi,g in enumerate(self.duplicates,1):
            try:s=os.path.getsize(g[0])
            except:continue
            for p in g:
                i=self.duptable.rowCount(); self.duptable.insertRow(i)
                self.duptable.setItem(i,0,self.checkitem(p)); self.duptable.setItem(i,1,QTableWidgetItem(f"Group {gi}"))
                self.duptable.setItem(i,2,QTableWidgetItem(size_text(s))); self.duptable.setItem(i,3,QTableWidgetItem(p))
        self.duptable.setSortingEnabled(True)

    def filter_files(self,text):
        q=text.lower().strip()
        for r in range(self.table.rowCount()):
            blob=" ".join(self.table.item(r,c).text().lower() for c in range(1,7))
            self.table.setRowHidden(r,bool(q and q not in blob))

    def select_visible(self,v):
        state = Qt.Checked if v else Qt.Unchecked
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                cb = self.table.item(r,0)
                if cb is not None:
                    cb.setCheckState(state)

    def selected_files(self):
        return [self.table.item(r,0).data(Qt.UserRole) for r in range(self.table.rowCount()) if self.table.item(r,0).checkState()==Qt.Checked]

    def toggle_dup_row_checkbox(self, item):
        if item is None:
            return
        row = item.row()
        cb = self.duptable.item(row, 0)
        if cb is not None and item.column() != 0:
            cb.setCheckState(Qt.Unchecked if cb.checkState() == Qt.Checked else Qt.Checked)

    def selected_dups(self):
        return [self.duptable.item(r,0).data(Qt.UserRole) for r in range(self.duptable.rowCount()) if self.duptable.item(r,0).checkState()==Qt.Checked]

    def destination_for(self,p):
        root=Path(self.path.text()); src=Path(p); mode=self.mode.currentText()
        if mode=="By Category": rel=category(src)
        elif mode=="By Extension": rel=(src.suffix.lower().lstrip(".") or "No Extension").upper()
        elif mode=="By Year": rel=datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y")
        else: rel=Path(datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y"))/category(src)
        dest=root/"Organized"/rel
        return dest

    def unique_dest(self,d,p):
        d=Path(d); p=Path(p); d.mkdir(parents=True,exist_ok=True); q=d/p.name
        if not q.exists(): return q
        for i in range(1,100000):
            q=d/f"{p.stem} ({i}){p.suffix}"
            if not q.exists(): return q
        raise RuntimeError("Unable to create unique destination.")

    def preview(self):
        ps=self.selected_files()
        if not ps: QMessageBox.information(self,"Nothing selected","Select files in the Files tab first."); return
        dlg=QDialog(self); dlg.setWindowTitle("Organization Preview"); dlg.resize(900,600); l=QVBoxLayout(dlg)
        t=self.make_table(["Source","Destination","Operation"]); t.setRowCount(0)
        for p in ps:
            d=self.unique_dest(self.destination_for(p),p); i=t.rowCount(); t.insertRow(i)
            t.setItem(i,0,QTableWidgetItem(p)); t.setItem(i,1,QTableWidgetItem(str(d))); t.setItem(i,2,QTableWidgetItem(self.action.currentText()))
        l.addWidget(t); l.addWidget(QLabel(f"{len(ps):,} file(s) selected. No changes have been made."))
        b=QDialogButtonBox(QDialogButtonBox.Close); b.rejected.connect(dlg.reject); l.addWidget(b); dlg.exec()

    def apply_selected(self):
        ps=self.selected_files()
        if not ps: QMessageBox.information(self,"Nothing selected","Select files first."); return
        if QMessageBox.question(self,"Confirm operation",f"{self.action.currentText()} {len(ps):,} selected files into Organized folders?\n\nA preview is recommended before applying.",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        log=[]
        for p in ps:
            try:
                d=self.unique_dest(self.destination_for(p),p)
                if self.action.currentText()=="Move files": shutil.move(p,d)
                else: shutil.copy2(p,d)
                log.append((str(p),str(d),self.action.currentText()))
            except Exception as e:
                self.statusBar().showMessage(f"Failed: {p} — {e}",10000)
        self.history.append(log); self.write_log(log); self.scan()
        QMessageBox.information(self,"Operation complete",f"Successfully processed {len(log):,} file(s).")

    def undo_last(self):
        if not self.history: QMessageBox.information(self,"Undo","There is no operation to undo in this session."); return
        log=self.history.pop(); ok=0
        for src,dst,op in reversed(log):
            try:
                if op=="Move files" and Path(dst).exists() and not Path(src).exists():
                    Path(src).parent.mkdir(parents=True,exist_ok=True); shutil.move(dst,src); ok+=1
            except: pass
        self.scan(); QMessageBox.information(self,"Undo",f"Restored {ok:,} moved file(s). Copied files are not removed by Undo.")

    def write_log(self,log):
        try:
            p=Path(self.path.text())/"JASS_File_Organizer_Operations.log"
            with open(p,"a",encoding="utf-8") as f:
                for a,b,c in log:f.write(f"{datetime.now().isoformat()}\t{c}\t{a}\t{b}\n")
        except: pass

    def open_folder(self):
        rows=self.table.selectionModel().selectedRows()
        if not rows:return
        p=self.table.item(rows[0].row(),0).data(Qt.UserRole)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))

    def export_csv(self):
        if not self.rows:return
        p,_=QFileDialog.getSaveFileName(self,"Export scan CSV","JASS_File_Organizer_Report.csv","CSV (*.csv)")
        if not p:return
        with open(p,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f); w.writerow(["Name","Size","Category","Extension","Modified","Path","Large"])
            for r in self.rows:w.writerow([r["name"],r["size"],r["category"],r["extension"],r["modified"],r["path"],r["large"]])
        QMessageBox.information(self,"Export complete",f"Saved:\n{p}")

    def statistics(self):
        total=sum(r["size"] for r in self.rows); cats=Counter(r["category"] for r in self.rows); exts=Counter(r["extension"] for r in self.rows)
        large=[r for r in self.rows if r["large"]]
        dupbytes=sum((len(g)-1)*os.path.getsize(g[0]) for g in self.duplicates if g and Path(g[0]).exists())
        lines=[f"<h2>Scan Statistics</h2><b>Files:</b> {len(self.rows):,}<br><b>Total size:</b> {size_text(total)}",
               f"<br><b>Large files:</b> {len(large):,}<br><b>Duplicate groups:</b> {len(self.duplicates):,}",
               f"<br><b>Potential duplicate space:</b> {size_text(dupbytes)}<br><b>Empty folders:</b> {len(self.empty):,}<h3>Categories</h3>"]
        lines += [f"{k}: {v:,} files" for k,v in cats.most_common()]
        lines += ["<h3>Extensions</h3>"]+[f"{k}: {v:,}" for k,v in exts.most_common(25)]
        self.stats.setHtml("<br>".join(lines))

    def clear(self,all_data=True):
        if all_data:self.rows=[]; self.duplicates=[]; self.empty=[]
        self.table.setRowCount(0); self.duptable.setRowCount(0); self.stats.clear(); self.progress.setValue(0); self.status.setText("Ready.")

if __name__=="__main__":
    app=QApplication(sys.argv); app.setApplicationName(APP)
    w=Main(); w.show(); sys.exit(app.exec())
