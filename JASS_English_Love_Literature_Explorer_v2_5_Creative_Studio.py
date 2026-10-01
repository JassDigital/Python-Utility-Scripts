import sys, json, re, zipfile, html
from pathlib import Path
from html.parser import HTMLParser

from PySide6.QtCore import Qt, QSettings, QPointF, QRectF
from PySide6.QtGui import (
    QAction, QColor, QBrush, QPen, QPainter, QPixmap, QFont,
    QTextOption
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QLabel,
    QPushButton, QSplitter, QComboBox, QGroupBox, QFormLayout,
    QSlider, QColorDialog, QSpinBox, QFileDialog, QMessageBox,
    QTabWidget, QCheckBox, QPlainTextEdit, QGraphicsView,
    QGraphicsScene, QGraphicsTextItem, QGraphicsRectItem, QGraphicsItem,
    QScrollArea
)

APP_NAME = "JASS English Love Literature Explorer"
DEFAULT_FOLDER = Path(r"C:\Users\singh\Downloads\JASS_English_Love_Literature")


# ----------------------------------------------------------------------
# EPUB READER
# ----------------------------------------------------------------------

class SimpleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "svg", "head"):
            self.skip += 1
        elif not self.skip and tag in (
            "p", "div", "section", "article",
            "h1", "h2", "h3", "h4", "h5", "h6",
            "li", "blockquote", "br"
        ):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "svg", "head"):
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in (
            "p", "div", "section", "article",
            "h1", "h2", "h3", "h4", "h5", "h6",
            "li", "blockquote"
        ):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            data = html.unescape(data)
            if data.strip():
                self.parts.append(data)


def html_to_text(raw):
    parser = SimpleHTMLParser()
    parser.feed(raw)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_epub(path):
    sections = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for name in names:
            low = name.lower()
            if not low.endswith((".xhtml", ".html", ".htm")):
                continue
            if Path(name).name.lower() == "nav.xhtml":
                continue
            try:
                text = html_to_text(z.read(name).decode("utf-8", errors="replace"))
                if text:
                    sections.append((name, text))
            except Exception:
                pass
    return sections


def title_from_path(path):
    stem = Path(path).stem
    for sep in (" — ", " – ", " - "):
        if sep in stem:
            return stem.split(sep, 1)[0].strip()
    return stem


def author_from_path(path):
    stem = Path(path).stem
    for sep in (" — ", " – ", " - "):
        if sep in stem:
            return stem.rsplit(sep, 1)[1].strip()
    return "Unknown / not specified"


def category_for(path):
    s = Path(path).stem.lower()
    if any(x in s for x in (
        "erotica", "venus", "maupin", "crimes de l'amour",
        "sex life"
    )):
        return "Sensual / Erotic Literature"
    if any(x in s for x in (
        "love letter", "love letters", "love-story",
        "love story", "love affair", "love affairs"
    )):
        return "Love / Romance"
    if any(x in s for x in (
        "romance", "romantic", "romeo", "juliet",
        "courtship", "wooing", "passionate"
    )):
        return "Romance / Courtship"
    return "Fiction / Related"


# ----------------------------------------------------------------------
# CREATIVE CANVAS
# ----------------------------------------------------------------------

class DesignTextItem(QGraphicsTextItem):
    """A movable, editable and mouse-resizable text block."""

    HANDLE_SIZE = 18

    def __init__(self, text="", role="body"):
        super().__init__(text)
        self.role = role
        self._font_size = 34 if role == "quote" else 24
        self._scale_percent = 100
        self._resizing = False
        self._resize_start_x = 0.0
        self._resize_start_width = 680.0

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True
        )
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction
        )
        self.setDefaultTextColor(QColor("#542B3A"))
        self.set_font_size(self._font_size)
        self.setTextWidth(680)

    def set_font_size(self, size):
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 24
        self._font_size = max(8, size)
        font = self.font()
        font.setPointSize(max(8, self._font_size))
        self.setFont(font)
        self.update()

    def font_size(self):
        return self._font_size

    def set_scale_percent(self, value):
        self._scale_percent = max(40, min(250, int(value)))
        self.setScale(self._scale_percent / 100.0)
        self.update()

    def scale_percent(self):
        return self._scale_percent

    def set_alignment(self, alignment):
        option = self.document().defaultTextOption()
        option.setAlignment(alignment)
        self.document().setDefaultTextOption(option)
        self.update()

    def alignment(self):
        return self.document().defaultTextOption().alignment()

    def _resize_zone(self):
        r = self.boundingRect()
        return QRectF(
            r.right() - self.HANDLE_SIZE * 1.6,
            r.bottom() - self.HANDLE_SIZE * 1.6,
            self.HANDLE_SIZE * 2.2,
            self.HANDLE_SIZE * 2.2,
        )

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)

        if self.isSelected():
            r = self.boundingRect().adjusted(-4, -4, 4, 4)

            pen = QPen(QColor("#B14E73"), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)

            handle = self._resize_zone()
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            painter.setBrush(QBrush(QColor("#B14E73")))
            painter.drawRect(handle)

            painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
            painter.drawLine(
                handle.left() + 4,
                handle.bottom() - 4,
                handle.right() - 4,
                handle.top() + 4,
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setSelected(True)
            scene = self.scene()
            if scene and scene.views():
                view = scene.views()[0]
                if hasattr(view, "_last_selected_text"):
                    view._last_selected_text = self

        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.isSelected()
            and self._resize_zone().contains(event.pos())
        ):
            self._resizing = True
            self._resize_start_x = event.pos().x()
            self._resize_start_width = self.textWidth()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.pos().x() - self._resize_start_x
            new_width = max(120.0, self._resize_start_width + delta)
            self.setTextWidth(new_width)

            view = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if view and hasattr(view, "notify_item_changed"):
                view.notify_item_changed(self)

            self.update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self.update()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            scene = self.scene()
            if scene and scene.views():
                view = scene.views()[0]
                if hasattr(view, "notify_item_changed"):
                    view.notify_item_changed(self)

        return super().itemChange(change, value)


THEMES = {
    "Blush Romance": {
        "background": "#FFF4F7", "text": "#542B3A",
        "accent": "#C05A78", "font": "Georgia"
    },
    "Rose Garden": {
        "background": "#FBE4EA", "text": "#4A2030",
        "accent": "#9E3D5B", "font": "Georgia"
    },
    "Midnight Love": {
        "background": "#171522", "text": "#F8EAF0",
        "accent": "#D99AAF", "font": "Georgia"
    },
    "Lavender Dream": {
        "background": "#F3EEFF", "text": "#40345C",
        "accent": "#816AA8", "font": "Georgia"
    },
    "Ivory Letter": {
        "background": "#FFF9EA", "text": "#493B2F",
        "accent": "#A77A45", "font": "Georgia"
    },
    "Vintage Paper": {
        "background": "#EADCC5", "text": "#453629",
        "accent": "#805D3D", "font": "Baskerville"
    },
    "Ocean Poetry": {
        "background": "#E9F6F7", "text": "#20454B",
        "accent": "#3C7D86", "font": "Georgia"
    },
    "Forest Romance": {
        "background": "#EDF4EC", "text": "#29422D",
        "accent": "#52785A", "font": "Georgia"
    },
    "Golden Hour": {
        "background": "#FFF0D2", "text": "#5B4020",
        "accent": "#B7792C", "font": "Georgia"
    },
    "Pure Paper": {
        "background": "#FFFFFF", "text": "#202020",
        "accent": "#555555", "font": "Georgia"
    },
    "Wine & Velvet": {
        "background": "#2A1720", "text": "#F9E5EC",
        "accent": "#C47A91", "font": "Palatino Linotype"
    },
    "Moonlit Blue": {
        "background": "#EAF0FA", "text": "#273A59",
        "accent": "#617DAA", "font": "Georgia"
    },
    "Sage & Cream": {
        "background": "#F1F4E9", "text": "#34432E",
        "accent": "#718460", "font": "Palatino Linotype"
    },
    "Peach Glow": {
        "background": "#FFF0E6", "text": "#663F34",
        "accent": "#D17E62", "font": "Georgia"
    },
    "Mauve Poetry": {
        "background": "#F1E5EF", "text": "#523B50",
        "accent": "#9C6E96", "font": "Georgia"
    },
    "Black & Champagne": {
        "background": "#171717", "text": "#F2E2B8",
        "accent": "#C8A85D", "font": "Baskerville"
    },
}


