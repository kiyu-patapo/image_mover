"""
image_sorter.py  v3
────────────────────
左クリックで画像を選択 → 「移動開始」で一括移動するツール

改善点 (v3):
  - サムネイルサイズを全て2倍に変更 (S:320 / M:480 / L:720)
  - 操作フローを2段階に変更
      1. 「選択開始」→ 画像をクリックして選択/解除
      2. 「移動開始」→ 選択した画像を一括で対象フォルダへ移動
  - 誤操作防止: 選択モード外ではクリックしても移動しない

依存: PyQt6  (pip install PyQt6)
"""

import sys
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui  import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog,
    QScrollArea, QFrame, QMessageBox, QProgressBar,
    QStatusBar, QButtonGroup,
)

# ──────────────────────────────────────────────────────
THUMBNAIL_SIZES  = {"S": 320, "M": 480, "L": 720}   # v3: 全て2倍
DEFAULT_SIZE_KEY = "M"
THUMBNAIL_MARGIN = 8
SUPPORTED_EXT    = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
# ──────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════
#  D&D 対応 QLineEdit
# ══════════════════════════════════════════════════════
class DropLineEdit(QLineEdit):
    """フォルダをドロップするとパスを自動入力する QLineEdit"""

    def __init__(self, placeholder: str = ""):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText(placeholder)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile() for u in urls):
                event.acceptProposedAction()
                self.setStyleSheet(
                    "QLineEdit { background:#2a2a50; border:1px solid #88aaff;"
                    " border-radius:3px; padding:3px 6px; color:#ddd; }")
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setStyleSheet("")
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.setText(path)
                event.acceptProposedAction()
                return
        event.ignore()


