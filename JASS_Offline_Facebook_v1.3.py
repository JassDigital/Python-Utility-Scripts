import os, sys, json, html, re, webbrowser
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QStackedWidget, QLabel,
    QLineEdit, QPushButton, QFrame, QScrollArea, QGridLayout,
    QMessageBox, QFileDialog, QComboBox, QTextBrowser, QStatusBar
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage
    WEBENGINE_AVAILABLE = True
except Exception:
    QWebEngineView = None
    QWebEnginePage = None
    WEBENGINE_AVAILABLE = False

IMAGE={".jpg",".jpeg",".png",".gif",".bmp",".webp",".tif",".tiff"}
VIDEO={".mp4",".mov",".mkv",".avi",".webm",".3gp",".m4v"}
AUDIO={".mp3",".m4a",".wav",".ogg",".aac",".flac"}
MEDIA=IMAGE|VIDEO|AUDIO
ROOT=Path("F:/")


def jload(p):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def parse_json_message(p):
    d=jload(p)
    if not isinstance(d,dict) or not isinstance(d.get("messages"),list):
        return None
    parts=[]
    for x in d.get("participants",[]):
        if isinstance(x,dict): x=x.get("name") or x.get("id")
        if x: parts.append(str(x))
    msgs=[]
    for m in d["messages"]:
        if not isinstance(m,dict): continue
        ts=m.get("timestamp_ms")
        try:
            tm=datetime.fromtimestamp(int(ts)/1000).strftime("%Y-%m-%d %H:%M") if ts else ""
        except Exception:
            tm=str(ts or "")
        sender=m.get("sender_name") or m.get("sender") or m.get("from") or "Unknown"
        content=m.get("content") or m.get("message") or ""
        msgs.append({"sender":str(sender),"content":str(content),"time":tm})
    return {
        "title":str(d.get("title") or p.stem),
        "participants":parts,
        "messages":msgs,
        "path":p,
        "kind":"JSON"
    }


def html_title(p):
    try:
        s=p.read_text(encoding="utf-8-sig",errors="ignore")[:50000]
        for pattern in (r"<title[^>]*>(.*?)</title>", r"<h[12][^>]*>(.*?)</h[12]>"):
            m=re.search(pattern,s,re.I|re.S)
            if m:
                t=re.sub(r"<[^>]+>"," ",m.group(1))
                t=" ".join(html.unescape(t).split())
                if t: return t
    except Exception:
        pass
    return p.stem.replace("_"," ")


def html_preview_text(p):
    try:
        s=p.read_text(encoding="utf-8-sig",errors="ignore")
        s=re.sub(r"(?is)<script.*?</script>"," ",s)
        s=re.sub(r"(?is)<style.*?</style>"," ",s)
        s=re.sub(r"(?is)<noscript.*?</noscript>"," ",s)
        s=re.sub(r"(?is)<[^>]+>"," ",s)
        return " ".join(html.unescape(s).split())
    except Exception:
        return ""


def parse_html_message(p):
    return {
        "title":html_title(p),
        "participants":[],
        "messages":[],
        "path":p,
        "kind":"HTML",
        "preview":html_preview_text(p)[:300]
    }


def parse_message(p):
    """Dispatch parser for the selected source. v1.2 accidentally omitted this."""
    p=Path(p)
    if p.suffix.lower()==".json":
        return parse_json_message(p)
    if p.suffix.lower() in (".html",".htm"):
        return parse_html_message(p)
    return None


def html_sources(root):
    """Find HTML throughout the export, not only in messages."""
    out=[]
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".html",".htm"):
            try:
                d=parse_html_message(p)
                rel=str(p.relative_to(root))
            except Exception:
                continue
            out.append((p,d,rel))
    return sorted(out,key=lambda x:x[2].lower())


def message_sources(root):
    out=[]
    b=root/"messages"
    if not b.exists(): return out

    for p in b.rglob("*.json"):
        d=parse_json_message(p)
        if d: out.append((p,d))

    for p in sorted(list(b.rglob("*.html"))+list(b.rglob("*.htm"))):
        out.append((p,parse_html_message(p)))
    return out


