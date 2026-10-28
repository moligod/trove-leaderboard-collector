from __future__ import annotations

import ctypes
import hashlib
import json
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import calendar
import time
from ctypes import wintypes
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import collector_core as core


POLL_MS = 5
IMPORT_RESULT_POLL_MS = 100
UPLOAD_RESULT_POLL_MS = 200
KEEPALIVE_INTERVAL_MS = 60_000
UPLOAD_FILTER_LABELS = {
    "latest_complete": "最新完整",
    "not_uploaded": "未上传",
    "pending": "待上传",
    "failed": "失败",
    "uploaded": "已上传",
    "all": "全部",
}
UPLOAD_FILTER_BY_LABEL = {label: key for key, label in UPLOAD_FILTER_LABELS.items()}
VK_R = 0x52
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MAPVK_VK_TO_VSC = 0
GA_ROOT = 2

USER32 = ctypes.windll.user32 if sys.platform == "win32" else None


class NoUploadRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the collector token to a redirect target."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class CapturedCfg:
    path: str
    raw: bytes
    signature: str
    mtime_ns: int | None


@dataclass(frozen=True)
class ImportWorkerResult:
    summary: core.ImportSummary | None
    signature: str
    mtime_ns: int | None
    error: str | None = None


@dataclass(frozen=True)
class UploadWorkerResult:
    snapshot_id: int
    ok: bool
    status_code: int | None
    message: str


if USER32 is not None:
    USER32.WindowFromPoint.argtypes = (wintypes.POINT,)
    USER32.WindowFromPoint.restype = wintypes.HWND
    USER32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    USER32.GetAncestor.restype = wintypes.HWND
    USER32.IsWindow.argtypes = (wintypes.HWND,)
    USER32.IsWindow.restype = wintypes.BOOL
    USER32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    USER32.GetWindowTextLengthW.restype = ctypes.c_int
    USER32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    USER32.GetWindowTextW.restype = ctypes.c_int
    USER32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    USER32.GetClassNameW.restype = ctypes.c_int
    USER32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    USER32.MapVirtualKeyW.restype = wintypes.UINT
    USER32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    USER32.PostMessageW.restype = wintypes.BOOL


class CollectorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Trove 排行榜采集器")
        self.geometry("1180x720")
        self.minsize(980, 620)

        self.cfg_path = tk.StringVar(value=str(core.DEFAULT_CFG_PATH))
        self.status = tk.StringVar(value="就绪")
        self.auto_refresh = tk.BooleanVar(value=True)
        self.selected_snapshot_id: int | None = None
        self.selected_leaderboard_id: str | None = None
        self.last_cfg_mtime_ns: int | None = None
        self.last_cfg_signature: str | None = None
        self.cfg_state_lock = threading.Lock()
        self.cfg_path_value = self.cfg_path.get()
        self.auto_refresh_value = bool(self.auto_refresh.get())
        self.import_queue: queue.Queue[CapturedCfg | None] = queue.Queue()
        self.import_result_queue: queue.Queue[ImportWorkerResult] = queue.Queue()
        self.upload_result_queue: queue.Queue[UploadWorkerResult] = queue.Queue()
        self.worker_stop = threading.Event()
        self.capture_thread: threading.Thread | None = None
        self.import_thread: threading.Thread | None = None
        self.upload_thread: threading.Thread | None = None
        self.upload_window: tk.Toplevel | None = None
        self.upload_url = tk.StringVar()
        self.collector_token = tk.StringVar()
        self.upload_status_filter = tk.StringVar(value=UPLOAD_FILTER_LABELS["latest_complete"])
        self.upload_date_filter = tk.StringVar(value="")
        self.upload_date_start: date | None = None
        self.upload_date_end: date | None = None
        self.upload_calendar_window: tk.Toplevel | None = None
        self.upload_calendar_month: date | None = None
        self.upload_calendar_pending_start: date | None = None
        self.upload_tree: ttk.Treeview | None = None
        self.upload_drag_anchor_iid: str | None = None
        self.upload_status = tk.StringVar(value="")
        self.icon_images: dict[str, tk.PhotoImage] = {}
        self.keepalive_hwnd: int | None = None
        self.keepalive_active = False
        self.keepalive_job: str | None = None
        self.keepalive_target = tk.StringVar(value="未锁定窗口")
        self.keepalive_status = tk.StringVar(value="挂机未启动")

        self.conn = core.init_db(core.DEFAULT_DB_PATH)
        self.upload_url.set(core.get_upload_url(self.conn))
        self.collector_token.set(core.get_collector_token(self.conn))
        self.cfg_path.trace_add("write", self.on_cfg_path_changed)
        self.auto_refresh.trace_add("write", self.on_auto_refresh_changed)
        self._build_ui()
        self.refresh_all()
        self.start_background_import()
        self.after(IMPORT_RESULT_POLL_MS, self.process_import_results)
        self.after(UPLOAD_RESULT_POLL_MS, self.process_upload_results)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(10, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Button(top, text="上传数据", command=self.open_upload_window).grid(row=0, column=9, padx=(6, 0))

        ttk.Label(top, text="配置文件").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.cfg_path).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(top, text="选择", command=self.choose_cfg).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="刷新", command=self.refresh_all).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(top, text="导入目录", command=self.import_catalog_only).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(top, text="导出 CSV", command=self.export_selected).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(top, text="清空选中", command=self.clear_selected_leaderboard).grid(row=0, column=6, padx=(0, 6))
        ttk.Button(top, text="清空全部数据", command=self.clear_all_collected_data).grid(row=0, column=7, padx=(0, 6))
        ttk.Button(top, text="打开目录", command=self.open_collector_folder).grid(row=0, column=8)

        ttk.Checkbutton(top, text="自动导入配置文件变化", variable=self.auto_refresh).grid(
            row=1, column=1, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            top,
            text="@paiming 生成ID列表；@data 自动续查；@onedata 只采当前榜；RANGE 输入 id-start-end；@qingkong 清空进度。",
            foreground="#555555",
        ).grid(row=1, column=3, columnspan=3, sticky="e", pady=(8, 0))

        keepalive = ttk.Frame(top)
        keepalive.grid(row=2, column=1, columnspan=6, sticky="ew", pady=(8, 0))
        keepalive.columnconfigure(2, weight=1)
        ttk.Label(keepalive, text="挂机窗口").grid(row=0, column=0, sticky="w")
        self.keepalive_drag_icon = tk.Label(
            keepalive,
            text="◎",
            width=3,
            relief="groove",
            borderwidth=2,
            cursor="crosshair",
            font=("Segoe UI", 12, "bold"),
        )
        self.keepalive_drag_icon.grid(row=0, column=1, padx=(8, 6))
        self.keepalive_drag_icon.bind("<ButtonPress-1>", self.begin_keepalive_drag)
        self.keepalive_drag_icon.bind("<ButtonRelease-1>", self.lock_keepalive_window)
        ttk.Label(keepalive, textvariable=self.keepalive_target).grid(row=0, column=2, sticky="w")
        self.keepalive_button = ttk.Button(keepalive, text="开始挂机", command=self.toggle_keepalive)
        self.keepalive_button.grid(row=0, column=3, padx=(8, 6))
        ttk.Label(keepalive, textvariable=self.keepalive_status, foreground="#555555").grid(
            row=0, column=4, sticky="e"
        )

        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        left = ttk.Frame(pane)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        pane.add(left, weight=2)

        self.board_tree = ttk.Treeview(
            left,
            columns=("id", "entries", "expected", "complete", "saved"),
            show="tree headings",
            selectmode="browse",
        )
        headings = {
            "id": ("ID", 74),
            "entries": ("行数", 70),
            "expected": ("应有", 80),
            "complete": ("完成", 60),
            "saved": ("保存时间", 145),
        }
        self.board_tree.heading("#0", text="分类 / 排行榜")
        self.board_tree.column("#0", width=320, anchor="w", stretch=True)
        for column, (label, width) in headings.items():
            self.board_tree.heading(column, text=label)
            self.board_tree.column(column, width=width, anchor="w", stretch=False)
        self.board_tree.grid(row=0, column=0, sticky="nsew")
        self.board_tree.bind("<<TreeviewSelect>>", self.on_board_selected)
        board_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.board_tree.yview)
        self.board_tree.configure(yscrollcommand=board_scroll.set)
        board_scroll.grid(row=0, column=1, sticky="ns")

        right = ttk.Frame(pane)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=4)
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)
        pane.add(right, weight=3)

        self.snapshot_tree = ttk.Treeview(
            right,
            columns=("time", "range", "entries", "expected", "complete", "imported"),
            show="headings",
            height=7,
            selectmode="browse",
        )
        snapshot_headings = {
            "time": ("采集时间", 150),
            "range": ("范围", 110),
            "entries": ("行数", 70),
            "expected": ("应有", 80),
            "complete": ("完成", 60),
            "imported": ("导入时间", 150),
        }
        for column, (label, width) in snapshot_headings.items():
            self.snapshot_tree.heading(column, text=label)
            self.snapshot_tree.column(column, width=width, anchor="w", stretch=column in {"time", "imported"})
        self.snapshot_tree.grid(row=0, column=0, sticky="nsew")
        self.snapshot_tree.bind("<<TreeviewSelect>>", self.on_snapshot_selected)
        self.snapshot_tree.bind("<Button-3>", self.show_snapshot_menu)
        self.snapshot_menu = tk.Menu(self, tearoff=False)
        self.snapshot_menu.add_command(label="删除该采集时间", command=self.delete_selected_snapshot)
        snapshot_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.snapshot_tree.yview)
        self.snapshot_tree.configure(yscrollcommand=snapshot_scroll.set)
        snapshot_scroll.grid(row=0, column=1, sticky="ns")

        self.entry_tree = ttk.Treeview(
            right,
            columns=("rank", "name", "score", "type", "score_name", "current", "friend"),
            show="headings",
        )
        entry_headings = {
            "rank": ("排名", 70),
            "name": ("玩家", 220),
            "score": ("分数", 130),
            "type": ("类型", 60),
            "score_name": ("分数名", 110),
            "current": ("自己", 48),
            "friend": ("好友", 58),
        }
        for column, (label, width) in entry_headings.items():
            self.entry_tree.heading(column, text=label)
            self.entry_tree.column(column, width=width, anchor="w", stretch=column == "name")
        self.entry_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        entry_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.entry_tree.yview)
        self.entry_tree.configure(yscrollcommand=entry_scroll.set)
        entry_scroll.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        log_frame = ttk.Frame(right)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=8, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.grid(row=0, column=1, sticky="ns")

        bottom = ttk.Frame(self, padding=(10, 0, 10, 8))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status).grid(row=0, column=0, sticky="w")
        ttk.Label(bottom, text=f"数据库: {core.DEFAULT_DB_PATH}").grid(row=0, column=1, sticky="e")

    def log(self, message: str) -> None:
        self.log_text.insert("1.0", f"[{core.now_iso()}] {message}\n")
        self.log_text.see("1.0")

    def on_cfg_path_changed(self, *_args: object) -> None:
        with self.cfg_state_lock:
            self.cfg_path_value = self.cfg_path.get()
            self.last_cfg_mtime_ns = None
            self.last_cfg_signature = None

    def on_auto_refresh_changed(self, *_args: object) -> None:
        with self.cfg_state_lock:
            self.auto_refresh_value = bool(self.auto_refresh.get())

    def start_background_import(self) -> None:
        self.import_thread = threading.Thread(target=self.import_worker_loop, name="cfg-import-worker", daemon=True)
        self.capture_thread = threading.Thread(target=self.capture_cfg_loop, name="cfg-capture-worker", daemon=True)
        self.import_thread.start()
        self.capture_thread.start()

    def current_capture_state(self) -> tuple[Path, bool, str | None]:
        with self.cfg_state_lock:
            return Path(self.cfg_path_value), self.auto_refresh_value, self.last_cfg_signature

    def update_seen_cfg(self, signature: str, mtime_ns: int | None) -> bool:
        with self.cfg_state_lock:
            if signature == self.last_cfg_signature:
                return False
            self.last_cfg_signature = signature
            self.last_cfg_mtime_ns = mtime_ns
            return True

    def capture_cfg_loop(self) -> None:
        while not self.worker_stop.is_set():
            path, auto_refresh, last_signature = self.current_capture_state()
            if auto_refresh:
                try:
                    raw = path.read_bytes()
                    stat = path.stat()
                except OSError:
                    raw = b""
                    stat = None
                if raw:
                    signature = hashlib.sha256(raw).hexdigest()
                    if signature != last_signature and self.update_seen_cfg(signature, stat.st_mtime_ns if stat else None):
                        self.import_queue.put(
                            CapturedCfg(
                                path=str(path),
                                raw=raw,
                                signature=signature,
                                mtime_ns=stat.st_mtime_ns if stat else None,
                            )
                        )
            self.worker_stop.wait(POLL_MS / 1000)

    def import_worker_loop(self) -> None:
        conn = core.init_db(core.DEFAULT_DB_PATH)
        try:
            while not self.worker_stop.is_set() or not self.import_queue.empty():
                try:
                    captured = self.import_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if captured is None:
                    self.import_queue.task_done()
                    break
                try:
                    summary = core.import_cfg_bytes(conn, captured.raw, captured.mtime_ns)
                    self.import_result_queue.put(
                        ImportWorkerResult(summary, captured.signature, captured.mtime_ns)
                    )
                except Exception as exc:  # Keep the capture thread alive even if one import fails.
                    self.import_result_queue.put(
                        ImportWorkerResult(None, captured.signature, captured.mtime_ns, str(exc))
                    )
                finally:
                    self.import_queue.task_done()
        finally:
            conn.close()

    def process_import_results(self) -> None:
        imported = 0
        skipped = 0
        pending = 0
        errors: list[str] = []
        processed = 0
        while True:
            try:
                result = self.import_result_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if result.error:
                errors.append(result.error)
                continue
            if result.summary is None:
                continue
            imported += result.summary.imported
            skipped += result.summary.skipped
            pending += result.summary.pending
            errors.extend(result.summary.errors)

        for error in errors:
            self.log(error)

        if imported > 0:
            self.refresh_board_list(load_snapshot_entries=False)
            message = f"后台导入 {imported}, 跳过 {skipped}"
            if pending:
                message += f", 等待 {pending}"
            queued = self.import_queue.qsize()
            if queued:
                message += f", 队列 {queued}"
            self.status.set(message)
            self.log(message)
        elif errors:
            for error in errors:
                self.log(error)
            self.status.set(f"后台导入错误 {len(errors)}, 跳过 {skipped}")
        elif pending:
            self.status.set("检测到 data/progress 未对齐，等待下一次 cfg 写入")
        elif processed and skipped:
            queued = self.import_queue.qsize()
            if queued:
                self.status.set(f"后台跳过 {skipped}, 队列 {queued}")

        if not self.worker_stop.is_set():
            self.after(IMPORT_RESULT_POLL_MS, self.process_import_results)

    def choose_cfg(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 Trove 排行榜配置文件",
            initialdir=str(core.DEFAULT_CFG_PATH.parent),
            filetypes=[("Trove 配置文件", "*.cfg"), ("所有文件", "*.*")],
        )
        if selected:
            self.cfg_path.set(selected)
            with self.cfg_state_lock:
                self.last_cfg_mtime_ns = None
                self.last_cfg_signature = None
            self.refresh_all()

    def refresh_all(self) -> None:
        catalog_summary = core.sync_catalog(self.conn, Path(self.cfg_path.get()))
        summary = core.import_cfg_dump(self.conn, Path(self.cfg_path.get()))
        self.refresh_board_list()
        parts = [
            f"目录 {catalog_summary.unique_rows}",
            f"完整目录 {catalog_summary.full_rows}",
            f"来源 {catalog_summary.source}",
            f"导入 {summary.imported}",
            f"跳过 {summary.skipped}",
        ]
        for error in catalog_summary.errors:
            self.log(error)
        if summary.errors:
            parts.append(f"错误 {len(summary.errors)}")
            for error in summary.errors:
                self.log(error)
        self.status.set(", ".join(parts))
        self.log(", ".join(parts))
        self.update_cfg_mtime()

    def import_dump_change(self, path: Path, mtime_ns: int | None, signature: str | None = None) -> None:
        summary = core.import_cfg_dump(self.conn, path)
        with self.cfg_state_lock:
            self.last_cfg_mtime_ns = mtime_ns
            if signature is not None:
                self.last_cfg_signature = signature
        if summary.imported > 0:
            self.refresh_board_list(load_snapshot_entries=False)
            message = f"导入 {summary.imported}, 跳过 {summary.skipped}"
            self.status.set(message)
            self.log(message)
        elif summary.errors:
            for error in summary.errors:
                self.log(error)
            self.status.set(f"错误 {len(summary.errors)}, 跳过 {summary.skipped}")
        elif summary.pending > 0:
            self.status.set("检测到 data/progress 未对齐，等待下一次 cfg 写入")

    def import_catalog_only(self) -> None:
        summary = core.import_catalog_from_cfg(self.conn, Path(self.cfg_path.get()))
        for error in summary.errors:
            self.log(error)
        if summary.unique_rows <= 0:
            messagebox.showwarning("导入目录", "\n".join(summary.errors) or "没有导入任何排行榜目录。")
            return
        self.refresh_board_list()
        message = f"已从配置文件导入目录：完整 {summary.full_rows}，唯一 {summary.unique_rows}"
        self.status.set(message)
        self.log(message)

    def refresh_board_list(self, load_snapshot_entries: bool = True) -> None:
        selected = self.current_leaderboard_id()
        self.board_tree.delete(*self.board_tree.get_children())
        category_nodes: dict[str, str] = {}
        for row in core.get_leaderboard_status(self.conn):
            category_id = row["category_id"] or ""
            category = row["category"] or "(未分类)"
            category_iid = f"cat:{category_id}:{category}"
            if category_iid not in category_nodes:
                label = f"{category_id}  {category}" if category_id else category
                self.board_tree.insert("", "end", iid=category_iid, text=label, open=True, values=("", "", "", "", ""))
                category_nodes[category_iid] = category_iid

            iid = f"lb:{row['leaderboard_id']}"
            complete = ""
            if row["snapshot_id"] is not None:
                complete = "是" if row["complete"] else "否"
            image = self.get_icon(row["icon_path"])
            item_options = {
                "iid": iid,
                "text": row["name"],
                "values": (
                    row["leaderboard_id"],
                    row["entries"] if row["entries"] is not None else "",
                    row["expected"] if row["expected"] is not None else "",
                    complete,
                    core.format_saved_at(row["saved_at_ms"]),
                ),
                "tags": ("done" if complete == "是" else "pending",),
            }
            if image is not None:
                item_options["image"] = image
            self.board_tree.insert(category_iid, "end", **item_options)
        selected_iid = f"lb:{selected}" if selected else ""
        if selected_iid and self.board_tree.exists(selected_iid):
            self.board_tree.selection_set(selected_iid)
            self.board_tree.see(selected_iid)
            self.refresh_snapshot_list(selected, load_entries=load_snapshot_entries)

    def current_leaderboard_id(self) -> str | None:
        selection = self.board_tree.selection()
        if not selection:
            return None
        iid = selection[0]
        if not iid.startswith("lb:"):
            return None
        return iid[3:]

    def on_board_selected(self, _event: tk.Event | None = None) -> None:
        leaderboard_id = self.current_leaderboard_id()
        self.refresh_snapshot_list(leaderboard_id, load_entries=True)

    def refresh_snapshot_list(self, leaderboard_id: str | None, load_entries: bool = True) -> None:
        previous_snapshot_id = self.selected_snapshot_id
        if load_entries:
            self.entry_tree.delete(*self.entry_tree.get_children())
        self.snapshot_tree.delete(*self.snapshot_tree.get_children())
        self.selected_leaderboard_id = leaderboard_id
        if not leaderboard_id:
            self.selected_snapshot_id = None
            if load_entries:
                self.status.set("请在分类下选择一个排行榜")
            return
        snapshots = core.get_snapshots(self.conn, leaderboard_id)
        if not snapshots:
            self.selected_snapshot_id = None
            if load_entries:
                self.status.set(f"排行榜 {leaderboard_id}: 还没有导入采集数据")
            return
        snapshot_ids = set()
        for row in snapshots:
            snapshot_ids.add(int(row["id"]))
            self.snapshot_tree.insert(
                "",
                "end",
                iid=f"snap:{row['id']}",
                values=(
                    core.format_saved_at(row["saved_at_ms"]) or f"快照 {row['id']}",
                    self.format_snapshot_range(row["range_start"], row["range_end"]),
                    row["entries"] if row["entries"] is not None else "",
                    row["expected"] if row["expected"] is not None else "",
                    "是" if row["complete"] else "否",
                    row["imported_at"],
                ),
            )
        if previous_snapshot_id in snapshot_ids:
            target_snapshot_id = previous_snapshot_id
        else:
            target_snapshot_id = int(snapshots[0]["id"])
        target = f"snap:{target_snapshot_id}"
        self.snapshot_tree.selection_set(target)
        self.snapshot_tree.see(target)
        if load_entries:
            self.on_snapshot_selected()
        else:
            self.selected_snapshot_id = target_snapshot_id

    def on_snapshot_selected(self, _event: tk.Event | None = None) -> None:
        self.entry_tree.delete(*self.entry_tree.get_children())
        selection = self.snapshot_tree.selection()
        if not selection:
            return
        iid = selection[0]
        if not iid.startswith("snap:"):
            return
        snapshot_id = int(iid[5:])
        self.selected_snapshot_id = snapshot_id
        for row in core.get_snapshot_entries(self.conn, snapshot_id, limit=500):
            self.entry_tree.insert(
                "",
                "end",
                values=(
                    row["rank"],
                    row["player_name"],
                    row["score_raw"],
                    row["score_type"],
                    row["score_name"],
                    "是" if row["is_current_player"] else "",
                    "是" if row["is_friend"] else "",
                ),
            )
        label = self.selected_leaderboard_id or "-"
        self.status.set(f"排行榜 {label}: 正在查看快照 #{snapshot_id}")

    def format_snapshot_range(self, start: int | None, end: int | None) -> str:
        if start is None and end is None:
            return ""
        if start is None:
            return f"-{end}"
        if end is None:
            return f"{start}-"
        return f"{start}-{end}"

    def show_snapshot_menu(self, event: tk.Event) -> None:
        iid = self.snapshot_tree.identify_row(event.y)
        if not iid or not iid.startswith("snap:"):
            return
        self.snapshot_tree.selection_set(iid)
        self.snapshot_tree.focus(iid)
        self.on_snapshot_selected()
        try:
            self.snapshot_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.snapshot_menu.grab_release()

    def delete_selected_snapshot(self) -> None:
        snapshot_id = self.selected_snapshot_id
        if snapshot_id is None:
            return
        leaderboard_id = self.selected_leaderboard_id or self.current_leaderboard_id()
        values = self.snapshot_tree.item(f"snap:{snapshot_id}").get("values", [])
        label = str(values[0]) if values else f"快照 #{snapshot_id}"
        confirmed = messagebox.askyesno(
            "删除采集时间",
            f"确定删除 {label} 的这条采集数据吗？\n只删除这一条采集时间，不删除排行榜目录。",
        )
        if not confirmed:
            return
        counts = core.delete_snapshot(self.conn, snapshot_id)
        self.selected_snapshot_id = None
        self.refresh_board_list(load_snapshot_entries=True)
        self.update_cfg_mtime()
        message = (
            f"已删除快照 #{snapshot_id}: "
            f"批次 {counts['dump_batches']}, 明细 {counts['entries']}"
        )
        if leaderboard_id:
            message = f"排行榜 {leaderboard_id}: " + message
        self.status.set(message)
        self.log(message)

    def export_selected(self) -> None:
        leaderboard_id = self.current_leaderboard_id()
        if not leaderboard_id:
            messagebox.showinfo("导出 CSV", "请先选择一个排行榜。")
            return
        snapshot_id = self.selected_snapshot_id
        if snapshot_id is None:
            messagebox.showinfo("导出 CSV", "请先选择一个采集时间快照。")
            return
        try:
            path = core.export_snapshot_csv(
                self.conn,
                leaderboard_id,
                snapshot_id,
                Path(__file__).resolve().parent / "exports",
            )
        except RuntimeError as exc:
            messagebox.showwarning("导出 CSV", str(exc))
            return
        self.log(f"已导出排行榜 {leaderboard_id}: {path}")
        messagebox.showinfo("导出 CSV", f"已导出:\n{path}")

    def open_upload_window(self) -> None:
        if self.upload_window is not None and self.upload_window.winfo_exists():
            self.upload_window.lift()
            self.refresh_upload_list()
            return

        window = tk.Toplevel(self)
        window.title("上传采集数据")
        window.geometry("1120x620")
        window.minsize(920, 520)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", self.close_upload_window)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)
        self.upload_window = window

        url_frame = ttk.Frame(window, padding=(10, 10, 10, 4))
        url_frame.grid(row=0, column=0, sticky="ew")
        url_frame.columnconfigure(1, weight=1)
        ttk.Label(url_frame, text="上传地址").grid(row=0, column=0, sticky="w")
        ttk.Entry(url_frame, textvariable=self.upload_url).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(url_frame, text="保存配置", command=self.save_upload_settings).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(url_frame, text="刷新列表", command=self.refresh_upload_list).grid(row=0, column=3)
        ttk.Label(url_frame, text="采集密钥").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(url_frame, textvariable=self.collector_token, show="*").grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(8, 8),
            pady=(8, 0),
        )
        ttk.Label(url_frame, text="与云端 LEADERBOARD_COLLECTOR_TOKEN 一致，至少 32 个字符").grid(
            row=1,
            column=2,
            columnspan=2,
            sticky="w",
            pady=(8, 0),
        )

        action_frame = ttk.Frame(window, padding=(10, 4, 10, 4))
        action_frame.grid(row=1, column=0, sticky="ew")
        ttk.Label(action_frame, text="范围").grid(row=0, column=0, sticky="w")
        filter_box = ttk.Combobox(
            action_frame,
            textvariable=self.upload_status_filter,
            state="readonly",
            width=12,
            values=tuple(UPLOAD_FILTER_LABELS.values()),
        )
        filter_box.grid(row=0, column=1, padx=(8, 12))
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_upload_list())
        ttk.Label(action_frame, text="采集日期").grid(row=0, column=2, sticky="w")
        date_entry = ttk.Entry(action_frame, textvariable=self.upload_date_filter, width=22, state="readonly")
        date_entry.grid(row=0, column=3, padx=(8, 6))
        date_entry.bind("<Button-1>", lambda _event: self.open_upload_calendar())
        ttk.Button(action_frame, text="选择日期", command=self.open_upload_calendar).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(action_frame, text="清空日期", command=self.clear_upload_date_filter).grid(row=0, column=5, padx=(0, 16))
        ttk.Button(action_frame, text="选中最新数据(不全)", command=self.select_latest_visible_upload_rows).grid(row=0, column=6, padx=(0, 6))
        ttk.Button(action_frame, text="选中最新数据(全)", command=self.select_latest_complete_visible_upload_rows).grid(row=0, column=7, padx=(0, 16))
        ttk.Button(action_frame, text="上传选中", command=self.upload_selected_snapshots).grid(row=0, column=8)

        table_frame = ttk.Frame(window, padding=(10, 4, 10, 4))
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.upload_tree = ttk.Treeview(
            table_frame,
            columns=(
                "status",
                "snapshot",
                "leaderboard",
                "time",
                "range",
                "complete",
                "entries",
                "retry",
                "last_attempt",
                "error",
            ),
            show="headings",
            selectmode="extended",
        )
        headings = {
            "status": ("状态", 76),
            "snapshot": ("快照ID", 72),
            "leaderboard": ("排行榜", 260),
            "time": ("采集时间", 150),
            "range": ("范围", 110),
            "complete": ("采集完整", 78),
            "entries": ("行数", 70),
            "retry": ("重试", 54),
            "last_attempt": ("最后尝试", 150),
            "error": ("错误", 260),
        }
        for column, (label, width) in headings.items():
            self.upload_tree.heading(column, text=label)
            self.upload_tree.column(column, width=width, anchor="w", stretch=column in {"leaderboard", "error"})
        self.upload_tree.grid(row=0, column=0, sticky="nsew")
        self.upload_tree.bind("<ButtonPress-1>", self.begin_upload_drag_select)
        self.upload_tree.bind("<B1-Motion>", self.update_upload_drag_select)
        upload_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.upload_tree.yview)
        self.upload_tree.configure(yscrollcommand=upload_scroll.set)
        upload_scroll.grid(row=0, column=1, sticky="ns")

        status_frame = ttk.Frame(window, padding=(10, 0, 10, 10))
        status_frame.grid(row=3, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.upload_status).grid(row=0, column=0, sticky="w")

        self.refresh_upload_list()

    def close_upload_window(self) -> None:
        if self.upload_calendar_window is not None and self.upload_calendar_window.winfo_exists():
            self.upload_calendar_window.destroy()
        self.upload_calendar_window = None
        if self.upload_window is not None:
            self.upload_window.destroy()
        self.upload_window = None
        self.upload_tree = None
        self.upload_drag_anchor_iid = None

    def save_upload_settings(self) -> None:
        url = self.upload_url.get().strip()
        if not url:
            messagebox.showwarning("上传地址", "上传地址不能为空。")
            return
        token = self.collector_token.get().strip()
        if len(token) < core.MIN_COLLECTOR_TOKEN_LENGTH:
            messagebox.showwarning(
                "采集密钥",
                f"采集密钥至少需要 {core.MIN_COLLECTOR_TOKEN_LENGTH} 个字符。",
            )
            return
        try:
            normalized_url = core.validate_upload_url(url)
        except ValueError as exc:
            messagebox.showwarning("上传地址", str(exc))
            return
        core.set_upload_url(self.conn, normalized_url)
        core.set_collector_token(self.conn, token)
        self.upload_url.set(normalized_url)
        self.upload_status.set(f"已保存上传配置: {normalized_url}")
        self.log(f"已保存上传配置: {normalized_url}")

    def refresh_upload_list(self) -> None:
        if self.upload_tree is None:
            return
        self.upload_tree.delete(*self.upload_tree.get_children())
        selected_filter, date_filter, rows, visible_rows = self.filtered_upload_rows()
        for row in visible_rows:
            snapshot_id = int(row["snapshot_id"])
            leaderboard = f"{row['leaderboard_id']} {row['leaderboard_name']}"
            collected_at = core.format_saved_at(row["saved_at_ms"]) or row["imported_at"] or ""
            status = row["upload_status"] or "pending"
            self.upload_tree.insert(
                "",
                "end",
                iid=f"upload:{snapshot_id}",
                values=(
                    self.upload_status_label(status),
                    snapshot_id,
                    leaderboard,
                    collected_at,
                    self.format_snapshot_range(row["range_start"], row["range_end"]),
                    self.upload_complete_label(row["complete"]),
                    row["entries"] if row["entries"] is not None else "",
                    row["retry_count"],
                    row["last_attempt_at"] or "",
                    row["last_error"] or "",
                ),
            )
        date_note = f"，日期 {date_filter}" if date_filter else ""
        self.upload_status.set(f"当前筛选: {selected_filter}{date_note}。显示 {len(visible_rows)} / {len(rows)} 个采集快照。")

    def filtered_upload_rows(self) -> tuple[str, str, list[object], list[object]]:
        selected_label = self.upload_status_filter.get()
        selected_filter = UPLOAD_FILTER_BY_LABEL.get(selected_label, "latest_complete")
        date_filter = self.upload_date_filter.get().strip()
        if selected_filter == "latest_complete":
            rows = core.list_latest_complete_upload_snapshots(self.conn)
        else:
            rows = core.list_upload_snapshots(self.conn)

        status_filter_map = {
            "pending": "pending",
            "failed": "failed",
            "uploaded": "uploaded",
        }
        expected_status = status_filter_map.get(selected_filter)
        visible_rows: list[object] = []
        for row in rows:
            status = row["upload_status"] or "pending"
            if not self.row_matches_upload_date_range(row):
                continue
            if selected_filter == "not_uploaded" and status == "uploaded":
                continue
            if expected_status is not None and status != expected_status:
                continue
            visible_rows.append(row)
        return selected_label, date_filter, rows, visible_rows

    def upload_status_label(self, status: str) -> str:
        labels = {
            "pending": "待上传",
            "failed": "失败",
            "uploaded": "已上传",
        }
        return labels.get(status, status)

    def upload_complete_label(self, complete: object) -> str:
        return "完整" if int(complete or 0) else "不完整"

    def open_upload_calendar(self) -> None:
        if self.upload_calendar_window is not None and self.upload_calendar_window.winfo_exists():
            self.upload_calendar_window.lift()
            return

        month = self.upload_date_start or date.today()
        self.upload_calendar_month = month.replace(day=1)
        self.upload_calendar_pending_start = None

        window = tk.Toplevel(self.upload_window or self)
        window.title("选择采集日期")
        window.geometry("340x330")
        window.resizable(False, False)
        window.transient(self.upload_window or self)
        window.protocol("WM_DELETE_WINDOW", self.close_upload_calendar)
        self.upload_calendar_window = window
        self.render_upload_calendar()

    def close_upload_calendar(self) -> None:
        if self.upload_calendar_window is not None:
            self.upload_calendar_window.destroy()
        self.upload_calendar_window = None
        self.upload_calendar_pending_start = None

    def render_upload_calendar(self) -> None:
        window = self.upload_calendar_window
        month = self.upload_calendar_month
        if window is None or month is None:
            return
        for child in window.winfo_children():
            child.destroy()

        frame = ttk.Frame(window, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        for column in range(7):
            frame.columnconfigure(column, weight=1)

        previous_month = self.add_months(month, -1)
        next_month = self.add_months(month, 1)
        ttk.Button(frame, text="<", width=3, command=lambda: self.show_upload_calendar_month(previous_month)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(frame, text=f"{month.year}-{month.month:02d}", anchor="center").grid(
            row=0, column=1, columnspan=5, sticky="ew"
        )
        ttk.Button(frame, text=">", width=3, command=lambda: self.show_upload_calendar_month(next_month)).grid(
            row=0, column=6, sticky="e"
        )

        weekdays = ("一", "二", "三", "四", "五", "六", "日")
        for column, label in enumerate(weekdays):
            ttk.Label(frame, text=label, anchor="center").grid(row=1, column=column, pady=(10, 4), sticky="ew")

        calendar.setfirstweekday(calendar.MONDAY)
        weeks = calendar.monthcalendar(month.year, month.month)
        selected_start = self.upload_calendar_pending_start or self.upload_date_start
        selected_end = None if self.upload_calendar_pending_start else self.upload_date_end
        for row_index, week in enumerate(weeks, start=2):
            for column, day_number in enumerate(week):
                if day_number == 0:
                    ttk.Label(frame, text="").grid(row=row_index, column=column, padx=2, pady=2, sticky="ew")
                    continue
                day = date(month.year, month.month, day_number)
                text = str(day_number)
                if selected_start == day and selected_end == day:
                    text = f"[{day_number}]"
                elif selected_start == day:
                    text = f"{day_number}*"
                elif selected_end == day:
                    text = f"*{day_number}"
                elif selected_start and selected_end and selected_start < day < selected_end:
                    text = f"-{day_number}-"
                ttk.Button(
                    frame,
                    text=text,
                    width=4,
                    command=lambda picked=day: self.pick_upload_calendar_date(picked),
                ).grid(row=row_index, column=column, padx=2, pady=2, sticky="ew")

        hint = "第一次点击开始日期，第二次点击结束日期；同一天表示当天。"
        if self.upload_calendar_pending_start is not None:
            hint = f"开始日期: {self.upload_calendar_pending_start.isoformat()}，请选择结束日期。"
        ttk.Label(frame, text=hint, foreground="#555555", anchor="center").grid(
            row=8, column=0, columnspan=7, sticky="ew", pady=(10, 0)
        )

    def show_upload_calendar_month(self, month: date) -> None:
        self.upload_calendar_month = month.replace(day=1)
        self.render_upload_calendar()

    def pick_upload_calendar_date(self, picked: date) -> None:
        if self.upload_calendar_pending_start is None:
            self.upload_calendar_pending_start = picked
            self.render_upload_calendar()
            return

        start = self.upload_calendar_pending_start
        end = picked
        if end < start:
            start, end = end, start
        self.upload_date_start = start
        self.upload_date_end = end
        self.upload_date_filter.set(self.format_upload_date_range(start, end))
        self.close_upload_calendar()
        self.refresh_upload_list()

    def add_months(self, value: date, delta: int) -> date:
        month_index = value.year * 12 + value.month - 1 + delta
        year = month_index // 12
        month = month_index % 12 + 1
        return date(year, month, 1)

    def format_upload_date_range(self, start: date | None, end: date | None) -> str:
        if start is None or end is None:
            return ""
        if start == end:
            return start.isoformat()
        return f"{start.isoformat()} 至 {end.isoformat()}"

    def parse_upload_row_date(self, row: object) -> date | None:
        collected_at = core.format_saved_at(row["saved_at_ms"]) or row["imported_at"] or ""
        if len(collected_at) < 10:
            return None
        try:
            return date.fromisoformat(collected_at[:10])
        except ValueError:
            return None

    def row_matches_upload_date_range(self, row: object) -> bool:
        if self.upload_date_start is None or self.upload_date_end is None:
            return True
        row_date = self.parse_upload_row_date(row)
        if row_date is None:
            return False
        return self.upload_date_start <= row_date <= self.upload_date_end

    def clear_upload_date_filter(self) -> None:
        self.upload_date_start = None
        self.upload_date_end = None
        self.upload_calendar_pending_start = None
        self.upload_date_filter.set("")
        self.refresh_upload_list()

    def begin_upload_drag_select(self, event: tk.Event) -> None:
        if self.upload_tree is None:
            return
        iid = self.upload_tree.identify_row(event.y)
        if not iid:
            self.upload_drag_anchor_iid = None
            return
        self.upload_drag_anchor_iid = iid
        self.upload_tree.selection_set(iid)

    def update_upload_drag_select(self, event: tk.Event) -> None:
        if self.upload_tree is None or self.upload_drag_anchor_iid is None:
            return
        current_iid = self.upload_tree.identify_row(event.y)
        if not current_iid:
            return
        children = list(self.upload_tree.get_children(""))
        try:
            start = children.index(self.upload_drag_anchor_iid)
            end = children.index(current_iid)
        except ValueError:
            return
        if start > end:
            start, end = end, start
        self.upload_tree.selection_set(children[start : end + 1])

    def selected_upload_snapshot_ids(self) -> list[int]:
        if self.upload_tree is None:
            return []
        snapshot_ids: list[int] = []
        for iid in self.upload_tree.selection():
            if iid.startswith("upload:"):
                snapshot_ids.append(int(iid.split(":", 1)[1]))
        return snapshot_ids

    def select_latest_visible_upload_rows(self) -> None:
        self.select_latest_visible_upload_rows_by_complete(require_complete=False)

    def select_latest_complete_visible_upload_rows(self) -> None:
        self.upload_status_filter.set(UPLOAD_FILTER_LABELS["latest_complete"])
        self.upload_date_filter.set("")
        self.upload_date_start = None
        self.upload_date_end = None
        self.refresh_upload_list()
        self.select_latest_visible_upload_rows_by_complete(require_complete=True)

    def select_latest_visible_upload_rows_by_complete(self, require_complete: bool) -> None:
        if self.upload_tree is None:
            return
        _selected_filter, _date_filter, _rows, visible_rows = self.filtered_upload_rows()
        latest_by_leaderboard: dict[str, object] = {}
        for row in visible_rows:
            if require_complete and not int(row["complete"] or 0):
                continue
            leaderboard_id = str(row["leaderboard_id"])
            existing = latest_by_leaderboard.get(leaderboard_id)
            if existing is None or self.upload_row_sort_key(row) > self.upload_row_sort_key(existing):
                latest_by_leaderboard[leaderboard_id] = row

        selected_iids = [
            f"upload:{row['snapshot_id']}"
            for row in latest_by_leaderboard.values()
            if self.upload_tree.exists(f"upload:{row['snapshot_id']}")
        ]
        self.upload_tree.selection_set(selected_iids)
        if selected_iids:
            self.upload_tree.see(selected_iids[0])
        mode = "完整" if require_complete else "不限完整"
        self.upload_status.set(f"已在当前筛选范围内选中 {len(selected_iids)} 个排行榜的最新数据（{mode}）。")

    def upload_row_sort_key(self, row: object) -> tuple[int, int]:
        saved_at_ms = row["saved_at_ms"]
        try:
            saved_at = int(saved_at_ms or 0)
        except (TypeError, ValueError):
            saved_at = 0
        try:
            snapshot_id = int(row["snapshot_id"])
        except (TypeError, ValueError):
            snapshot_id = 0
        return saved_at, snapshot_id

    def upload_selected_snapshots(self) -> None:
        snapshot_ids = self.selected_upload_snapshot_ids()
        if not snapshot_ids:
            messagebox.showinfo("上传数据", "请先选择要上传的采集快照。")
            return
        latest_complete_snapshot_ids = {
            int(row["snapshot_id"])
            for row in core.list_latest_complete_upload_snapshots(self.conn)
        }
        selected_snapshot_ids = set(snapshot_ids)
        if not latest_complete_snapshot_ids:
            messagebox.showwarning("上传数据", "还没有可发布的完整排行榜快照。")
            return
        if selected_snapshot_ids != latest_complete_snapshot_ids:
            missing_count = len(latest_complete_snapshot_ids - selected_snapshot_ids)
            extra_count = len(selected_snapshot_ids - latest_complete_snapshot_ids)
            details = [
                f"已选择 {len(selected_snapshot_ids)} 个，完整一轮需要 {len(latest_complete_snapshot_ids)} 个。",
                "请点击“选中最新数据(全)”后再上传。",
            ]
            if missing_count:
                details.append(f"还缺少 {missing_count} 个最新完整榜单。")
            if extra_count:
                details.append(f"包含 {extra_count} 个不是最新完整数据的快照。")
            messagebox.showwarning("上传完整快照", "\n".join(details))
            return
        self.start_upload_thread(snapshot_ids)

    def start_upload_thread(self, snapshot_ids: list[int]) -> None:
        if self.upload_thread is not None and self.upload_thread.is_alive():
            messagebox.showinfo("上传数据", "已有上传任务正在运行，请等待完成。")
            return
        url = self.upload_url.get().strip()
        if not url:
            messagebox.showwarning("上传地址", "上传地址不能为空。")
            return
        token = self.collector_token.get().strip()
        if len(token) < core.MIN_COLLECTOR_TOKEN_LENGTH:
            messagebox.showwarning(
                "采集密钥",
                f"请填写与云端一致的采集密钥，至少 {core.MIN_COLLECTOR_TOKEN_LENGTH} 个字符。",
            )
            return
        try:
            url = core.validate_upload_url(url)
        except ValueError as exc:
            messagebox.showwarning("上传地址", str(exc))
            return
        core.set_upload_url(self.conn, url)
        token = core.set_collector_token(self.conn, token)
        self.upload_url.set(url)
        self.upload_status.set(f"开始上传 {len(snapshot_ids)} 个快照...")
        self.status.set(f"开始上传 {len(snapshot_ids)} 个快照")
        self.upload_thread = threading.Thread(
            target=self.upload_worker_loop,
            args=(snapshot_ids, url, token),
            name="leaderboard-upload-worker",
            daemon=True,
        )
        self.upload_thread.start()

    def upload_worker_loop(self, snapshot_ids: list[int], upload_url: str, collector_token: str) -> None:
        conn = core.init_db(core.DEFAULT_DB_PATH)
        try:
            board_ids = [core.get_snapshot_leaderboard_id(conn, snapshot_id) for snapshot_id in snapshot_ids]
            if len(board_ids) != len(set(board_ids)):
                raise RuntimeError("Select only one complete snapshot for each leaderboard before uploading.")

            first_payload = core.build_upload_payload(conn, snapshot_ids[0])
            source_date = str(first_payload.get("collected_at") or date.today().isoformat())[:10]
            status_code, message = self.post_upload_payload(
                upload_url,
                {
                    "source_date": source_date,
                    "expected_board_ids": sorted(board_ids),
                },
                collector_token,
            )
            response = self.parse_upload_response(message)
            remote_snapshot_id = response.get("snapshot_id")
            if not 200 <= status_code < 300 or not remote_snapshot_id:
                self.mark_upload_batch_failure(
                    conn,
                    snapshot_ids,
                    upload_url,
                    message or "Unable to create the server snapshot.",
                    status_code,
                )
                return

            board_url_prefix = f"{upload_url.rstrip('/')}/{urllib.parse.quote(str(remote_snapshot_id), safe='')}"
            for index, snapshot_id in enumerate(snapshot_ids):
                if self.worker_stop.is_set():
                    return
                payload = first_payload if index == 0 else core.build_upload_payload(conn, snapshot_id)
                status_code, message = self.post_upload_payload(
                    f"{board_url_prefix}/boards",
                    payload,
                    collector_token,
                )
                if not 200 <= status_code < 300:
                    self.mark_upload_batch_failure(
                        conn,
                        snapshot_ids,
                        upload_url,
                        message or "Unable to stage a leaderboard board.",
                        status_code,
                    )
                    return

            status_code, message = self.post_upload_payload(
                f"{board_url_prefix}/publish",
                {},
                collector_token,
            )
            if not 200 <= status_code < 300:
                self.mark_upload_batch_failure(
                    conn,
                    snapshot_ids,
                    upload_url,
                    message or "Unable to publish the server snapshot.",
                    status_code,
                )
                return

            success_message = f"Published server snapshot {remote_snapshot_id}."
            for snapshot_id in snapshot_ids:
                core.mark_upload_success(conn, snapshot_id, upload_url, status_code)
                self.upload_result_queue.put(
                    UploadWorkerResult(snapshot_id, True, status_code, success_message)
                )
        except Exception as exc:
            self.mark_upload_batch_failure(conn, snapshot_ids, upload_url, str(exc), None)
        finally:
            conn.close()

    def parse_upload_response(self, message: str) -> dict[str, object]:
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def mark_upload_batch_failure(
        self,
        conn: object,
        snapshot_ids: list[int],
        upload_url: str,
        error: str,
        status_code: int | None,
    ) -> None:
        for snapshot_id in snapshot_ids:
            core.mark_upload_failure(conn, snapshot_id, upload_url, error, status_code)
            self.upload_result_queue.put(
                UploadWorkerResult(snapshot_id, False, status_code, error)
            )

    def post_upload_payload(
        self,
        upload_url: str,
        payload: dict[str, object],
        collector_token: str,
    ) -> tuple[int, str]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timeout_seconds = min(600, max(60, 30 + len(body) // (64 * 1024)))
        last_error = "Upload request failed."
        for attempt in range(4):
            request = urllib.request.Request(
                upload_url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept": "application/json, text/plain, */*",
                    "Authorization": f"Bearer {collector_token}",
                    "Connection": "close",
                    "User-Agent": "TrovebbsTool-Collector/1.0",
                },
            )
            try:
                opener = urllib.request.build_opener(NoUploadRedirect())
                with opener.open(request, timeout=timeout_seconds) as response:
                    response_body = response.read(4000).decode("utf-8", errors="replace")
                    return int(response.status), response_body
            except urllib.error.HTTPError as exc:
                response_body = exc.read(4000).decode("utf-8", errors="replace")
                return int(exc.code), response_body
            except (urllib.error.URLError, OSError) as exc:
                last_error = str(exc)
                if attempt < 3:
                    time.sleep(2**attempt)
        return 0, f"Upload connection failed after 4 attempts: {last_error}"

    def process_upload_results(self) -> None:
        ok = 0
        failed = 0
        messages: list[str] = []
        while True:
            try:
                result = self.upload_result_queue.get_nowait()
            except queue.Empty:
                break
            if result.ok:
                ok += 1
            else:
                failed += 1
            outcome = "成功" if result.ok else "失败"
            code = f" {result.status_code}" if result.status_code is not None else ""
            messages.append(f"上传快照 #{result.snapshot_id}: {outcome}{code} {result.message[:160]}")

        for message in messages:
            self.log(message)
        if messages:
            self.refresh_upload_list()
            summary = f"上传完成: 成功 {ok}, 失败 {failed}"
            self.upload_status.set(summary)
            self.status.set(summary)

        if not self.worker_stop.is_set():
            self.after(UPLOAD_RESULT_POLL_MS, self.process_upload_results)

    def clear_selected_leaderboard(self) -> None:
        leaderboard_id = self.current_leaderboard_id()
        if not leaderboard_id:
            messagebox.showinfo("清空选中", "请先在左侧选择一个排行榜。")
            return
        item = self.board_tree.item(f"lb:{leaderboard_id}")
        name = item.get("text") or leaderboard_id
        confirmed = messagebox.askyesno(
            "清空选中",
            f"确定清空排行榜 {leaderboard_id}「{name}」的采集数据吗？\n目录不会删除。",
        )
        if not confirmed:
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            counts = core.clear_leaderboard_data(self.conn, leaderboard_id)
        finally:
            self.config(cursor="")
        self.selected_snapshot_id = None
        self.refresh_board_list(load_snapshot_entries=True)
        self.update_cfg_mtime()
        message = (
            f"已清空排行榜 {leaderboard_id}: "
            f"快照 {counts['snapshots']}, 批次 {counts['dump_batches']}, 明细 {counts['entries']}"
        )
        self.status.set(message)
        self.log(message)

    def clear_all_collected_data(self) -> None:
        confirmed = messagebox.askyesno(
            "清空全部数据",
            "确定清空数据库里的全部采集数据吗？\n排行榜目录会保留。",
        )
        if not confirmed:
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            counts = core.clear_all_collected_data(self.conn)
        finally:
            self.config(cursor="")
        self.selected_snapshot_id = None
        self.refresh_board_list(load_snapshot_entries=True)
        self.update_cfg_mtime()
        message = (
            "已清空全部采集数据: "
            f"快照 {counts['snapshots']}, 批次 {counts['dump_batches']}, 明细 {counts['entries']}"
        )
        self.status.set(message)
        self.log(message)

    def get_icon(self, icon_path: str | None) -> tk.PhotoImage | None:
        path = self.resolve_icon_path(icon_path)
        if path is None:
            return None
        key = str(path).lower()
        if key in self.icon_images:
            return self.icon_images[key]
        try:
            image = tk.PhotoImage(file=str(path))
            width = image.width()
            height = image.height()
            factor = max(1, int(max(width / 24, height / 24)))
            if factor > 1:
                image = image.subsample(factor, factor)
            self.icon_images[key] = image
            return image
        except tk.TclError:
            return None

    def resolve_icon_path(self, icon_path: str | None) -> Path | None:
        if not icon_path:
            return None
        normalized = icon_path.replace("\\", "/").strip()
        prefix = "ui/"
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix) :]
        path = core.PROJECT_ROOT / normalized
        if path.exists():
            return path
        return None

    def update_cfg_mtime(self) -> None:
        path = Path(self.cfg_path.get())
        try:
            mtime_ns = path.stat().st_mtime_ns
            signature = self.cfg_signature(path)
        except OSError:
            mtime_ns = None
            signature = None
        with self.cfg_state_lock:
            self.last_cfg_mtime_ns = mtime_ns
            self.last_cfg_signature = signature

    def cfg_signature(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def poll_cfg(self) -> None:
        # Legacy Tk polling hook kept for compatibility; cfg capture now runs in
        # capture_cfg_loop so imports cannot block the next file snapshot.
        return

    def begin_keepalive_drag(self, _event: tk.Event) -> None:
        if USER32 is None:
            self.keepalive_status.set("当前系统不支持窗口句柄锁定")
            return
        self.keepalive_status.set("拖到游戏窗口后松开")

    def lock_keepalive_window(self, _event: tk.Event) -> None:
        if USER32 is None:
            messagebox.showwarning("挂机窗口", "当前系统不支持窗口句柄锁定。")
            return

        hwnd = self.window_from_pointer()
        if not hwnd:
            self.keepalive_status.set("未获取到窗口")
            return
        if hwnd == self.winfo_id():
            self.keepalive_status.set("不能锁定采集器窗口")
            return

        self.keepalive_hwnd = hwnd
        self.keepalive_target.set(f"{self.describe_window(hwnd)}  HWND=0x{hwnd:X}")
        self.keepalive_status.set("窗口已锁定")
        self.log(f"已锁定挂机窗口: {self.keepalive_target.get()}")

    def window_from_pointer(self) -> int | None:
        if USER32 is None:
            return None
        point = wintypes.POINT(self.winfo_pointerx(), self.winfo_pointery())
        hwnd = int(USER32.WindowFromPoint(point) or 0)
        if hwnd:
            root = int(USER32.GetAncestor(hwnd, GA_ROOT) or 0)
            if root:
                hwnd = root
        return hwnd or None

    def describe_window(self, hwnd: int) -> str:
        if USER32 is None:
            return "未知窗口"
        title_len = int(USER32.GetWindowTextLengthW(hwnd))
        title = ""
        if title_len > 0:
            title_buffer = ctypes.create_unicode_buffer(title_len + 1)
            USER32.GetWindowTextW(hwnd, title_buffer, title_len + 1)
            title = title_buffer.value.strip()
        class_buffer = ctypes.create_unicode_buffer(256)
        USER32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        class_name = class_buffer.value.strip()
        if title and class_name:
            return f"{title} ({class_name})"
        if title:
            return title
        if class_name:
            return f"无标题窗口 ({class_name})"
        return "无标题窗口"

    def toggle_keepalive(self) -> None:
        if self.keepalive_active:
            self.stop_keepalive()
            return
        self.start_keepalive()

    def start_keepalive(self) -> None:
        if USER32 is None:
            messagebox.showwarning("开始挂机", "当前系统不支持后台按键。")
            return
        if not self.keepalive_hwnd:
            messagebox.showinfo("开始挂机", "请先拖拽 ◎ 到游戏窗口，锁定窗口句柄。")
            return
        if not self.is_valid_window(self.keepalive_hwnd):
            self.keepalive_hwnd = None
            self.keepalive_target.set("未锁定窗口")
            messagebox.showwarning("开始挂机", "锁定的窗口句柄已经无效，请重新拖拽锁定。")
            return

        self.keepalive_active = True
        self.keepalive_button.configure(text="停止挂机")
        self.keepalive_status.set("挂机中，每 60 秒按 R")
        self.log(f"开始挂机: {self.keepalive_target.get()}")
        self.run_keepalive()

    def stop_keepalive(self, write_log: bool = True) -> None:
        if self.keepalive_job is not None:
            try:
                self.after_cancel(self.keepalive_job)
            except tk.TclError:
                pass
            self.keepalive_job = None
        self.keepalive_active = False
        self.keepalive_button.configure(text="开始挂机")
        self.keepalive_status.set("挂机已停止")
        if write_log:
            self.log("停止挂机")

    def run_keepalive(self) -> None:
        if not self.keepalive_active:
            return
        if not self.keepalive_hwnd or not self.is_valid_window(self.keepalive_hwnd):
            self.stop_keepalive(write_log=False)
            self.keepalive_hwnd = None
            self.keepalive_target.set("未锁定窗口")
            self.keepalive_status.set("窗口无效，挂机已停止")
            self.log("挂机窗口无效，已停止")
            return

        if self.post_r_key(self.keepalive_hwnd):
            self.keepalive_status.set(f"已发送 R: {core.now_iso()}")
        else:
            self.keepalive_status.set("发送 R 失败")
            self.log(f"向 HWND=0x{self.keepalive_hwnd:X} 发送 R 失败")
        self.keepalive_job = self.after(KEEPALIVE_INTERVAL_MS, self.run_keepalive)

    def is_valid_window(self, hwnd: int) -> bool:
        return bool(USER32 is not None and USER32.IsWindow(hwnd))

    def post_r_key(self, hwnd: int) -> bool:
        if USER32 is None:
            return False
        scan_code = int(USER32.MapVirtualKeyW(VK_R, MAPVK_VK_TO_VSC))
        key_down_lparam = 1 | (scan_code << 16)
        key_up_lparam = key_down_lparam | (1 << 30) | (1 << 31)
        down_ok = bool(USER32.PostMessageW(hwnd, WM_KEYDOWN, VK_R, key_down_lparam))
        up_ok = bool(USER32.PostMessageW(hwnd, WM_KEYUP, VK_R, key_up_lparam))
        return down_ok and up_ok

    def open_collector_folder(self) -> None:
        folder = Path(__file__).resolve().parent
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("采集器目录", str(folder))

    def on_close(self) -> None:
        self.stop_keepalive(write_log=False)
        self.worker_stop.set()
        self.import_queue.put(None)
        if self.capture_thread is not None and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=0.5)
        if self.import_thread is not None and self.import_thread.is_alive():
            self.import_thread.join(timeout=1.5)
        self.conn.close()
        self.destroy()


def main() -> int:
    app = CollectorApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