# ══════════════════════════════════════════════════════
#  バックグラウンド サムネイル ローダー
# ══════════════════════════════════════════════════════
class ThumbnailLoader(QThread):
    loaded   = pyqtSignal(int, QPixmap)
    finished = pyqtSignal()

    def __init__(self, paths: list, size: int):
        super().__init__()
        self.paths = paths
        self.size  = size
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for i, p in enumerate(self.paths):
            if self._stop:
                break
            px = QPixmap(str(p))
            if not px.isNull():
                px = px.scaled(
                    self.size, self.size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self.loaded.emit(i, px)
        self.finished.emit()


# ══════════════════════════════════════════════════════
#  画像カード  （normal / selected / moved の3状態）
# ══════════════════════════════════════════════════════
class ImageCard(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, path: Path, index: int, thumb_size: int):
        super().__init__()
        self.path       = path
        self.index      = index
        self.moved      = False
        self.selected   = False          # v3: 選択状態
        self.thumb_size = thumb_size

        self.setFixedSize(thumb_size + 16, thumb_size + 32)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 2)
        lay.setSpacing(2)

        self.img_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.img_label.setFixedSize(thumb_size, thumb_size)
        self.img_label.setText("…")
        lay.addWidget(self.img_label)

        name_lbl = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        name_lbl.setFixedWidth(thumb_size)
        font_px = max(7, thumb_size // 20)
        name_lbl.setStyleSheet(f"font-size: {font_px}px;")
        fm = name_lbl.fontMetrics()
        name_lbl.setText(fm.elidedText(path.name, Qt.TextElideMode.ElideRight, thumb_size))
        lay.addWidget(name_lbl)

    def set_pixmap(self, px: QPixmap):
        self.img_label.setPixmap(px) if not px.isNull() else self.img_label.setText("?")

    def toggle_select(self):
        """選択状態をトグル"""
        self.selected = not self.selected
        self._apply_style()

    def mark_moved(self):
        self.moved    = True
        self.selected = False
        self.setEnabled(False)
        self._apply_style()

    def _apply_style(self):
        if self.moved:
            self.setStyleSheet(
                "ImageCard { background:#1a3a1a; border:1px solid #336633; border-radius:4px; }")
        elif self.selected:
            # 選択中: 青い強調枠
            self.setStyleSheet(
                "ImageCard { background:#1a2a50; border:3px solid #4488ff; border-radius:4px; }")
        else:
            self.setStyleSheet("""
                ImageCard { background:#2b2b2b; border:1px solid #555; border-radius:4px; }
                ImageCard:hover { border:1px solid #88aaff; background:#333355; }
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.moved:
            self.clicked.emit(self)


# ══════════════════════════════════════════════════════
#  メインウィンドウ
# ══════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("画像移動まし～ん")
        self.resize(960, 700)
        self._set_dark_theme()

        self.src_dir        = None
        self.dst_dir        = None
        self.cards          = []
        self.selecting      = False      # v3: 選択モードフラグ
        self._moved_count   = 0
        self._selected_count = 0
        self._loader        = None
        self._thumb_size    = THUMBNAIL_SIZES[DEFAULT_SIZE_KEY]

        self._build_ui()

    # ──────────────────────────────────────────
    #  UI 構築
    # ──────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vlay = QVBoxLayout(root)
        vlay.setSpacing(6)
        vlay.setContentsMargins(8, 8, 8, 8)

        vlay.addWidget(self._folder_row("移動元フォルダ:", "src"))
        vlay.addWidget(self._folder_row("移動先フォルダ:", "dst"))

        # 操作ボタン行
        btn_row = QHBoxLayout()

        self.load_btn   = QPushButton("📂  画像を読み込む")
        self.select_btn = QPushButton("☑  選択開始")      # v3: 旧「移動開始」
        self.move_btn   = QPushButton("📦  移動開始")      # v3: 新設
        self.select_btn.setEnabled(False)
        self.move_btn.setEnabled(False)

        self.load_btn.clicked.connect(self._load_images)
        self.select_btn.clicked.connect(self._toggle_select_mode)
        self.move_btn.clicked.connect(self._execute_move)

        for b in (self.load_btn, self.select_btn, self.move_btn):
            b.setFixedHeight(32)

        btn_row.addWidget(self.load_btn)
        btn_row.addWidget(self.select_btn)
        btn_row.addWidget(self.move_btn)

        # サイズ切替ボタン (S / M / L)
        btn_row.addSpacing(16)
        size_lbl = QLabel("サイズ:")
        size_lbl.setFixedWidth(44)
        btn_row.addWidget(size_lbl)
        self._size_btn_group = QButtonGroup(self)
        for key in ("S", "M", "L"):
            b = QPushButton(key)
            b.setFixedSize(34, 28)
            b.setCheckable(True)
            b.setChecked(key == DEFAULT_SIZE_KEY)
            b.clicked.connect(lambda _, k=key: self._change_thumb_size(k))
            self._size_btn_group.addButton(b)
            btn_row.addWidget(b)

        btn_row.addStretch()
        self.counter_label = QLabel("画像: 0 枚 / 選択: 0 枚 / 移動済: 0 枚")
        btn_row.addWidget(self.counter_label)
        vlay.addLayout(btn_row)

        # プログレスバー
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        vlay.addWidget(self.progress)

        # サムネイルグリッド
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(THUMBNAIL_MARGIN)
        self.grid_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.grid_widget)
        vlay.addWidget(scroll, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(
            "移動元・移動先フォルダを選択（またはドロップ）して「画像を読み込む」を押してください")

    def _folder_row(self, label_text: str, tag: str) -> QWidget:
        w   = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label_text)
        lbl.setFixedWidth(120)

        edit = DropLineEdit("フォルダをここにドロップ、またはパスを入力 / 右のボタンで選択")
        btn  = QPushButton("参照…")
        btn.setFixedWidth(70)

        if tag == "src":
            self.src_edit = edit
            btn.clicked.connect(self._browse_src)
        else:
            self.dst_edit = edit
            btn.clicked.connect(self._browse_dst)

        lay.addWidget(lbl)
        lay.addWidget(edit)
        lay.addWidget(btn)
        return w

    # ──────────────────────────────────────────
    #  フォルダ参照
    # ──────────────────────────────────────────
    def _browse_src(self):
        d = QFileDialog.getExistingDirectory(self, "移動元フォルダを選択")
        if d:
            self.src_edit.setText(d)

    def _browse_dst(self):
        d = QFileDialog.getExistingDirectory(self, "移動先フォルダを選択")
        if d:
            self.dst_edit.setText(d)

    # ──────────────────────────────────────────
    #  サムネイルサイズ切替
    # ──────────────────────────────────────────
    def _change_thumb_size(self, key: str):
        new_size = THUMBNAIL_SIZES[key]
        if new_size == self._thumb_size:
            return
        self._thumb_size = new_size
        if self.cards:
            self._reload_grid()

    def _reload_grid(self):
        if self._loader and self._loader.isRunning():
            self._loader.stop()
            self._loader.wait()

        paths        = [c.path  for c in self.cards]
        moved_set    = {c.index for c in self.cards if c.moved}
        selected_set = {c.index for c in self.cards if c.selected}

        for card in self.cards:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()

        ts   = self._thumb_size
        cols = self._calc_cols(ts)
        for i, p in enumerate(paths):
            card = ImageCard(p, i, ts)
            card.clicked.connect(self._on_card_clicked)
            if i in moved_set:
                card.mark_moved()
            elif i in selected_set:
                card.selected = True
                card._apply_style()
            self.cards.append(card)
            self.grid_layout.addWidget(card, i // cols, i % cols)

        self.progress.setMaximum(len(paths))
        self.progress.setValue(0)
        self.progress.show()

        self._loader = ThumbnailLoader(paths, ts)
        self._loader.loaded.connect(self._on_thumbnail_loaded)
        self._loader.finished.connect(self._on_load_finished)
        self._loader.start()

    # ──────────────────────────────────────────
    #  画像読み込み
    # ──────────────────────────────────────────
    def _load_images(self):
        src_text = self.src_edit.text().strip()
        dst_text = self.dst_edit.text().strip()

        if not src_text:
            QMessageBox.warning(self, "エラー", "移動元フォルダを指定してください"); return
        if not dst_text:
            QMessageBox.warning(self, "エラー", "移動先フォルダを指定してください"); return

        src = Path(src_text)
        dst = Path(dst_text)

        if not src.is_dir():
            QMessageBox.warning(self, "エラー", f"移動元フォルダが見つかりません:\n{src}"); return
        dst.mkdir(parents=True, exist_ok=True)

        self.src_dir = src
        self.dst_dir = dst

        if self._loader and self._loader.isRunning():
            self._loader.stop()
            self._loader.wait()

        self._clear_grid()
        self.selecting = False
        self.select_btn.setText("☑  選択開始")
        self.move_btn.setEnabled(False)

        paths = sorted([p for p in src.iterdir() if p.suffix.lower() in SUPPORTED_EXT])
        if not paths:
            QMessageBox.information(self, "情報", "対応画像が見つかりませんでした"); return

        ts   = self._thumb_size
        cols = self._calc_cols(ts)
        for i, p in enumerate(paths):
            card = ImageCard(p, i, ts)
            card.clicked.connect(self._on_card_clicked)
            self.cards.append(card)
            self.grid_layout.addWidget(card, i // cols, i % cols)

        self._update_counter()
        self.select_btn.setEnabled(True)

        self.progress.setMaximum(len(paths))
        self.progress.setValue(0)
        self.progress.show()

        self._loader = ThumbnailLoader(paths, ts)
        self._loader.loaded.connect(self._on_thumbnail_loaded)
        self._loader.finished.connect(self._on_load_finished)
        self._loader.start()

        self.status.showMessage(f"{len(paths)} 枚の画像を読み込み中…")

    def _calc_cols(self, thumb_size: int) -> int:
        card_w = thumb_size + 16 + THUMBNAIL_MARGIN
        return max(2, (self.grid_widget.width() or 960) // card_w)

    def _on_thumbnail_loaded(self, index: int, px: QPixmap):
        if index < len(self.cards):
            self.cards[index].set_pixmap(px)
            self.progress.setValue(index + 1)

    def _on_load_finished(self):
        self.progress.hide()
        self.status.showMessage(
            "読み込み完了。「選択開始」を押してから画像をクリックして選択 → 「移動開始」で一括移動")

    def _clear_grid(self):
        for card in self.cards:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self._moved_count    = 0
        self._selected_count = 0

    # ──────────────────────────────────────────
    #  選択モード ON / OFF  (旧: _toggle_active)
    # ──────────────────────────────────────────
    def _toggle_select_mode(self):
        self.selecting = not self.selecting
        if self.selecting:
            self.select_btn.setText("⏹  選択停止")
            self.status.showMessage(
                "✅ 選択モード ON — クリックで選択/解除。選択後に「移動開始」を押してください")
        else:
            self.select_btn.setText("☑  選択開始")
            self.status.showMessage("選択モード OFF")

    # ──────────────────────────────────────────
    #  カードクリック → 選択トグル  (v3)
    # ──────────────────────────────────────────
    def _on_card_clicked(self, card: ImageCard):
        if not self.selecting:
            self.status.showMessage(
                "「選択開始」を押してから画像をクリックして選択してください")
            return

        card.toggle_select()
        self._selected_count = sum(1 for c in self.cards if c.selected)
        self._update_counter()

        # 1枚でも選択されていれば「移動開始」を有効化
        self.move_btn.setEnabled(self._selected_count > 0)

        action = "選択" if card.selected else "解除"
        self.status.showMessage(
            f"{action}: {card.path.name}  （選択中: {self._selected_count} 枚）")

    # ──────────────────────────────────────────
    #  移動実行  (v3: 新設)
    # ──────────────────────────────────────────
    def _execute_move(self):
        selected_cards = [c for c in self.cards if c.selected and not c.moved]
        if not selected_cards:
            self.status.showMessage("移動する画像が選択されていません")
            return

        moved = 0
        errors = []
        for card in selected_cards:
            src_path = card.path
            dst_path = self.dst_dir / src_path.name

            # 重複ファイル名の処理
            if dst_path.exists():
                stem, suffix = src_path.stem, src_path.suffix
                n = 1
                while dst_path.exists():
                    dst_path = self.dst_dir / f"{stem}_{n}{suffix}"
                    n += 1

            try:
                shutil.move(str(src_path), str(dst_path))
                card.mark_moved()
                self._moved_count    += 1
                self._selected_count -= 1
                moved += 1
            except Exception as e:
                errors.append(f"{src_path.name}: {e}")

        self._update_counter()
        self.move_btn.setEnabled(self._selected_count > 0)

        if errors:
            QMessageBox.critical(self, "移動エラー", "\n".join(errors))
        else:
            self.status.showMessage(
                f"✅ {moved} 枚を [{self.dst_dir}] へ移動しました")

    def _update_counter(self):
        self.counter_label.setText(
            f"画像: {len(self.cards)} 枚 / 選択: {self._selected_count} 枚 / 移動済: {self._moved_count} 枚")

    # ──────────────────────────────────────────
    #  ダークテーマ
    # ──────────────────────────────────────────
    def _set_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color:#1e1e1e; color:#dddddd; }
            QLineEdit {
                background:#2b2b2b; border:1px solid #555;
                border-radius:3px; padding:3px 6px; color:#ddd;
            }
            QPushButton {
                background:#3a3a5c; border:1px solid #5555aa;
                border-radius:4px; padding:4px 12px; color:#cceeff;
            }
            QPushButton:hover    { background:#4a4a7c; }
            QPushButton:pressed  { background:#2a2a4c; }
            QPushButton:checked  { background:#2255cc; border-color:#4477ff; color:#ffffff; }
            QPushButton:disabled { background:#2a2a2a; color:#666; border-color:#444; }
            QScrollArea  { background:#1e1e1e; }
            QProgressBar { background:#333; border:none; border-radius:3px; }
            QProgressBar::chunk { background:#5577ff; border-radius:3px; }
            QStatusBar   { background:#161616; color:#aaa; font-size:11px; }
            QLabel        { color:#dddddd; }
        """)


# ══════════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
