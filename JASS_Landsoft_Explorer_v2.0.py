import os
import sys
import shutil
import subprocess
import json
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QDir, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QAction, QFont, QPixmap, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeView, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QPushButton, QLabel, QFrame, QMessageBox, QInputDialog, QPlainTextEdit,
    QStackedWidget, QComboBox, QMenu, QToolButton, QProgressBar,
    QAbstractItemView, QFileSystemModel, QDialog, QDialogButtonBox, QCheckBox,
    QFormLayout, QSpinBox
)

ROOT = Path(r"E:\Landsoft")
APP_DIR = Path.home() / ".jass_landsoft_explorer"
FAV_FILE = APP_DIR / "favorites.json"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".ico"}
PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt", ".log", ".md", ".ini", ".rtf", ".xml", ".json", ".csv"}
EDITABLE_TEXT = TEXT_EXTS | {".py", ".yaml", ".yml", ".css", ".js", ".html", ".sql"}
OFFICE_EXTS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".doc", ".docx", ".odt", ".ppt", ".pptx"}

try:
    import fitz
except Exception:
    fitz = None

try:
    from send2trash import send2trash
except Exception:
    send2trash = None


def human_size(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}"
        n /= 1024


def category(ext):
    ext = ext.lower()
    if ext in IMAGE_EXTS: return "Images"
    if ext in PDF_EXTS: return "PDF"
    if ext in {".xlsx", ".xls", ".xlsm", ".xlsb", ".csv"}: return "Excel / Data"
    if ext in {".doc", ".docx", ".odt", ".rtf"}: return "Documents"
    if ext in EDITABLE_TEXT: return "Text"
    if ext in {".db", ".byte[]", ".opf", ".ttf"}: return "Other"
    return "Other"


def icon_for(name, is_dir=False):
    if is_dir: return "▣"
    return {".pdf":"▤", ".jpg":"▧", ".jpeg":"▧", ".png":"▧", ".xlsx":"▥", ".xls":"▥",
            ".doc":"▥", ".docx":"▥", ".txt":"≡", ".csv":"≡", ".db":"◈"}.get(Path(name).suffix.lower(), "◇")