def media_files(root):
    out=[]; seen=set()
    for folder in ("photos_and_videos","messages","posts","stories","comments"):
        b=root/folder
        if not b.exists(): continue
        for p in b.rglob("*"):
            if p.is_file() and p.suffix.lower() in MEDIA:
                k=str(p).lower()
                if k not in seen:
                    seen.add(k); out.append(p)
    return out


class Scan(QThread):
    done=Signal(object)
    status=Signal(str)
    def __init__(self,root):
        super().__init__(); self.root=root
    def run(self):
        self.status.emit("Indexing Facebook export — messages, HTML, media and files...")
        files=folders=0
        try:
            for _,ds,fs in os.walk(self.root,followlinks=False):
                folders+=len(ds); files+=len(fs)
        except Exception:
            pass
        self.done.emit({
            "messages":message_sources(self.root),
            "html":html_sources(self.root),
            "media":media_files(self.root),
            "files":files,
            "folders":folders
        })


class OfflinePage(QWebEnginePage if WEBENGINE_AVAILABLE else QWidget):
    if WEBENGINE_AVAILABLE:
        def acceptNavigationRequest(self,url,nav_type,is_main_frame):
            # Keep the viewer offline: local export links work; web links open externally.
            if url.isLocalFile() or url.scheme() in ("about", "data"):
                return True
            webbrowser.open(url.toString())
            return False