class CreativeCanvas(QGraphicsView):
    """Scrollable multi-page design surface."""

    PAGE_GAP = 70

    def __init__(self):
        super().__init__()

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self.page_width = 900
        self.page_height = 1100
        self.page_count = 1

        # Word-like page margins used by automatic body-text flow.
        self.margin_top = 85
        self.margin_bottom = 85
        self.margin_left = 90
        self.margin_right = 90

        self.bg_color = QColor("#FFF4F7")
        self.bg_alpha = 255
        self.bg_image = None
        self.bg_image_path = ""

        self.pages = []
        # Keep the last selected text item available when focus moves from
        # the canvas to a control (for example the color picker).
        self._last_selected_text = None

        self.setBackgroundBrush(QBrush(QColor("#D8D3D7")))
        self.setStyleSheet(
            "QGraphicsView { border: 0; border-radius: 10px; }"
        )

        self._rebuild_pages()

    @property
    def total_height(self):
        return (
            self.page_count * self.page_height
            + (self.page_count - 1) * self.PAGE_GAP
        )

    def page_y(self, index):
        return index * (self.page_height + self.PAGE_GAP)

    def _rebuild_pages(self):
        for page in self.pages:
            self.scene.removeItem(page)
        self.pages = []

        for i in range(self.page_count):
            y = self.page_y(i)
            page = QGraphicsRectItem(
                0, y, self.page_width, self.page_height
            )
            page.setBrush(Qt.BrushStyle.NoBrush)
            page.setPen(QPen(QColor("#C7B9C0"), 2))
            page.setZValue(-1000)
            self.scene.addItem(page)
            self.pages.append(page)

        self.scene.setSceneRect(
            -20,
            -20,
            self.page_width + 40,
            self.total_height + 40
        )
        self.scene.update()
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_width()

    def _fit_width(self):
        if self.page_width <= 0 or self.viewport().width() <= 30:
            return

        available = max(200, self.viewport().width() - 55)
        scale = min(1.0, available / float(self.page_width))

        self.resetTransform()
        self.scale(scale, scale)

        self.horizontalScrollBar().setValue(
            max(0, self.horizontalScrollBar().maximum() // 2)
        )

    def wheelEvent(self, event):
        # Ctrl+wheel zooms. Normal wheel remains a page/document scroll.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.12 if event.angleDelta().y() > 0 else 0.89
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def set_size(self, width, height):
        self.page_width = int(width)
        self.page_height = int(height)
        self._rebuild_pages()
        self._fit_width()

    def add_page(self):
        self.page_count += 1
        self._rebuild_pages()
        return self.page_count

    def remove_last_page(self):
        if self.page_count <= 1:
            return False

        # Do not remove a page that currently contains text.
        last_y = self.page_y(self.page_count - 1)
        last_bottom = last_y + self.page_height

        for item in self.scene.items():
            if isinstance(item, DesignTextItem):
                r = item.sceneBoundingRect()
                if r.intersects(
                    QRectF(0, last_y, self.page_width, self.page_height)
                ):
                    return False

        self.page_count -= 1
        self._rebuild_pages()
        return True

    def set_background_color(self, color):
        self.bg_color = QColor(color)
        self.bg_image = None
        self.bg_image_path = ""
        self._refresh_background()

    def set_background_image(self, filename):
        pix = QPixmap(filename)
        if pix.isNull():
            return False
        self.bg_image = pix
        self.bg_image_path = filename
        self._refresh_background()
        return True

    def clear_background_image(self):
        self.bg_image = None
        self.bg_image_path = ""
        self._refresh_background()

    def set_background_opacity(self, value):
        self.bg_alpha = max(0, min(255, int(value)))
        self._refresh_background()

    def _refresh_background(self):
        self.scene.update()
        self.viewport().update()

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        for i in range(self.page_count):
            y = self.page_y(i)
            page_rect = QRectF(
                0, y, self.page_width, self.page_height
            )

            if not rect.intersects(page_rect):
                continue

            # Base background.
            bg = QColor(self.bg_color)
            bg.setAlpha(self.bg_alpha)
            painter.setOpacity(1.0)
            painter.fillRect(page_rect, bg)

            # Optional image overlay.
            if self.bg_image and not self.bg_image.isNull():
                painter.setOpacity(self.bg_alpha / 255.0)
                painter.drawPixmap(
                    page_rect,
                    self.bg_image,
                    self.bg_image.rect()
                )

            painter.setOpacity(1.0)

            # Subtle inner border.
            painter.setPen(QPen(QColor("#C7B9C0"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(page_rect.adjusted(1, 1, -1, -1))

            # Page number for multi-page documents.
            if self.page_count > 1:
                painter.setPen(QPen(QColor("#9A8D94"), 1))
                painter.setFont(QFont("Segoe UI", 9))
                painter.drawText(
                    QRectF(
                        0,
                        y + self.page_height - 34,
                        self.page_width,
                        20
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    f"Page {i + 1}"
                )

        painter.restore()

    def selected_text(self):
        # Normal case: the graphics scene still reports the selected item.
        for item in self.scene.selectedItems():
            if isinstance(item, DesignTextItem):
                self._last_selected_text = item
                return item

        # Qt may clear the scene selection when a tool button receives focus.
        # Keep using the last real text selection for editing controls.
        item = self._last_selected_text
        if (
            isinstance(item, DesignTextItem)
            and item.scene() is self.scene
        ):
            return item

        self._last_selected_text = None
        return None

    def add_text(
        self,
        text,
        role="body",
        position=None,
        color=None,
        font_name=None
    ):
        item = DesignTextItem(text, role)

        item.setPos(
            position if position is not None
            else QPointF(self.margin_left, self.margin_top)
        )

        if color:
            item.setDefaultTextColor(QColor(color))

        if font_name:
            font = item.font()
            font.setFamily(font_name)
            item.setFont(font)

        self.scene.addItem(item)
        self.scene.clearSelection()
        item.setSelected(True)
        self._last_selected_text = item
        item.setFocus()

        self.notify_item_changed(item)
        return item

    def _measure_text_height(self, text, font, width):
        """Measure text using the same Qt document engine as the canvas."""
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setTextWidth(float(width))
        option = doc.defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(option)
        doc.setPlainText(text)
        return doc.size().height()

    def _split_for_page(self, text, font, width, max_height):
        """Return (page_text, remainder), preferring paragraph/word boundaries."""
        text = text.lstrip()
        if not text:
            return "", ""

        if self._measure_text_height(text, font, width) <= max_height:
            return text, ""

        lo, hi = 1, len(text)
        best = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = text[:mid]
            if self._measure_text_height(candidate, font, width) <= max_height:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1

        # Prefer a natural break before the hard character limit.
        cut = max(1, best)
        natural_positions = [
            text.rfind("\n\n", 0, cut),
            text.rfind("\n", 0, cut),
            text.rfind(" ", 0, cut),
        ]
        natural = max(natural_positions)
        if natural > 20:
            cut = natural
            if text[cut:cut + 2] == "\n\n":
                cut += 2
            elif text[cut:cut + 1] in ("\n", " "):
                cut += 1

        page_text = text[:cut].rstrip()
        remainder = text[cut:].lstrip()

        # A pathological long word may leave us with no useful natural break.
        if not page_text:
            page_text = text[:best].rstrip()
            remainder = text[best:].lstrip()

        return page_text, remainder

    def add_flowed_body(
        self, text, color=None, font_name=None, font_size=24, clear_existing=False
    ):
        """Place a long body passage across pages with Word-like margins."""
        text = text.strip()
        if not text:
            return []

        if clear_existing:
            self.clear_text()
            self.page_count = 1
            self._rebuild_pages()

        font = QFont(font_name or "Georgia", max(8, int(font_size)))
        width = max(120, self.page_width - self.margin_left - self.margin_right)
        max_height = max(100, self.page_height - self.margin_top - self.margin_bottom)

        chunks = []
        remainder = text
        while remainder:
            chunk, remainder = self._split_for_page(
                remainder, font, width, max_height
            )
            if not chunk:
                break
            chunks.append(chunk)

        required = max(1, len(chunks))
        if required != self.page_count:
            self.page_count = required
            self._rebuild_pages()

        items = []
        for index, chunk in enumerate(chunks):
            item = DesignTextItem(chunk, "body")
            item.set_font_size(font_size)
            f = item.font()
            f.setFamily(font.family())
            item.setFont(f)
            item.setTextWidth(width)
            item.setDefaultTextColor(QColor(color or "#542B3A"))
            item.setPos(
                QPointF(
                    self.margin_left,
                    self.page_y(index) + self.margin_top
                )
            )
            self.scene.addItem(item)
            items.append(item)

        self.scene.clearSelection()
        if items:
            items[0].setSelected(True)
            items[0].setFocus()
        self.scene.update()
        self.viewport().update()
        return items

    def reflow_body_items(self):
        """Reflow all body blocks into a clean multi-page reading layout."""
        bodies = [
            item for item in self.scene.items()
            if isinstance(item, DesignTextItem) and item.role == "body"
        ]
        if not bodies:
            return []

        bodies.sort(key=lambda x: (x.sceneBoundingRect().top(), x.pos().x()))
        text = "\n\n".join(item.toPlainText().strip() for item in bodies if item.toPlainText().strip())
        if not text:
            return []

        first = bodies[0]
        color = first.defaultTextColor().name(QColor.NameFormat.HexArgb)
        font = first.font()
        size = first.font_size()
        family = font.family()
        for item in bodies:
            self.scene.removeItem(item)

        return self.add_flowed_body(
            text, color=color, font_name=family, font_size=size, clear_existing=False
        )

    def notify_item_changed(self, item=None):
        """Keep the document tall enough for manually positioned items."""
        if item is None:
            return

        bottom = item.sceneBoundingRect().bottom()
        while bottom > self.total_height - self.margin_bottom:
            self.page_count += 1
            self._rebuild_pages()

        self.scene.update()
        self.viewport().update()

    def delete_selected(self):
        item = self.selected_text()
        if item:
            self.scene.removeItem(item)
            if self._last_selected_text is item:
                self._last_selected_text = None
            self.scene.clearSelection()
            self.scene.update()

    def duplicate_selected(self):
        item = self.selected_text()
        if not item:
            return None

        clone = self.add_text(
            item.toPlainText(),
            item.role,
            item.pos() + QPointF(35, 35),
            item.defaultTextColor().name(QColor.NameFormat.HexArgb),
            item.font().family()
        )
        clone.setTextWidth(item.textWidth())
        clone.set_font_size(item.font_size())
        clone.set_scale_percent(item.scale_percent())

        font = clone.font()
        font.setBold(item.font().bold())
        font.setItalic(item.font().italic())
        clone.setFont(font)
        clone.set_alignment(item.alignment())
        clone.setZValue(item.zValue() + 1)
        return clone

    def bring_front(self):
        item = self.selected_text()
        if item:
            max_z = max(
                [x.zValue() for x in self.scene.items()
                 if isinstance(x, DesignTextItem)],
                default=0
            )
            item.setZValue(max_z + 1)

    def send_back(self):
        item = self.selected_text()
        if item:
            min_z = min(
                [x.zValue() for x in self.scene.items()
                 if isinstance(x, DesignTextItem)],
                default=0
            )
            item.setZValue(min_z - 1)

    def clear_text(self):
        for item in list(self.scene.items()):
            if isinstance(item, DesignTextItem):
                self.scene.removeItem(item)
        self._last_selected_text = None
        self.scene.clearSelection()

    def export_png(self, filename):
        """Export the complete multi-page design as one tall PNG."""
        total_h = int(self.total_height)

        image = QPixmap(self.page_width, total_h)
        image.fill(Qt.GlobalColor.transparent)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Backgrounds.
        for i in range(self.page_count):
            y = self.page_y(i)
            page_rect = QRectF(
                0, y, self.page_width, self.page_height
            )

            bg = QColor(self.bg_color)
            bg.setAlpha(self.bg_alpha)
            painter.fillRect(page_rect, bg)

            if self.bg_image and not self.bg_image.isNull():
                painter.setOpacity(self.bg_alpha / 255.0)
                painter.drawPixmap(
                    page_rect,
                    self.bg_image,
                    self.bg_image.rect()
                )
                painter.setOpacity(1.0)

        # Render the scene into the tall image. Page rectangles have no
        # brush, so the text layer is rendered without duplicating the
        # backgrounds already painted above.
        self.scene.render(
            painter,
            QRectF(0, 0, self.page_width, self.total_height),
            QRectF(0, 0, self.page_width, self.total_height)
        )

        painter.end()
        return image.save(filename, "PNG")

    def export_pages(self, folder):
        """Export every page separately as page_001.png, page_002.png, ..."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)

        created = []

        for page_index in range(self.page_count):
            y = self.page_y(page_index)

            image = QPixmap(self.page_width, self.page_height)
            image.fill(Qt.GlobalColor.transparent)

            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            bg = QColor(self.bg_color)
            bg.setAlpha(self.bg_alpha)
            painter.fillRect(
                QRectF(0, 0, self.page_width, self.page_height),
                bg
            )

            if self.bg_image and not self.bg_image.isNull():
                painter.setOpacity(self.bg_alpha / 255.0)
                painter.drawPixmap(
                    QRectF(0, 0, self.page_width, self.page_height),
                    self.bg_image,
                    self.bg_image.rect()
                )
                painter.setOpacity(1.0)

            # Render this page's portion of the scene.
            self.scene.render(
                painter,
                QRectF(0, 0, self.page_width, self.page_height),
                QRectF(
                    0, y,
                    self.page_width,
                    self.page_height
                )
            )

            painter.end()

            filename = folder / f"page_{page_index + 1:03d}.png"
            image.save(str(filename), "PNG")
            created.append(str(filename))

        return created

    def project_data(self):
        items = []

        for item in self.scene.items():
            if not isinstance(item, DesignTextItem):
                continue

            font = item.font()

            items.append({
                "text": item.toPlainText(),
                "role": item.role,
                "x": item.pos().x(),
                "y": item.pos().y(),
                "width": item.textWidth(),
                "font_size": item.font_size(),
                "scale_percent": item.scale_percent(),
                "color": item.defaultTextColor().name(
                    QColor.NameFormat.HexArgb
                ),
                "font_family": font.family(),
                "bold": font.bold(),
                "italic": font.italic(),
                "alignment": int(item.alignment()),
                "z": item.zValue()
            })

        return {
            "version": 4,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "page_count": self.page_count,
            "margins": {
                "top": self.margin_top,
                "bottom": self.margin_bottom,
                "left": self.margin_left,
                "right": self.margin_right,
            },
            "page_gap": self.PAGE_GAP,
            "background_color": self.bg_color.name(
                QColor.NameFormat.HexArgb
            ),
            "background_alpha": self.bg_alpha,
            "background_image": self.bg_image_path,
            "items": items
        }

    def load_project(self, data):
        self.clear_text()

        self.page_width = int(
            data.get("page_width", 900)
        )
        self.page_height = int(
            data.get("page_height", 1100)
        )
        self.page_count = max(
            1,
            int(data.get("page_count", 1))
        )

        self.bg_color = QColor(
            data.get("background_color", "#FFF4F7")
        )
        self.bg_alpha = int(
            data.get("background_alpha", 255)
        )

        image_path = data.get("background_image", "")
        self.bg_image = None
        self.bg_image_path = ""

        if image_path and Path(image_path).exists():
            pix = QPixmap(image_path)
            if not pix.isNull():
                self.bg_image = pix
                self.bg_image_path = image_path

        self._rebuild_pages()

        for d in data.get("items", []):
            item = self.add_text(
                d.get("text", ""),
                d.get("role", "body"),
                QPointF(
                    float(d.get("x", 90)),
                    float(d.get("y", 130))
                ),
                d.get("color", "#542B3A"),
                d.get("font_family", "Georgia")
            )

            item.setTextWidth(
                float(d.get("width", 680))
            )
            item.set_font_size(
                int(d.get("font_size", 24))
            )
            item.set_scale_percent(
                int(d.get("scale_percent", 100))
            )

            font = item.font()
            font.setBold(bool(d.get("bold", False)))
            font.setItalic(bool(d.get("italic", False)))
            item.setFont(font)

            try:
                item.set_alignment(
                    Qt.AlignmentFlag(int(d.get("alignment", 1)))
                )
            except Exception:
                pass

            item.setZValue(float(d.get("z", 0)))

        self.scene.clearSelection()
        self._refresh_background()
        self._fit_width()


class CreativeStudio(QWidget):
    def __init__(self):
        super().__init__()
        self.canvas = CreativeCanvas()
        self._updating_controls = False
        self.build_ui()
        self.new_design("Quote Card")

    def build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # ---------------- LEFT CONTROL PANEL ----------------
        controls = QWidget()
        control_layout = QVBoxLayout(controls)
        control_layout.setContentsMargins(4, 4, 10, 4)
        control_layout.setSpacing(10)

        heading = QLabel(
            "<h2 style='margin:0'>✨ Creative Studio</h2>"
            "<span>Create beautiful literary cards, pages "
            "and letters.</span>"
        )
        heading.setWordWrap(True)
        heading.setObjectName("studioHeading")
        control_layout.addWidget(heading)

        type_box = QGroupBox("Design & Theme")
        type_layout = QFormLayout(type_box)

        self.design_type = QComboBox()
        self.design_type.addItems([
            "Quote Card",
            "Love Letter",
            "Beautiful Page",
            "Poetry Card",
            "Romantic Note",
            "Social Story"
        ])
        type_layout.addRow("Format:", self.design_type)

        self.theme = QComboBox()
        self.theme.addItems(list(THEMES.keys()))
        self.theme.currentTextChanged.connect(self.apply_theme)
        type_layout.addRow("Theme:", self.theme)

        new_button = QPushButton("＋ New Design")
        new_button.clicked.connect(
            lambda: self.new_design(
                self.design_type.currentText()
            )
        )
        type_layout.addRow(new_button)

        control_layout.addWidget(type_box)

        # ---------------- TEXT INPUT ----------------
        text_box = QGroupBox("Text Elements")
        text_layout = QVBoxLayout(text_box)

        self.text_editor = QPlainTextEdit()
        self.text_editor.setPlaceholderText(
            "Write or paste a quotation, passage, "
            "thought or love letter..."
        )
        self.text_editor.setMinimumHeight(120)
        self.text_editor.setMaximumHeight(180)
        self.text_editor.textChanged.connect(
            self.editor_text_changed
        )
        text_layout.addWidget(self.text_editor)

        row = QHBoxLayout()

        add_quote = QPushButton("＋ Quote")
        add_quote.clicked.connect(self.add_quote)
        row.addWidget(add_quote)

        add_body = QPushButton("＋ Body")
        add_body.clicked.connect(self.add_body)
        row.addWidget(add_body)

        text_layout.addLayout(row)

        row2 = QHBoxLayout()

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self.canvas.delete_selected)
        row2.addWidget(delete_btn)

        duplicate_btn = QPushButton("Duplicate")
        duplicate_btn.clicked.connect(self.canvas.duplicate_selected)
        row2.addWidget(duplicate_btn)

        text_layout.addLayout(row2)

        hint = QLabel(
            "Tip: drag a selected block. Drag its bottom-right "
            "handle to resize it."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777;")
        text_layout.addWidget(hint)

        control_layout.addWidget(text_box)

        # ---------------- TYPOGRAPHY ----------------
        typo_box = QGroupBox("Selected Text — Live Controls")
        typo = QFormLayout(typo_box)

        self.font_size = QSpinBox()
        self.font_size.setRange(8, 120)
        self.font_size.setValue(34)
        self.font_size.valueChanged.connect(self.update_selected)
        typo.addRow("Font size:", self.font_size)

        self.text_width = QSpinBox()
        self.text_width.setRange(100, 1200)
        self.text_width.setSingleStep(20)
        self.text_width.setValue(680)
        self.text_width.valueChanged.connect(self.update_selected)
        typo.addRow("Width:", self.text_width)

        self.scale = QSpinBox()
        self.scale.setRange(40, 250)
        self.scale.setSuffix("%")
        self.scale.setValue(100)
        self.scale.valueChanged.connect(self.update_selected)
        typo.addRow("Scale:", self.scale)

        self.font_family = QComboBox()
        self.font_family.addItems([
            "Georgia",
            "Times New Roman",
            "Baskerville",
            "Palatino Linotype",
            "Garamond",
            "Book Antiqua",
            "Arial",
            "Segoe UI"
        ])
        self.font_family.currentTextChanged.connect(
            self.update_selected
        )
        typo.addRow("Font:", self.font_family)

        self.alignment = QComboBox()
        self.alignment.addItems([
            "Left", "Center", "Right"
        ])
        self.alignment.currentTextChanged.connect(
            self.update_selected
        )
        typo.addRow("Alignment:", self.alignment)

        self.bold = QCheckBox("Bold")
        self.bold.stateChanged.connect(self.update_selected)
        typo.addRow("", self.bold)

        self.italic = QCheckBox("Italic")
        self.italic.stateChanged.connect(self.update_selected)
        typo.addRow("", self.italic)

        text_color = QPushButton("🎨 Choose Text Color…")
        text_color.clicked.connect(self.choose_text_color)
        typo.addRow(text_color)

        self.text_color_preview = QLabel("Current text color")
        self.text_color_preview.setMinimumHeight(26)
        self.text_color_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        typo.addRow("Current:", self.text_color_preview)

        # Useful quick color palette — no dialog required.
        palette_row = QHBoxLayout()
        for name, color in [
            ("Ink", "#202020"),
            ("Rose", "#B14E73"),
            ("Plum", "#663B65"),
            ("Blue", "#365A85"),
            ("Green", "#456A4A"),
            ("Gold", "#A4772E"),
            ("White", "#FFFFFF")
        ]:
            btn = QPushButton()
            btn.setToolTip(name)
            btn.setFixedSize(30, 26)
            # Use QPalette rather than a per-button stylesheet. This avoids
            # Qt stylesheet parser warnings and keeps the swatch reliable.
            pal = btn.palette()
            pal.setColor(btn.backgroundRole(), QColor(color))
            btn.setAutoFillBackground(True)
            btn.setPalette(pal)
            btn.setProperty("swatchColor", color)
            btn.clicked.connect(
                lambda checked=False, c=color: self.set_text_color(c)
            )
            palette_row.addWidget(btn)

        typo.addRow("Quick colors:", palette_row)
        control_layout.addWidget(typo_box)

        # ---------------- BACKGROUND ----------------
        bg_box = QGroupBox("Background — Live Preview")
        bg = QFormLayout(bg_box)

        bg_color = QPushButton("🎨 Background Color…")
        bg_color.clicked.connect(self.choose_background_color)
        bg.addRow(bg_color)

        self.bg_preview = QLabel("Background")
        self.bg_preview.setMinimumHeight(28)
        self.bg_preview.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        bg.addRow(self.bg_preview)

        bg_image = QPushButton("🖼 Background Image…")
        bg_image.clicked.connect(self.choose_background_image)
        bg.addRow(bg_image)

        self.transparency = QSlider(
            Qt.Orientation.Horizontal
        )
        self.transparency.setRange(0, 255)
        self.transparency.setValue(255)
        self.transparency.valueChanged.connect(
            self.update_background
        )
        bg.addRow("Opacity:", self.transparency)

        self.opacity_label = QLabel("100%")
        bg.addRow("Current:", self.opacity_label)

        remove_image = QPushButton("Remove Background Image")
        remove_image.clicked.connect(
            self.remove_background_image
        )
        bg.addRow(remove_image)

        self.canvas_size = QComboBox()
        self.canvas_size.addItems([
            "Portrait 900 × 1100",
            "Square 1080 × 1080",
            "Story 1080 × 1920",
            "Landscape 1200 × 800",
            "Letter 850 × 1100"
        ])
        self.canvas_size.currentTextChanged.connect(
            self.change_canvas_size
        )
        bg.addRow("Page size:", self.canvas_size)

        control_layout.addWidget(bg_box)

        # ---------------- PAGES ----------------
        page_box = QGroupBox("Pages")
        page_layout = QHBoxLayout(page_box)

        add_page = QPushButton("＋ Add Page")
        add_page.clicked.connect(self.add_page)
        page_layout.addWidget(add_page)

        remove_page = QPushButton("− Remove Page")
        remove_page.clicked.connect(self.remove_page)
        page_layout.addWidget(remove_page)

        self.page_label = QLabel("1 page")
        page_layout.addWidget(self.page_label)

        control_layout.addWidget(page_box)

        margin_box = QGroupBox("Document Margins")
        margin_layout = QFormLayout(margin_box)

        self.top_margin = QSpinBox()
        self.top_margin.setRange(20, 250)
        self.top_margin.setValue(self.canvas.margin_top)
        self.top_margin.setSuffix(" px")
        self.top_margin.valueChanged.connect(self.update_margins)
        margin_layout.addRow("Top:", self.top_margin)

        self.bottom_margin = QSpinBox()
        self.bottom_margin.setRange(20, 250)
        self.bottom_margin.setValue(self.canvas.margin_bottom)
        self.bottom_margin.setSuffix(" px")
        self.bottom_margin.valueChanged.connect(self.update_margins)
        margin_layout.addRow("Bottom:", self.bottom_margin)

        self.left_margin = QSpinBox()
        self.left_margin.setRange(20, 250)
        self.left_margin.setValue(self.canvas.margin_left)
        self.left_margin.setSuffix(" px")
        self.left_margin.valueChanged.connect(self.update_margins)
        margin_layout.addRow("Left:", self.left_margin)

        self.right_margin = QSpinBox()
        self.right_margin.setRange(20, 250)
        self.right_margin.setValue(self.canvas.margin_right)
        self.right_margin.setSuffix(" px")
        self.right_margin.valueChanged.connect(self.update_margins)
        margin_layout.addRow("Right:", self.right_margin)

        reflow_btn = QPushButton("↕ Reflow Body Text Across Pages")
        reflow_btn.clicked.connect(self.reflow_body_text)
        margin_layout.addRow(reflow_btn)

        control_layout.addWidget(margin_box)

        zoom_box = QGroupBox("Canvas View")
        zoom_layout = QHBoxLayout(zoom_box)

        fit_btn = QPushButton("Fit Width")
        fit_btn.clicked.connect(self.canvas._fit_width)
        zoom_layout.addWidget(fit_btn)

        zoom_layout.addWidget(
            QLabel("Ctrl + mouse wheel = zoom")
        )

        control_layout.addWidget(zoom_box)

        # ---------------- LAYERS ----------------
        layer_box = QGroupBox("Layer Arrangement")
        layers = QHBoxLayout(layer_box)

        front = QPushButton("Bring Front")
        front.clicked.connect(self.canvas.bring_front)
        layers.addWidget(front)

        back = QPushButton("Send Back")
        back.clicked.connect(self.canvas.send_back)
        layers.addWidget(back)

        control_layout.addWidget(layer_box)

        # ---------------- SAVE / SHARE ----------------
        save_box = QGroupBox("Save & Share")
        save_layout = QVBoxLayout(save_box)

        export_button = QPushButton("🖼 Export Complete Design PNG")
        export_button.clicked.connect(self.export_png)
        save_layout.addWidget(export_button)

        export_pages_button = QPushButton("🖼 Export Pages Separately")
        export_pages_button.clicked.connect(self.export_pages)
        save_layout.addWidget(export_pages_button)

        copy_button = QPushButton("📋 Copy PNG to Clipboard")
        copy_button.clicked.connect(self.copy_png)
        save_layout.addWidget(copy_button)

        save_button = QPushButton("💾 Save Design Project")
        save_button.clicked.connect(self.save_project)
        save_layout.addWidget(save_button)

        load_button = QPushButton("📂 Load Design Project")
        load_button.clicked.connect(self.load_project)
        save_layout.addWidget(load_button)

        clear_button = QPushButton("Clear All Text")
        clear_button.clicked.connect(self.canvas.clear_text)
        save_layout.addWidget(clear_button)

        control_layout.addWidget(save_box)
        control_layout.addStretch()

        # Scrollable controls.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(controls)

        self.canvas.scene.selectionChanged.connect(
            self.selection_changed
        )

        splitter.addWidget(scroll)
        splitter.addWidget(self.canvas)
        splitter.setSizes([410, 1150])

        self.setStyleSheet("""
            QWidget {
                font-size: 13px;
            }
            QGroupBox {
                font-weight: 600;
                border: 1px solid #D6CBD0;
                border-radius: 8px;
                margin-top: 9px;
                padding-top: 9px;
                background: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #694457;
            }
            QPushButton {
                min-height: 28px;
                border: 1px solid #D4C8CE;
                border-radius: 6px;
                padding: 3px 8px;
                background: #FAF8F9;
            }
            QPushButton:hover {
                background: #F2E7EC;
                border-color: #B88B9B;
            }
            QComboBox, QSpinBox, QLineEdit {
                min-height: 28px;
                border: 1px solid #D4C8CE;
                border-radius: 6px;
                padding: 2px 6px;
                background: white;
            }
            QPlainTextEdit {
                border: 1px solid #D4C8CE;
                border-radius: 6px;
                padding: 6px;
            }
            QScrollArea {
                background: transparent;
            }
        """)

    def _update_page_label(self):
        n = self.canvas.page_count
        self.page_label.setText(
            f"{n} page" if n == 1 else f"{n} pages"
        )

    def apply_theme(self, name):
        if self._updating_controls:
            return

        theme = THEMES.get(name)
        if not theme:
            return

        self.canvas.set_background_color(
            QColor(theme["background"])
        )
        self.canvas.set_background_opacity(
            self.transparency.value()
        )

        item = self.canvas.selected_text()
        if item:
            item.setDefaultTextColor(
                QColor(theme["text"])
            )
            font = item.font()
            font.setFamily(theme["font"])
            item.setFont(font)

        self._update_bg_preview()

    def _update_bg_preview(self):
        color = QColor(self.canvas.bg_color)
        color.setAlpha(self.canvas.bg_alpha)

        self.bg_preview.setStyleSheet(
            "background: %s; border: 1px solid #aaa; "
            "border-radius: 6px; color: #444;" %
            color.name(QColor.NameFormat.HexArgb)
        )
        self.bg_preview.setText(
            f"Background • {color.name(QColor.NameFormat.HexArgb)}"
        )

    def new_design(self, kind):
        self._updating_controls = True

        self.canvas.clear_text()
        self.canvas.page_count = 1

        theme_name = self.theme.currentText()
        theme = THEMES[theme_name]

        self.canvas.set_size(
            self.canvas.page_width,
            self.canvas.page_height
        )
        self.canvas.set_background_color(
            QColor(theme["background"])
        )
        self.canvas.set_background_opacity(255)

        self.transparency.setValue(255)
        self._updating_controls = False

        if kind == "Quote Card":
            text = (
                "“Some feelings are too beautiful "
                "to remain unspoken.”"
            )
            self.text_editor.setPlainText(text)
            item = self.canvas.add_text(
                text, "quote", QPointF(110, 360),
                theme["text"], theme["font"]
            )
            item.set_font_size(42)
            item.set_alignment(Qt.AlignmentFlag.AlignCenter)

        elif kind == "Love Letter":
            text = (
                "My Dear,\n\n"
                "There are thoughts I carry quietly, "
                "and somehow they always find their "
                "way back to you.\n\n"
                "With affection,\nJASS"
            )
            self.text_editor.setPlainText(text)
            item = self.canvas.add_text(
                text, "body", QPointF(105, 170),
                theme["text"], theme["font"]
            )
            item.set_font_size(25)

        elif kind == "Beautiful Page":
            text = (
                "A Beautiful Thought\n\n"
                "Words become memories when we "
                "give them a place to live."
            )
            self.text_editor.setPlainText(text)
            item = self.canvas.add_text(
                text, "body", QPointF(105, 240),
                theme["text"], theme["font"]
            )
            item.set_font_size(31)

        elif kind == "Poetry Card":
            text = (
                "Between one heartbeat\n"
                "and the next,\n"
                "there is a whole world\n"
                "of things left unsaid."
            )
            self.text_editor.setPlainText(text)
            item = self.canvas.add_text(
                text, "quote", QPointF(120, 300),
                theme["text"], theme["font"]
            )
            item.set_font_size(39)
            item.set_alignment(Qt.AlignmentFlag.AlignCenter)

        elif kind == "Romantic Note":
            text = (
                "For You\n\n"
                "Just a little note to say:\n"
                "some days become brighter\n"
                "because someone is in our thoughts."
            )
            self.text_editor.setPlainText(text)
            item = self.canvas.add_text(
                text, "body", QPointF(105, 250),
                theme["text"], theme["font"]
            )
            item.set_font_size(29)

        else:
            text = (
                "A thought worth sharing\n\n"
                "Keep the beautiful words.\n"
                "They may become someone's memory."
            )
            self.text_editor.setPlainText(text)
            item = self.canvas.add_text(
                text, "quote", QPointF(100, 480),
                theme["text"], theme["font"]
            )
            item.set_font_size(40)
            item.set_alignment(Qt.AlignmentFlag.AlignCenter)

        self._sync_controls_from_item(item)
        self._update_page_label()
        self.canvas.viewport().update()
        self._update_bg_preview()

    def add_quote(self):
        text = self.text_editor.toPlainText().strip()
        if not text:
            return

        theme = THEMES[self.theme.currentText()]
        item = self.canvas.add_text(
            text, "quote", QPointF(110, 250),
            theme["text"], theme["font"]
        )
        item.set_font_size(self.font_size.value())
        self._sync_controls_from_item(item)

    def add_body(self):
        text = self.text_editor.toPlainText().strip()
        if not text:
            return

        theme = THEMES[self.theme.currentText()]
        existing = [
            item for item in self.canvas.scene.items()
            if isinstance(item, DesignTextItem) and item.role == "body"
        ]

        # Treat body text like a document: additional body passages are
        # appended and the complete body is reflowed over the pages.
        if existing:
            existing.sort(key=lambda x: (x.sceneBoundingRect().top(), x.pos().x()))
            combined = "\n\n".join(
                [x.toPlainText().strip() for x in existing if x.toPlainText().strip()]
                + [text]
            )
            color = existing[0].defaultTextColor().name(QColor.NameFormat.HexArgb)
            family = existing[0].font().family()
            size = existing[0].font_size()
            for item in existing:
                self.canvas.scene.removeItem(item)
            items = self.canvas.add_flowed_body(
                combined, color=color, font_name=family, font_size=size, clear_existing=False
            )
        else:
            items = self.canvas.add_flowed_body(
                text,
                color=theme["text"],
                font_name=theme["font"],
                font_size=self.font_size.value(),
                clear_existing=False
            )

        if items:
            self._sync_controls_from_item(items[0])
            self._update_page_label()

    def reflow_body_text(self):
        items = self.canvas.reflow_body_items()
        if items:
            self._sync_controls_from_item(items[0])
            self._update_page_label()
            self.window().statusBar().showMessage(
                f"Body text reflowed across {self.canvas.page_count} page(s)."
            )
        else:
            QMessageBox.information(
                self, "No Body Text", "Add some body text first."
            )

    def update_margins(self):
        self.canvas.margin_top = self.top_margin.value()
        self.canvas.margin_bottom = self.bottom_margin.value()
        self.canvas.margin_left = self.left_margin.value()
        self.canvas.margin_right = self.right_margin.value()
        self.canvas.scene.update()
        self.canvas.viewport().update()

    def editor_text_changed(self):
        if self._updating_controls:
            return

        item = self.canvas.selected_text()
        if item:
            item.setPlainText(
                self.text_editor.toPlainText()
            )
            self.canvas.notify_item_changed(item)
            self.canvas.scene.update()

    def _sync_controls_from_item(self, item):
        if not item:
            return

        self._updating_controls = True

        self.text_editor.setPlainText(
            item.toPlainText()
        )
        self.font_size.setValue(
            item.font_size()
        )
        self.text_width.setValue(
            max(100, int(item.textWidth()))
        )
        self.scale.setValue(
            item.scale_percent()
        )
        self.font_family.setCurrentText(
            item.font().family()
        )

        alignment = item.alignment()
        if alignment == Qt.AlignmentFlag.AlignCenter:
            self.alignment.setCurrentText("Center")
        elif alignment == Qt.AlignmentFlag.AlignRight:
            self.alignment.setCurrentText("Right")
        else:
            self.alignment.setCurrentText("Left")

        self.bold.setChecked(
            item.font().bold()
        )
        self.italic.setChecked(
            item.font().italic()
        )

        color = QColor(item.defaultTextColor())
        self.text_color_preview.setStyleSheet(
            "background-color: %s; color: %s; border: 1px solid #999; "
            "border-radius: 5px;" % (
                color.name(),
                "white" if color.lightness() < 140 else "#333"
            )
        )
        self.text_color_preview.setText(
            f"{color.name(QColor.NameFormat.HexArgb)}"
        )

        self._updating_controls = False

    def selection_changed(self):
        item = self.canvas.selected_text()
        if item:
            self._sync_controls_from_item(item)

    def update_selected(self):
        if self._updating_controls:
            return

        item = self.canvas.selected_text()
        if not item:
            return

        item.set_font_size(
            self.font_size.value()
        )
        item.setTextWidth(
            self.text_width.value()
        )
        item.set_scale_percent(
            self.scale.value()
        )

        font = item.font()
        font.setFamily(
            self.font_family.currentText()
        )
        font.setBold(
            self.bold.isChecked()
        )
        font.setItalic(
            self.italic.isChecked()
        )
        item.setFont(font)

        align_name = self.alignment.currentText()

        if align_name == "Center":
            alignment = Qt.AlignmentFlag.AlignCenter
        elif align_name == "Right":
            alignment = Qt.AlignmentFlag.AlignRight
        else:
            alignment = Qt.AlignmentFlag.AlignLeft

        item.set_alignment(alignment)
        self.canvas.notify_item_changed(item)

    def set_text_color(self, color):
        item = self.canvas.selected_text()
        if not item:
            QMessageBox.information(
                self,
                "Select Text",
                "Click a text block on the canvas first."
            )
            return

        qcolor = QColor(color)
        if not qcolor.isValid():
            return

        # Re-select the item before applying the color so the operation is
        # deterministic even after the color button/dialog took focus.
        self.canvas.scene.clearSelection()
        item.setSelected(True)
        self.canvas._last_selected_text = item
        item.setDefaultTextColor(qcolor)
        item.update()
        item.document().markContentsDirty(0, item.document().characterCount())
        self.canvas.scene.update()
        self.canvas.viewport().update()
        self._sync_controls_from_item(item)

    def choose_text_color(self):
        item = self.canvas.selected_text()

        if not item:
            QMessageBox.information(
                self,
                "Select Text",
                "Click a text block on the canvas first."
            )
            return

        color = QColorDialog.getColor(
            item.defaultTextColor(),
            self,
            "Choose Text Color"
        )

        if color.isValid():
            self.set_text_color(color)

    def choose_background_color(self):
        color = QColorDialog.getColor(
            self.canvas.bg_color,
            self,
            "Choose Background Color"
        )

        if color.isValid():
            self.canvas.set_background_color(color)
            self._update_bg_preview()

    def choose_background_image(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Background Image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )

        if filename:
            if self.canvas.set_background_image(filename):
                self._update_bg_preview()

    def remove_background_image(self):
        self.canvas.clear_background_image()
        self._update_bg_preview()

    def update_background(self, value):
        self.canvas.set_background_opacity(value)

        self.opacity_label.setText(
            f"{round(value / 255 * 100)}%"
        )

        self._update_bg_preview()

    def change_canvas_size(self, text):
        match = re.search(
            r"(\d+)\s*[×x]\s*(\d+)",
            text
        )

        if match:
            self.canvas.set_size(
                int(match.group(1)),
                int(match.group(2))
            )
            self._update_page_label()

    def add_page(self):
        n = self.canvas.add_page()
        self._update_page_label()

        self.window().statusBar().showMessage(
            f"Added page {n}. Scroll down to continue."
        )

    def remove_page(self):
        if self.canvas.remove_last_page():
            self._update_page_label()
        else:
            QMessageBox.information(
                self,
                "Page Not Removed",
                "The last page contains text, so it was kept."
            )

    def export_png(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Complete Design",
            "JASS_literary_design.png",
            "PNG Images (*.png)"
        )

        if filename:
            if self.canvas.export_png(filename):
                self.window().statusBar().showMessage(
                    f"Exported complete design: {filename}"
                )

    def export_pages(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder for Page Images"
        )

        if folder:
            files = self.canvas.export_pages(folder)

            self.window().statusBar().showMessage(
                f"Exported {len(files)} page image(s)."
            )

            QMessageBox.information(
                self,
                "Pages Exported",
                f"Exported {len(files)} page image(s) to:\n{folder}"
            )

    def copy_png(self):
        temp = Path.cwd() / "_jass_design_clipboard.png"

        if self.canvas.export_png(str(temp)):
            QApplication.clipboard().setPixmap(
                QPixmap(str(temp))
            )

            try:
                temp.unlink()
            except OSError:
                pass

            self.window().statusBar().showMessage(
                "Complete design copied to clipboard."
            )

    def save_project(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save JASS Design",
            "JASS_literary_design.jassdesign",
            "JASS Design (*.jassdesign);;JSON (*.json)"
        )

        if filename:
            Path(filename).write_text(
                json.dumps(
                    self.canvas.project_data(),
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf-8"
            )

            self.window().statusBar().showMessage(
                f"Saved: {filename}"
            )

    def load_project(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load JASS Design",
            "",
            "JASS Design (*.jassdesign *.json)"
        )

        if not filename:
            return

        try:
            data = json.loads(
                Path(filename).read_text(
                    encoding="utf-8"
                )
            )

            self.canvas.load_project(data)

            self._updating_controls = True
            self.transparency.setValue(
                self.canvas.bg_alpha
            )
            self.top_margin.setValue(self.canvas.margin_top)
            self.bottom_margin.setValue(self.canvas.margin_bottom)
            self.left_margin.setValue(self.canvas.margin_left)
            self.right_margin.setValue(self.canvas.margin_right)
            self._updating_controls = False

            self._update_bg_preview()
            self._update_page_label()

            item = self.canvas.selected_text()
            if item:
                self._sync_controls_from_item(item)

            self.window().statusBar().showMessage(
                f"Loaded: {filename}"
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Load Error",
                str(exc)
            )


# ----------------------------------------------------------------------
# LIBRARY & READER
# ----------------------------------------------------------------------

class LibraryReader(QWidget):
    def __init__(self):
        super().__init__()

        self.settings = QSettings(
            "JASS",
            "EnglishLoveLiteratureExplorer"
        )

        self.folder = Path(
            self.settings.value(
                "folder",
                str(DEFAULT_FOLDER)
            )
        )

        self.books = []
        self.filtered_books = []
        self.current_path = None
        self.sections = []
        self.section_index = 0

        self.favorites = set(
            self.settings.value(
                "favorites",
                [],
                type=list
            )
        )

        self.build_ui()
        self.load_books()

    def build_ui(self):
        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search title, author or filename..."
        )
        self.search.textChanged.connect(
            self.filter_books
        )
        toolbar.addWidget(self.search, 3)

        self.category = QComboBox()
        self.category.addItems([
            "All categories",
            "Love / Romance",
            "Romance / Courtship",
            "Sensual / Erotic Literature",
            "Fiction / Related",
            "★ Favorites"
        ])
        self.category.currentTextChanged.connect(
            self.filter_books
        )
        toolbar.addWidget(self.category)

        folder_button = QPushButton("Choose Folder")
        folder_button.clicked.connect(
            self.choose_folder
        )
        toolbar.addWidget(folder_button)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(
            self.load_books
        )
        toolbar.addWidget(refresh)

        root.addLayout(toolbar)

        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        left = QWidget()
        left_layout = QVBoxLayout(left)

        self.book_list = QListWidget()
        self.book_list.currentItemChanged.connect(
            self.book_selected
        )
        left_layout.addWidget(self.book_list)

        self.count_label = QLabel()
        left_layout.addWidget(self.count_label)

        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.title_label = QLabel(
            "Select a book"
        )
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            "font-size: 22px; font-weight: bold;"
        )
        right_layout.addWidget(self.title_label)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        right_layout.addWidget(self.info_label)

        self.reader = QTextBrowser()
        self.reader.setFont(
            QFont("Georgia", 13)
        )
        right_layout.addWidget(
            self.reader,
            1
        )

        bottom = QHBoxLayout()

        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText(
            "Find in current book..."
        )
        self.find_box.returnPressed.connect(
            self.find_text
        )
        bottom.addWidget(self.find_box)

        previous = QPushButton("◀ Section")
        previous.clicked.connect(
            self.previous_section
        )
        bottom.addWidget(previous)

        next_button = QPushButton("Section ▶")
        next_button.clicked.connect(
            self.next_section
        )
        bottom.addWidget(next_button)

        self.favorite_button = QPushButton(
            "☆ Favorite"
        )
        self.favorite_button.clicked.connect(
            self.toggle_favorite
        )
        bottom.addWidget(
            self.favorite_button
        )

        right_layout.addLayout(bottom)

        splitter.addWidget(right)
        splitter.setSizes([430, 1050])

        root.addWidget(
            splitter,
            1
        )

    def load_books(self):
        self.folder.mkdir(
            parents=True,
            exist_ok=True
        )

        self.books = sorted(
            self.folder.rglob("*.epub"),
            key=lambda p: p.name.lower()
        )

        self.filter_books()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose EPUB Library",
            str(self.folder)
        )

        if folder:
            self.folder = Path(folder)
            self.settings.setValue(
                "folder",
                str(self.folder)
            )
            self.load_books()

    def filter_books(self):
        query = self.search.text().lower().strip()
        selected_category = (
            self.category.currentText()
        )

        self.filtered_books = []

        for path in self.books:
            category = category_for(path)

            if (
                selected_category == "★ Favorites"
                and str(path) not in self.favorites
            ):
                continue

            if (
                selected_category not in (
                    "All categories",
                    "★ Favorites"
                )
                and category != selected_category
            ):
                continue

            searchable = (
                title_from_path(path)
                + " "
                + author_from_path(path)
                + " "
                + path.name
            ).lower()

            if query and query not in searchable:
                continue

            self.filtered_books.append(path)

        self.book_list.blockSignals(True)
        self.book_list.clear()

        for path in self.filtered_books:
            label = title_from_path(path)

            if str(path) in self.favorites:
                label = "★ " + label

            item = QListWidgetItem(label)
            item.setData(
                Qt.ItemDataRole.UserRole,
                str(path)
            )
            item.setToolTip(str(path))
            self.book_list.addItem(item)

        self.book_list.blockSignals(False)

        self.count_label.setText(
            f"{len(self.filtered_books)} shown / "
            f"{len(self.books)} EPUBs"
        )

        if self.filtered_books:
            self.book_list.setCurrentRow(0)

    def book_selected(self, current, previous):
        if not current:
            return

        path = Path(
            current.data(
                Qt.ItemDataRole.UserRole
            )
        )

        self.current_path = path

        self.title_label.setText(
            title_from_path(path)
        )

        self.info_label.setText(
            f"Author: {author_from_path(path)}  •  "
            f"Category: {category_for(path)}"
        )

        self.favorite_button.setText(
            "★ Favorite"
            if str(path) in self.favorites
            else "☆ Favorite"
        )

        try:
            self.sections = read_epub(path)
            self.section_index = 0

            full_text = "\n\n".join(
                text
                for _, text in self.sections
            )

            self.reader.setPlainText(
                full_text or
                "No readable EPUB text found."
            )

        except Exception as exc:
            self.reader.setPlainText(
                f"Could not open EPUB:\n{exc}"
            )

    def previous_section(self):
        if not self.sections:
            return

        self.section_index = max(
            0,
            self.section_index - 1
        )

        self.reader.setPlainText(
            self.sections[
                self.section_index
            ][1]
        )

    def next_section(self):
        if not self.sections:
            return

        self.section_index = min(
            len(self.sections) - 1,
            self.section_index + 1
        )

        self.reader.setPlainText(
            self.sections[
                self.section_index
            ][1]
        )

    def find_text(self):
        query = self.find_box.text()

        if not query:
            return

        if not self.reader.find(query):
            cursor = self.reader.textCursor()
            cursor.movePosition(
                cursor.MoveOperation.Start
            )
            self.reader.setTextCursor(cursor)
            self.reader.find(query)

    def toggle_favorite(self):
        if not self.current_path:
            return

        path = str(self.current_path)

        if path in self.favorites:
            self.favorites.remove(path)
        else:
            self.favorites.add(path)

        self.settings.setValue(
            "favorites",
            list(self.favorites)
        )

        self.favorite_button.setText(
            "★ Favorite"
            if path in self.favorites
            else "☆ Favorite"
        )

        self.filter_books()


# ----------------------------------------------------------------------
# MAIN WINDOW
# ----------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            APP_NAME + " v2.1 Creative Studio — Fixed"
        )
        self.resize(1550, 950)

        self.setStatusBar(
            self.statusBar()
        )

        tabs = QTabWidget()

        self.library = LibraryReader()
        self.creative = CreativeStudio()

        tabs.addTab(
            self.library,
            "📚 Library & Reader"
        )
        tabs.addTab(
            self.creative,
            "✨ Creative Studio"
        )

        self.setCentralWidget(tabs)

        help_menu = self.menuBar().addMenu(
            "&Help"
        )

        about = QAction(
            "About",
            self
        )
        about.triggered.connect(
            self.show_about
        )
        help_menu.addAction(about)

    def show_about(self):
        QMessageBox.information(
            self,
            "About",
            "JASS English Love Literature Explorer "
            "v2.1\n\n"
            "v2.0 Library & Reader baseline + "
            "Creative Studio.\n\n"
            "Explore literature, capture ideas, "
            "and create beautiful shareable "
            "literary designs locally."
        )


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("JASS")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