def open_path(path):
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class ScanWorker(QThread):
    done = Signal(object, object)
    progress = Signal(int)
    def __init__(self, root, query="", max_depth=99):
        super().__init__(); self.root=Path(root); self.query=query.lower(); self.max_depth=max_depth
    def run(self):
        results=[]; total=0
        try:
            for current, dirs, files in os.walk(self.root, followlinks=False):
                cur=Path(current)
                try: depth=len(cur.relative_to(self.root).parts)
                except ValueError: depth=0
                if depth >= self.max_depth: dirs[:] = []
                names=dirs+files
                for name in names:
                    if self.query and self.query not in name.lower(): continue
                    results.append(cur/name)
                    total += 1
                    if total % 100 == 0: self.progress.emit(min(99, total % 1000 // 10))
            self.progress.emit(100); self.done.emit(results, None)
        except Exception as e:
            self.done.emit(results, str(e))


class StatsWorker(QThread):
    done=Signal(int,int,int,object)
    def __init__(self, root): super().__init__(); self.root=Path(root)
    def run(self):
        files=folders=total=0; cats={}
        try:
            for cur,dirs,names in os.walk(self.root, followlinks=False):
                folders += len(dirs)
                for name in names:
                    try: size=(Path(cur)/name).stat().st_size
                    except OSError: continue
                    files+=1; total+=size; c=category(Path(name).suffix); cats[c]=cats.get(c,0)+1
        except Exception: pass
        self.done.emit(files,folders,total,cats)


class TextEditorDialog(QDialog):
    def __init__(self,path,parent=None):
        super().__init__(parent); self.path=Path(path); self.setWindowTitle(f"Edit • {self.path.name}"); self.resize(950,700)
        lay=QVBoxLayout(self); top=QHBoxLayout(); top.addWidget(QLabel(f"<b>{self.path.name}</b>")); top.addStretch(); top.addWidget(QLabel("UTF-8")); lay.addLayout(top)
        self.editor=QPlainTextEdit(); self.editor.setFont(QFont("Cascadia Mono",11)); lay.addWidget(self.editor,1)
        try: self.editor.setPlainText(self.path.read_text(encoding="utf-8-sig",errors="replace"))
        except Exception as e: self.editor.setPlainText(f"Unable to read file:\n{e}")
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); lay.addWidget(buttons)
    def save(self):
        try: self.path.write_text(self.editor.toPlainText(),encoding="utf-8"); self.accept()
        except Exception as e: QMessageBox.critical(self,"Save failed",str(e))


class PropertiesDialog(QDialog):
    def __init__(self,path,parent=None):
        super().__init__(parent); self.path=Path(path); self.setWindowTitle("Properties • "+self.path.name); self.resize(600,420)
        lay=QVBoxLayout(self); form=QFormLayout()
        try: st=self.path.stat()
        except OSError: st=None
        fields=[("Name",self.path.name),("Type","Folder" if self.path.is_dir() else category(self.path.suffix)),
                ("Location",str(self.path.parent)),("Size","—" if self.path.is_dir() or not st else human_size(st.st_size)),
                ("Modified","—" if not st else datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")),
                ("Created","—" if not st else datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S"))]
        for k,v in fields: form.addRow(k,QLabel(v))
        lay.addLayout(form); lay.addStretch(); b=QDialogButtonBox(QDialogButtonBox.Close); b.rejected.connect(self.reject); b.accepted.connect(self.accept); lay.addWidget(b)


class Preview(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent); lay=QVBoxLayout(self); lay.setContentsMargins(18,18,18,18)
        self.title=QLabel("SELECT AN ITEM"); self.title.setObjectName("previewTitle"); lay.addWidget(self.title)
        self.meta=QLabel("Select an item to inspect it."); self.meta.setWordWrap(True); self.meta.setObjectName("muted"); lay.addWidget(self.meta)
        self.stack=QStackedWidget(); self.placeholder=QLabel("◈\n\nPREVIEW\n\nSelect an image, PDF or text file."); self.placeholder.setAlignment(Qt.AlignCenter); self.placeholder.setObjectName("previewPlaceholder"); self.stack.addWidget(self.placeholder)
        self.image=QLabel(); self.image.setAlignment(Qt.AlignCenter); self.stack.addWidget(self.image)
        self.pdf=QLabel(); self.pdf.setAlignment(Qt.AlignCenter); self.stack.addWidget(self.pdf)
        self.text=QPlainTextEdit(); self.text.setReadOnly(True); self.text.setFont(QFont("Cascadia Mono",10)); self.stack.addWidget(self.text)
        self.info=QLabel(); self.info.setAlignment(Qt.AlignTop|Qt.AlignLeft); self.info.setWordWrap(True); self.stack.addWidget(self.info); lay.addWidget(self.stack,1)
    def show_item(self,path):
        p=Path(path); self.title.setText(p.name.upper() if p.name else str(p))
        try:
            st=p.stat()
            if p.is_dir():
                try: count=sum(1 for _ in p.iterdir())
                except OSError: count=0
                self.meta.setText(f"FOLDER • {count:,} direct items\n{p}\n\nModified: {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}")
                self.info.setText("Folder selected.\n\nDouble-click to open.\nUse Properties for details and the toolbar for file operations."); self.stack.setCurrentWidget(self.info); return
            self.meta.setText(f"{category(p.suffix)} • {human_size(st.st_size)}\n{p}\n\nModified: {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}")
            ext=p.suffix.lower()
            if ext in IMAGE_EXTS:
                pix=QPixmap(str(p)); self.image.setPixmap(pix.scaled(850,650,Qt.KeepAspectRatio,Qt.SmoothTransformation) if not pix.isNull() else QPixmap()); self.stack.setCurrentWidget(self.image if not pix.isNull() else self.placeholder)
            elif ext in PDF_EXTS and fitz:
                try:
                    doc=fitz.open(str(p)); page=doc.load_page(0); pix=page.get_pixmap(matrix=fitz.Matrix(1.25,1.25),alpha=False); q=QPixmap(); q.loadFromData(pix.tobytes("png")); doc.close(); self.pdf.setPixmap(q.scaled(850,650,Qt.KeepAspectRatio,Qt.SmoothTransformation)); self.stack.setCurrentWidget(self.pdf)
                except Exception: self.pdf.setText("PDF preview unavailable.\nUse Open to view it."); self.stack.setCurrentWidget(self.pdf)
            elif ext in EDITABLE_TEXT:
                self.text.setPlainText(p.read_text(encoding="utf-8-sig",errors="replace")[:250000]); self.stack.setCurrentWidget(self.text)
            else: self.stack.setCurrentWidget(self.placeholder)
        except Exception as e: self.meta.setText(str(e)); self.stack.setCurrentWidget(self.placeholder)


class LandsoftExplorer(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("JASS Landsoft Explorer • v2.0"); self.resize(1600,950); self.setMinimumSize(1150,720)
        self.current_dir=ROOT; self.history=[ROOT]; self.history_index=0; self.search_results=[]; self.favorites=[]; self.scan_worker=None; self.stats_worker=None
        self.load_favorites(); self.build_ui(); self.apply_style(); self.populate_root(); self.refresh_stats()
    def build_ui(self):
        central=QWidget(); self.setCentralWidget(central); main=QVBoxLayout(central); main.setContentsMargins(16,14,16,12); main.setSpacing(9)
        header=QHBoxLayout(); brand=QLabel("JASS <span>LANDSOFT</span>"); brand.setObjectName("brand"); header.addWidget(brand); x=QLabel("EXPLORER 2.0"); x.setObjectName("eyebrow"); header.addWidget(x); header.addStretch()
        self.search=QLineEdit(); self.search.setPlaceholderText("⌕  Search all Landsoft files and folders…"); self.search.setClearButtonEnabled(True); self.search.setMinimumWidth(430); self.search.returnPressed.connect(self.search_now); header.addWidget(self.search)
        b=QPushButton("SEARCH"); b.clicked.connect(self.search_now); header.addWidget(b); main.addLayout(header)
        cards=QHBoxLayout(); self.cards={}
        for key,label in [("files","FILES"),("folders","FOLDERS"),("size","TOTAL SIZE"),("pdf","PDF"),("images","IMAGES"),("excel","EXCEL / DATA")]:
            f=QFrame(); f.setObjectName("card"); l=QVBoxLayout(f); v=QLabel("—"); v.setObjectName("cardValue"); l.addWidget(v); l.addWidget(QLabel(label)); cards.addWidget(f); self.cards[key]=v
        main.addLayout(cards)
        toolbar=QHBoxLayout()
        buttons=[("←",self.go_back,"Alt+Left"),("→",self.go_forward,"Alt+Right"),("↑ UP",self.go_up,"Alt+Up"),("↻ REFRESH",self.refresh_all,"F5"),("＋ NEW FOLDER",self.new_folder,None),("☆ FAVORITE",self.toggle_favorite,None),("✎ RENAME",self.rename_item,"F2"),("DELETE",self.delete_items,"Delete"),("COPY",self.copy_items,"Ctrl+C"),("MOVE",self.move_items,"Ctrl+M"),("OPEN",self.open_item,"Return"),("EDIT",self.edit_item,"Ctrl+E"),("PROPERTIES",self.properties,"Alt+Enter")]
        for text,slot,shortcut in buttons:
            q=QPushButton(text); q.clicked.connect(slot); toolbar.addWidget(q)
            if shortcut: q.setShortcut(QKeySequence(shortcut))
        toolbar.addStretch(); self.filter=QComboBox(); self.filter.addItems(["All types","Images","PDF","Excel / Data","Documents","Text","Other"]); self.filter.currentTextChanged.connect(self.populate_files); toolbar.addWidget(self.filter); main.addLayout(toolbar)
        self.breadcrumb=QLabel(); self.breadcrumb.setObjectName("breadcrumb"); main.addWidget(self.breadcrumb)
        split=QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False)
        left=QFrame(); ll=QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.addWidget(QLabel("FOLDERS"),0)
        self.model=QFileSystemModel(); self.model.setFilter(QDir.AllDirs|QDir.NoDotAndDotDot); self.model.setRootPath(str(ROOT)); self.tree=QTreeView(); self.tree.setModel(self.model); self.tree.setRootIndex(self.model.index(str(ROOT))); self.tree.setHeaderHidden(True)
        for c in range(1,4): self.tree.hideColumn(c)
        self.tree.clicked.connect(self.folder_clicked); self.tree.doubleClicked.connect(self.folder_double_clicked); self.tree.setContextMenuPolicy(Qt.CustomContextMenu); self.tree.customContextMenuRequested.connect(self.tree_menu); ll.addWidget(self.tree); split.addWidget(left)
        middle=QFrame(); ml=QVBoxLayout(middle); ml.setContentsMargins(0,0,0,0); self.file_title=QLabel("FILES"); self.file_title.setObjectName("sectionTitle"); ml.addWidget(self.file_title)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["TYPE","NAME","SIZE","MODIFIED","LOCATION","STATUS"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.verticalHeader().setVisible(False); self.table.setSortingEnabled(True)
        h=self.table.horizontalHeader(); h.setSectionResizeMode(0,QHeaderView.ResizeToContents); h.setSectionResizeMode(1,QHeaderView.Stretch); h.setSectionResizeMode(2,QHeaderView.ResizeToContents); h.setSectionResizeMode(3,QHeaderView.ResizeToContents); h.setSectionResizeMode(4,QHeaderView.Stretch); h.setSectionResizeMode(5,QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.selection_changed); self.table.doubleClicked.connect(lambda _: self.open_item()); self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.customContextMenuRequested.connect(self.file_menu); ml.addWidget(self.table); split.addWidget(middle)
        self.preview=Preview(); split.addWidget(self.preview); split.setSizes([270,800,450]); main.addWidget(split,1)
        bottom=QHBoxLayout(); self.progress=QProgressBar(); self.progress.setVisible(False); self.progress.setMaximumWidth(220); bottom.addWidget(self.progress); self.status=QLabel("Ready"); self.status.setObjectName("muted"); bottom.addWidget(self.status); bottom.addStretch(); self.location=QLabel(str(ROOT)); self.location.setObjectName("muted"); bottom.addWidget(self.location); main.addLayout(bottom)
    def apply_style(self):
        self.setStyleSheet('''*{font-family:"Segoe UI",Arial;} QMainWindow,QWidget{background:#0b1018;color:#e7eef8;} QFrame#card,QFrame{border:1px solid #1e2b3b;border-radius:12px;} QFrame#card{background:#101925;} QLabel#brand{font-size:26px;font-weight:800;letter-spacing:2px;color:#f2f7ff;} QLabel#brand span{color:#45d9ff;} QLabel#eyebrow,QLabel#sectionTitle{color:#6d7f95;font-size:11px;font-weight:700;letter-spacing:2px;} QLabel#cardValue{font-size:24px;font-weight:800;color:#56ddff;} QLabel#breadcrumb{background:#0e1722;border:1px solid #1e2b3b;border-radius:8px;padding:8px 12px;color:#86a0ba;} QLabel#muted{color:#718399;} QLabel#previewTitle{color:#eaf4ff;font-size:18px;font-weight:700;} QLabel#previewPlaceholder{color:#53657b;font-size:15px;border:1px dashed #26384c;border-radius:12px;} QLineEdit,QComboBox,QPlainTextEdit{background:#0e1722;border:1px solid #25364a;border-radius:8px;padding:8px;color:#e8f2ff;selection-background-color:#155f82;} QLineEdit:focus,QComboBox:focus,QPlainTextEdit:focus{border:1px solid #35cfff;} QPushButton{background:#111d2b;border:1px solid #26394f;border-radius:8px;padding:8px 11px;color:#c9d8e8;font-weight:600;} QPushButton:hover{background:#17283a;border-color:#36cfff;color:white;} QPushButton:pressed{background:#0c526c;} QTreeView,QTableWidget{background:#0d151f;alternate-background-color:#101b28;border:1px solid #1e2b3b;border-radius:10px;gridline-color:#172433;outline:none;} QTreeView::item,QTableWidget::item{padding:7px;border:none;} QTreeView::item:hover,QTableWidget::item:hover{background:#142538;} QTreeView::item:selected,QTableWidget::item:selected{background:#123e55;color:#fff;} QHeaderView::section{background:#111d2b;color:#6f849b;border:none;border-bottom:1px solid #26384b;padding:8px;font-size:10px;font-weight:700;} QProgressBar{border:1px solid #26394f;border-radius:6px;background:#0e1722;text-align:center;color:#8ea5ba;} QProgressBar::chunk{background:#20bde8;border-radius:5px;} QMenu{background:#111c29;border:1px solid #294057;padding:5px;} QMenu::item{padding:8px 22px;} QMenu::item:selected{background:#123e55;} QDialog{background:#0d151f;}''')
    def load_favorites(self):
        try: self.favorites=json.loads(FAV_FILE.read_text(encoding="utf-8"))
        except Exception: self.favorites=[]
    def save_favorites(self):
        APP_DIR.mkdir(parents=True,exist_ok=True); FAV_FILE.write_text(json.dumps(self.favorites,indent=2),encoding="utf-8")
    def populate_root(self): self.current_dir=ROOT; self.populate_files(); self.update_breadcrumb()
    def update_breadcrumb(self):
        try: rel=self.current_dir.relative_to(ROOT); text="LANDSOFT / "+(" / ".join(rel.parts) if rel.parts else "ROOT")
        except ValueError: text=str(self.current_dir)
        self.breadcrumb.setText(text); self.location.setText(str(self.current_dir)); self.file_title.setText(f"FILES • {self.current_dir.name.upper()}"); self.tree.setCurrentIndex(self.model.index(str(self.current_dir)))
        self.status.setText(f"{self.table.rowCount():,} items")
    def navigate(self,p,record=True):
        p=Path(p)
        if not p.is_dir() or not str(p).lower().startswith(str(ROOT).lower()): return
        if record:
            self.history=self.history[:self.history_index+1]; self.history.append(p); self.history_index+=1
        self.current_dir=p; self.populate_files(); self.update_breadcrumb()
    def populate_files(self):
        self.table.setSortingEnabled(False); self.table.setRowCount(0); self.search_results=[]
        if not self.current_dir.exists(): return
        sf=self.filter.currentText()
        try: entries=sorted(self.current_dir.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))
        except OSError as e: self.status.setText(f"Cannot read folder: {e}"); return
        for p in entries:
            if p.is_dir() or sf=="All types" or category(p.suffix)==sf: self.add_row(p)
        self.table.setSortingEnabled(True); self.update_breadcrumb()
    def add_row(self,p,status=""):
        r=self.table.rowCount(); self.table.insertRow(r); d=p.is_dir()
        try: st=p.stat(); size="—" if d else human_size(st.st_size); mod=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError: size=mod="?"
        vals=[icon_for(p.name,d),p.name,size,mod,"LANDSOFT" if p.parent==ROOT else str(p.parent.relative_to(ROOT)),status]
        for c,v in enumerate(vals):
            it=QTableWidgetItem(v); it.setData(Qt.UserRole,str(p)); self.table.setItem(r,c,it)
            if c==0: it.setTextAlignment(Qt.AlignCenter)
    def selected_paths(self):
        paths=[]
        for idx in self.table.selectionModel().selectedRows():
            it=self.table.item(idx.row(),1)
            if it: paths.append(Path(it.data(Qt.UserRole)))
        return paths
    def selected_path(self):
        ps=self.selected_paths(); return ps[0] if ps else None
    def selection_changed(self):
        ps=self.selected_paths()
        if len(ps)==1: self.preview.show_item(ps[0]); self.status.setText(str(ps[0]))
        elif ps: self.status.setText(f"{len(ps):,} items selected")
    def folder_clicked(self,index): self.navigate(Path(self.model.filePath(index)))
    def folder_double_clicked(self,index): self.navigate(Path(self.model.filePath(index)))
    def go_up(self):
        if self.current_dir!=ROOT: self.navigate(self.current_dir.parent)
    def go_back(self):
        if self.history_index>0:
            self.history_index-=1; self.current_dir=self.history[self.history_index]; self.populate_files(); self.update_breadcrumb()
    def go_forward(self):
        if self.history_index+1<len(self.history):
            self.history_index+=1; self.current_dir=self.history[self.history_index]; self.populate_files(); self.update_breadcrumb()
    def refresh_all(self): self.populate_files(); self.refresh_stats(); self.status.setText("Refreshed")
    def refresh_stats(self):
        if self.stats_worker and self.stats_worker.isRunning(): return
        self.stats_worker=StatsWorker(ROOT); self.stats_worker.done.connect(self.stats_done); self.stats_worker.start()
    def stats_done(self,files,folders,total,cats):
        self.cards["files"].setText(f"{files:,}"); self.cards["folders"].setText(f"{folders:,}"); self.cards["size"].setText(human_size(total)); self.cards["pdf"].setText(f"{cats.get('PDF',0):,}"); self.cards["images"].setText(f"{cats.get('Images',0):,}"); self.cards["excel"].setText(f"{cats.get('Excel / Data',0):,}")
    def new_folder(self):
        name,ok=QInputDialog.getText(self,"New Folder","Folder name:");
        if not ok or not name.strip(): return
        try: (self.current_dir/name.strip()).mkdir(); self.refresh_all()
        except Exception as e: QMessageBox.critical(self,"Cannot create folder",str(e))
    def rename_item(self):
        ps=self.selected_paths()
        if len(ps)!=1: QMessageBox.information(self,"Rename","Select exactly one file or folder."); return
        p=ps[0]; name,ok=QInputDialog.getText(self,"Rename","New name:",text=p.name)
        if ok and name.strip() and name.strip()!=p.name:
            try: p.rename(p.with_name(name.strip())); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"Rename failed",str(e))
    def delete_items(self):
        ps=self.selected_paths()
        if not ps: return
        target="Move" if send2trash else "Delete"
        msg=f"{target} {len(ps)} selected item(s) to the Recycle Bin?" if send2trash else f"Permanently delete {len(ps)} selected item(s)?"
        if QMessageBox.question(self,"Confirm",msg+"\n\n"+"\n".join(str(p) for p in ps[:8]),QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes: return
        try:
            for p in ps:
                if send2trash: send2trash(str(p))
                elif p.is_dir(): shutil.rmtree(p)
                else: p.unlink()
            self.refresh_all()
        except Exception as e: QMessageBox.critical(self,"Delete failed",str(e))
    def copy_items(self):
        ps=self.selected_paths()
        if not ps: return
        dest=QFileDialog.getExistingDirectory(self,"Copy selected items to",str(self.current_dir))
        if not dest: return
        try:
            for p in ps:
                target=Path(dest)/p.name
                if p.is_dir(): shutil.copytree(p,target,dirs_exist_ok=True)
                else: shutil.copy2(p,target)
            self.refresh_all(); QMessageBox.information(self,"Copy complete",f"Copied {len(ps)} item(s).")
        except Exception as e: QMessageBox.critical(self,"Copy failed",str(e))
    def move_items(self):
        ps=self.selected_paths()
        if not ps: return
        dest=QFileDialog.getExistingDirectory(self,"Move selected items to",str(self.current_dir))
        if not dest: return
        try:
            for p in ps: shutil.move(str(p),str(Path(dest)/p.name))
            self.refresh_all(); QMessageBox.information(self,"Move complete",f"Moved {len(ps)} item(s).")
        except Exception as e: QMessageBox.critical(self,"Move failed",str(e))
    def open_item(self):
        p=self.selected_path()
        if not p: return
        if p.is_dir(): self.navigate(p); return
        try: open_path(p)
        except Exception as e: QMessageBox.critical(self,"Open failed",str(e))
    def edit_item(self):
        p=self.selected_path()
        if not p or p.is_dir(): return
        if p.suffix.lower() in EDITABLE_TEXT:
            if TextEditorDialog(p,self).exec(): self.refresh_all()
        else: self.open_item()
    def properties(self):
        p=self.selected_path()
        if p: PropertiesDialog(p,self).exec()
    def toggle_favorite(self):
        p=self.current_dir
        s=str(p)
        if s in self.favorites: self.favorites.remove(s); self.status.setText("Removed from favorites")
        else: self.favorites.append(s); self.status.setText("Added to favorites")
        self.save_favorites()
    def search_now(self):
        q=self.search.text().strip()
        if not q: self.populate_files(); return
        if self.scan_worker and self.scan_worker.isRunning(): return
        self.table.setRowCount(0); self.file_title.setText("SEARCHING…"); self.breadcrumb.setText(f"SEARCH / {q}"); self.progress.setVisible(True); self.progress.setValue(0); self.status.setText("Searching Landsoft…")
        self.scan_worker=ScanWorker(ROOT,q); self.scan_worker.progress.connect(self.progress.setValue); self.scan_worker.done.connect(self.search_done); self.scan_worker.start()
    def search_done(self,results,error):
        self.progress.setVisible(False)
        if error: self.status.setText("Search error: "+error); return
        sf=self.filter.currentText(); self.table.setSortingEnabled(False); self.table.setRowCount(0); shown=0
        for p in sorted(results,key=lambda x:(not x.is_dir(),x.name.lower())):
            if p.is_dir() or sf=="All types" or category(p.suffix)==sf: self.add_row(p); shown+=1
        self.table.setSortingEnabled(True); self.file_title.setText(f"SEARCH RESULTS • {shown:,}"); self.status.setText(f"{shown:,} matching items")
    def tree_path(self):
        i=self.tree.currentIndex(); return Path(self.model.filePath(i)) if i.isValid() else None
    def tree_menu(self,pos):
        p=self.tree_path(); m=QMenu(self)
        if p:
            m.addAction("Open folder",lambda:self.navigate(p)); m.addAction("New folder",self.new_folder); m.addAction("Rename",self.rename_tree_item); m.addAction("Properties",lambda:PropertiesDialog(p,self).exec())
            if p!=ROOT: m.addAction("Delete",self.delete_tree_item)
        m.exec(self.tree.viewport().mapToGlobal(pos))
    def rename_tree_item(self):
        p=self.tree_path()
        if not p or p==ROOT: return
        name,ok=QInputDialog.getText(self,"Rename folder","New name:",text=p.name)
        if ok and name.strip():
            try: p.rename(p.with_name(name.strip())); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"Rename failed",str(e))
    def delete_tree_item(self):
        p=self.tree_path()
        if not p or p==ROOT: return
        if QMessageBox.question(self,"Delete folder",f"Move folder to Recycle Bin?\n\n{p}",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
        try:
            if send2trash: send2trash(str(p))
            else: shutil.rmtree(p)
            self.refresh_all()
        except Exception as e: QMessageBox.critical(self,"Delete failed",str(e))
    def file_menu(self,pos):
        p=self.selected_path(); m=QMenu(self)
        if p:
            m.addAction("Open",self.open_item); m.addAction("Edit",self.edit_item); m.addAction("Rename",self.rename_item); m.addAction("Copy",self.copy_items); m.addAction("Move",self.move_items); m.addAction("Properties",self.properties); m.addSeparator(); m.addAction("Delete",self.delete_items); m.addAction("Open containing folder",lambda:open_path(p.parent))
        m.exec(self.table.viewport().mapToGlobal(pos))
    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Escape and self.search.text(): self.search.clear(); self.populate_files(); return
        if e.key()==Qt.Key_F and e.modifiers() & Qt.ControlModifier: self.search.setFocus(); e.accept(); return
        super().keyPressEvent(e)


def main():
    app=QApplication(sys.argv); app.setApplicationName("JASS Landsoft Explorer")
    if not ROOT.exists(): QMessageBox.critical(None,"Landsoft not found",f"Configured folder does not exist:\n{ROOT}"); return 1
    win=LandsoftExplorer(); win.show(); return app.exec()

if __name__=="__main__": sys.exit(main())