class Card(QFrame):
    clicked=Signal(object)
    def __init__(self,p):
        super().__init__(); self.p=p; self.setObjectName("mediaCard")
        l=QVBoxLayout(self); im=QLabel(); im.setAlignment(Qt.AlignCenter); im.setFixedHeight(120)
        e=p.suffix.lower()
        if e in IMAGE:
            q=QPixmap(str(p))
            if not q.isNull():
                im.setPixmap(q.scaled(175,115,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            else: im.setText("IMAGE")
        elif e in VIDEO: im.setText("▶ VIDEO")
        else: im.setText("♪ AUDIO")
        l.addWidget(im)
        n=QLabel(p.name); n.setWordWrap(True); n.setAlignment(Qt.AlignCenter); l.addWidget(n)
    def mousePressEvent(self,e):
        self.clicked.emit(self.p); super().mousePressEvent(e)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JASS OFFLINE FACEBOOK v1.3")
        self.resize(1500,900)
        self.root=None; self.data={}; self.worker=None
        self.ui(); self.style()

    def ui(self):
        c=QWidget(); self.setCentralWidget(c)
        o=QVBoxLayout(c); o.setContentsMargins(0,0,0,0)

        bar=QFrame(); bar.setObjectName("bar"); h=QHBoxLayout(bar)
        logo=QLabel("facebook"); logo.setObjectName("logo"); h.addWidget(logo)
        self.search=QLineEdit(); self.search.setPlaceholderText("Search your offline Facebook data...")
        self.search.returnPressed.connect(self.search_all); h.addWidget(self.search,1)
        self.open_root_btn=QPushButton("OPEN ROOT INDEX")
        self.open_root_btn.clicked.connect(self.open_root_index); self.open_root_btn.setEnabled(False); h.addWidget(self.open_root_btn)
        b=QPushButton("OPEN EXPORT"); b.clicked.connect(self.choose); h.addWidget(b)
        o.addWidget(bar)

        body=QHBoxLayout(); o.addLayout(body,1)
        nav=QFrame(); nav.setObjectName("nav"); nl=QVBoxLayout(nav)
        self.nav=QListWidget()
        for x in ["Home","Messages","Media","HTML Pages","Posts","Friends","Groups","Events","Profile","All Files"]:
            self.nav.addItem(x)
        self.nav.currentRowChanged.connect(self.page); nl.addWidget(self.nav)
        self.root_label=QLabel("No export opened"); self.root_label.setWordWrap(True); nl.addWidget(self.root_label)
        body.addWidget(nav)

        self.pages=QStackedWidget(); body.addWidget(self.pages,1)
        self.home=self.home_page(); self.msg=self.message_page(); self.med=self.media_page(); self.htmlpage=self.html_page(); self.generic=self.generic_page()
        for x in (self.home,self.msg,self.med,self.htmlpage,self.generic): self.pages.addWidget(x)

        self.status=QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Offline mode — local export only.")
        self.nav.setCurrentRow(0)

    def home_page(self):
        w=QWidget(); l=QVBoxLayout(w)
        a=QLabel("Your Offline Facebook"); a.setObjectName("hero"); l.addWidget(a)
        s=QLabel("Browse your downloaded Facebook data privately. Local HTML links work inside the viewer; external web links are opened outside it.")
        s.setWordWrap(True); l.addWidget(s)
        row=QHBoxLayout(); self.stats={}
        for k,t in [("files","FILES"),("folders","FOLDERS"),("messages","MESSAGE SOURCES"),("html","HTML PAGES"),("media","MEDIA")]:
            f=QFrame(); f.setObjectName("stat"); z=QVBoxLayout(f)
            q=QLabel(t); q.setObjectName("statLabel"); v=QLabel("0"); v.setObjectName("statValue")
            z.addWidget(q); z.addWidget(v); self.stats[k]=v; row.addWidget(f)
        l.addLayout(row)
        self.home_info=QLabel("Click OPEN EXPORT to load your Facebook download."); self.home_info.setWordWrap(True); l.addWidget(self.home_info)
        self.feature_info=QLabel("v1.3: fixed conversation click handling • full local HTML viewer • root index • HTML search • media search/filter • containing-folder actions")
        self.feature_info.setWordWrap(True); l.addWidget(self.feature_info); l.addStretch(); return w

    def make_html_view(self):
        if WEBENGINE_AVAILABLE:
            view=QWebEngineView()
            view.setPage(OfflinePage(view))
            return view
        view=QTextBrowser(); view.setOpenExternalLinks(False); view.anchorClicked.connect(self.handle_link)
        return view

    def load_local_html(self,view,p):
        url=QUrl.fromLocalFile(str(Path(p).resolve()))
        if WEBENGINE_AVAILABLE and isinstance(view,QWebEngineView):
            view.setUrl(url)
        else:
            view.setSource(url)

    def message_page(self):
        w=QWidget(); l=QHBoxLayout(w); sp=QSplitter(Qt.Horizontal); l.addWidget(sp)
        left=QWidget(); ll=QVBoxLayout(left)
        self.msg_search=QLineEdit(); self.msg_search.setPlaceholderText("Search conversations and message pages...")
        self.msg_search.textChanged.connect(self.filter_msg); ll.addWidget(self.msg_search)
        self.convos=QListWidget(); self.convos.currentRowChanged.connect(self.open_msg); ll.addWidget(self.convos)
        sp.addWidget(left)

        right=QWidget(); rl=QVBoxLayout(right); head=QHBoxLayout()
        self.chat_title=QLabel("Messages"); self.chat_title.setObjectName("chatTitle"); head.addWidget(self.chat_title,1)
        self.chat_back=QPushButton("BACK"); self.chat_back.clicked.connect(lambda: self.web_back(self.chat_browser)); head.addWidget(self.chat_back)
        self.chat_forward=QPushButton("FORWARD"); self.chat_forward.clicked.connect(lambda: self.web_forward(self.chat_browser)); head.addWidget(self.chat_forward)
        self.chat_reload=QPushButton("RELOAD"); self.chat_reload.clicked.connect(lambda: self.web_reload(self.chat_browser)); head.addWidget(self.chat_reload)
        self.open_html_btn=QPushButton("OPEN HTML"); self.open_html_btn.clicked.connect(self.open_selected_html); self.open_html_btn.setEnabled(False); head.addWidget(self.open_html_btn)
        rl.addLayout(head)
        self.chat_info=QLabel("Select a message page from the list."); rl.addWidget(self.chat_info)
        self.chat_browser=self.make_html_view(); rl.addWidget(self.chat_browser,1)
        sp.addWidget(right); sp.setSizes([420,880]); return w

    def media_page(self):
        w=QWidget(); l=QVBoxLayout(w); h=QHBoxLayout()
        self.med_search=QLineEdit(); self.med_search.setPlaceholderText("Search media..."); self.med_search.textChanged.connect(self.populate_media); h.addWidget(self.med_search)
        self.med_filter=QComboBox(); self.med_filter.addItems(["All","Images","Videos","Audio"]); self.med_filter.currentTextChanged.connect(self.populate_media); h.addWidget(self.med_filter)
        l.addLayout(h); sc=QScrollArea(); sc.setWidgetResizable(True)
        self.medw=QWidget(); self.grid=QGridLayout(self.medw); self.grid.setAlignment(Qt.AlignTop); sc.setWidget(self.medw); l.addWidget(sc); return w

    def html_page(self):
        w=QWidget(); l=QVBoxLayout(w); sp=QSplitter(Qt.Horizontal); l.addWidget(sp)
        left=QWidget(); ll=QVBoxLayout(left)
        self.html_search=QLineEdit(); self.html_search.setPlaceholderText("Search all HTML pages..."); self.html_search.textChanged.connect(self.filter_html); ll.addWidget(self.html_search)
        self.html_list=QListWidget(); self.html_list.currentRowChanged.connect(self.open_html_page); ll.addWidget(self.html_list); sp.addWidget(left)
        right=QWidget(); rl=QVBoxLayout(right); h=QHBoxLayout()
        self.html_title_label=QLabel("HTML Viewer"); self.html_title_label.setObjectName("chatTitle"); h.addWidget(self.html_title_label,1)
        self.html_back=QPushButton("BACK"); self.html_back.clicked.connect(lambda: self.web_back(self.html_view)); h.addWidget(self.html_back)
        self.html_forward=QPushButton("FORWARD"); self.html_forward.clicked.connect(lambda: self.web_forward(self.html_view)); h.addWidget(self.html_forward)
        self.html_reload=QPushButton("RELOAD"); self.html_reload.clicked.connect(lambda: self.web_reload(self.html_view)); h.addWidget(self.html_reload)
        self.browser_btn=QPushButton("OPEN IN BROWSER"); self.browser_btn.clicked.connect(self.open_current_browser); self.browser_btn.setEnabled(False); h.addWidget(self.browser_btn)
        self.folder_btn=QPushButton("OPEN FOLDER"); self.folder_btn.clicked.connect(self.open_html_folder); self.folder_btn.setEnabled(False); h.addWidget(self.folder_btn)
        rl.addLayout(h)
        self.html_view=self.make_html_view(); rl.addWidget(self.html_view,1)
        sp.addWidget(right); sp.setSizes([420,880]); return w

    def generic_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.gt=QLabel("Facebook Data"); self.gt.setObjectName("hero"); l.addWidget(self.gt); self.gb=QTextBrowser(); l.addWidget(self.gb); return w

    def choose(self):
        f=QFileDialog.getExistingDirectory(self,"Select Facebook export folder",str(self.root or ROOT))
        if f: self.load(Path(f))

    def load(self,r):
        self.root=r; self.root_label.setText(str(r)); self.nav.setEnabled(False); self.open_root_btn.setEnabled(False)
        self.status.showMessage("Indexing Facebook export...")
        self.worker=Scan(r); self.worker.status.connect(self.status.showMessage); self.worker.done.connect(self.ready); self.worker.start()

    def ready(self,d):
        self.data=d; self.nav.setEnabled(True); self.open_root_btn.setEnabled((self.root/"index.html").exists())
        for k in ("files","folders"): self.stats[k].setText(f"{d[k]:,}")
        self.stats["messages"].setText(f"{len(d['messages']):,}"); self.stats["html"].setText(f"{len(d['html']):,}"); self.stats["media"].setText(f"{len(d['media']):,}")
        self.home_info.setText(f"Loaded: {self.root}\n\nFound {len(d['messages']):,} message source(s), {len(d['html']):,} HTML pages and {len(d['media']):,} media files.")
        self.populate_convos(); self.populate_html(); self.populate_media(); self.nav.setCurrentRow(1 if d["messages"] else 3); self.status.showMessage("Export ready — offline mode.")

    def page(self,r):
        if r in (0,1,2,3): self.pages.setCurrentIndex(r)
        else:
            self.pages.setCurrentIndex(4); self.gt.setText(self.nav.item(r).text()); self.generic_show(r)

    def populate_convos(self):
        self.convos.clear()
        for p,d in self.data.get("messages",[]):
            title=d.get("title") or p.stem
            if d.get("kind")=="HTML": preview=d.get("preview","")
            else: preview=next((m["content"] for m in d.get("messages",[]) if m.get("content")),"")
            item=QListWidgetItem(("🌐 " if d.get("kind")=="HTML" else "💬 ")+title+(f"\n{preview[:110]}" if preview else ""))
            item.setData(Qt.UserRole,str(p)); item.setToolTip(str(p)); self.convos.addItem(item)
        if self.convos.count(): self.convos.setCurrentRow(0)
        else:
            self.chat_title.setText("No message pages found"); self.chat_info.setText("No JSON or HTML files were found below the messages folder.")

    def filter_msg(self,q):
        q=q.lower().strip()
        for i in range(self.convos.count()): self.convos.item(i).setHidden(bool(q) and q not in self.convos.item(i).text().lower())

    def open_msg(self,r):
        if r<0 or r>=self.convos.count(): return
        item=self.convos.item(r); p=Path(item.data(Qt.UserRole)); d=parse_message(p)
        self.chat_title.setText(item.text().split("\n",1)[0]); self.chat_info.setText(str(p)); ishtml=p.suffix.lower() in (".html",".htm"); self.open_html_btn.setEnabled(ishtml)
        if ishtml:
            self.load_local_html(self.chat_browser,p); return
        self.chat_browser.setHtml(self.render_json_chat(d)) if hasattr(self.chat_browser,"setHtml") else None

    def render_json_chat(self,d):
        if not d:return "<h3>Could not parse this conversation.</h3>"
        parts=", ".join(d.get("participants",[])); out=["<style>body{background:#0c141b;color:#d9e6ed;font-family:Segoe UI}.m{padding:10px;margin:8px;border:1px solid #234657;border-radius:8px}.s{color:#39e6ff;font-weight:bold}.t{color:#708894;font-size:11px}</style>"]
        out.append(f"<h3>{html.escape(d.get('title','Messages'))}</h3>")
        if parts: out.append(f"<p>{html.escape(parts)}</p>")
        for m in d.get("messages",[]):
            out.append(f"<div class='m'><div class='s'>{html.escape(str(m.get('sender','Unknown')))}</div><div>{html.escape(str(m.get('content','')))}</div>")
            if m.get("time"): out.append(f"<div class='t'>{html.escape(str(m['time']))}</div>")
            out.append("</div>")
        return "".join(out)

    def open_selected_html(self):
        if self.convos.currentItem():
            p=Path(self.convos.currentItem().data(Qt.UserRole))
            if p.exists(): webbrowser.open(p.as_uri())

    def populate_html(self):
        self.html_list.clear()
        for p,d,rel in self.data.get("html",[]):
            item=QListWidgetItem("🌐 "+d.get("title",p.name)); item.setData(Qt.UserRole,str(p)); item.setToolTip(rel); self.html_list.addItem(item)
        if self.html_list.count(): self.html_list.setCurrentRow(0)

    def filter_html(self,q):
        q=q.lower().strip()
        for i in range(self.html_list.count()): self.html_list.item(i).setHidden(bool(q) and q not in (self.html_list.item(i).text()+" "+self.html_list.item(i).toolTip()).lower())

    def open_html_page(self,r):
        if r<0 or r>=self.html_list.count(): return
        p=Path(self.html_list.item(r).data(Qt.UserRole)); self.html_title_label.setText(p.name); self.browser_btn.setEnabled(p.exists()); self.folder_btn.setEnabled(p.exists()); self.load_local_html(self.html_view,p); self.status.showMessage(str(p))

    def open_current_browser(self):
        if self.html_list.currentItem():
            p=Path(self.html_list.currentItem().data(Qt.UserRole))
            if p.exists(): webbrowser.open(p.as_uri())

    def open_html_folder(self):
        if not self.html_list.currentItem(): return
        p=Path(self.html_list.currentItem().data(Qt.UserRole))
        if p.exists(): webbrowser.open(p.parent.as_uri())

    def open_root_index(self):
        p=self.root/"index.html" if self.root else None
        if p and p.exists():
            self.nav.setCurrentRow(3)
            for i in range(self.html_list.count()):
                if Path(self.html_list.item(i).data(Qt.UserRole)).resolve()==p.resolve():
                    self.html_list.setCurrentRow(i); break

    def web_back(self,v):
        if WEBENGINE_AVAILABLE and isinstance(v,QWebEngineView): v.back()
        elif hasattr(v,"backward"): v.backward()

    def web_forward(self,v):
        if WEBENGINE_AVAILABLE and isinstance(v,QWebEngineView): v.forward()
        elif hasattr(v,"forward"): v.forward()

    def web_reload(self,v):
        if WEBENGINE_AVAILABLE and isinstance(v,QWebEngineView): v.reload()
        elif hasattr(v,"reload"): v.reload()

    def handle_link(self,url):
        if url.isLocalFile(): self.html_view.setSource(url); self.chat_browser.setSource(url)
        else: webbrowser.open(url.toString())

    def populate_media(self):
        while self.grid.count():
            x=self.grid.takeAt(0)
            if x.widget(): x.widget().deleteLater()
        q=self.med_search.text().lower(); f=self.med_filter.currentText(); arr=[]
        for p in self.data.get("media",[]):
            if q and q not in p.name.lower(): continue
            e=p.suffix.lower()
            if f=="Images" and e not in IMAGE: continue
            if f=="Videos" and e not in VIDEO: continue
            if f=="Audio" and e not in AUDIO: continue
            arr.append(p)
        for i,p in enumerate(arr):
            c=Card(p); c.clicked.connect(lambda path: webbrowser.open(path.as_uri())); self.grid.addWidget(c,i//5,i%5)
        self.status.showMessage(f"{len(arr):,} media items")

    def search_all(self):
        q=self.search.text().strip()
        if q: self.nav.setCurrentRow(1); self.msg_search.setText(q)

    def generic_show(self,r):
        if not self.root: self.gb.setHtml("<h2>Open an export folder first</h2>"); return
        folder={4:"posts",5:"friends",6:"groups",7:"events",8:"profile_information",9:""}.get(r,"")
        b=self.root/folder if folder else self.root
        if not b.exists(): self.gb.setHtml("<p>This section was not found in this export.</p>"); return
        fs=[p for p in b.rglob("*") if p.is_file()]
        out=[f"<h2>{html.escape(self.gt.text())}</h2><p><b>{len(fs):,}</b> files found.</p><ul>"]
        for p in fs[:3000]:
            rel=p.relative_to(self.root).as_posix()
            if p.suffix.lower() in (".html",".htm"):
                out.append(f"<li><a href='file:///{p.as_posix()}'>{html.escape(rel)}</a></li>")
            else: out.append(f"<li>{html.escape(rel)}</li>")
        if len(fs)>3000: out.append(f"<li>Showing first 3,000 of {len(fs):,} files.</li>")
        out.append("</ul>"); self.gb.setHtml("".join(out))

    def style(self):
        self.setStyleSheet("""
        QWidget{background:#080f15;color:#d9e6ed;font-family:Segoe UI;font-size:13px}
        #bar{background:#1877f2;border-bottom:2px solid #39e6ff}
        #logo{background:#fff;color:#111;font-size:25px;font-weight:800;padding:0 7px}
        QLineEdit,QComboBox,QListWidget,QTextBrowser{background:#0c141b;border:1px solid #214554;border-radius:5px;padding:6px;color:#d9e6ed}
        QListWidget::item{padding:13px 10px;border-bottom:1px solid #162b36}
        QListWidget::item:selected{background:#155d78;border:1px solid #39e6ff}
        #nav{background:#091219;border-right:1px solid #214554}
        QPushButton{background:#0d1a23;border:1px solid #2c6175;border-radius:5px;padding:8px 12px;color:#d9e6ed}
        QPushButton:hover{background:#155d78;border-color:#39e6ff}
        QPushButton:disabled{color:#4b6670;border-color:#29414a}
        #hero{font-size:28px;font-weight:700;color:#39e6ff}
        #chatTitle{font-size:24px;font-weight:700;color:#39e6ff}
        #stat{border:1px solid #214554;border-radius:8px;padding:8px}
        #statLabel{color:#6f9aaa;font-size:11px}
        #statValue{font-size:24px;font-weight:700;color:#39e6ff}
        #mediaCard{border:1px solid #214554;border-radius:8px;padding:5px}
        #mediaCard:hover{border-color:#39e6ff}
        QSplitter::handle{background:#214554}
        QStatusBar{background:#091219;color:#6f9aaa}
        """)


if __name__=="__main__":
    app=QApplication(sys.argv)
    w=Window(); w.show()
    sys.exit(app.exec())
