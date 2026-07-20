import json
import os
import re
import subprocess
import sys
import threading
import tkinter.font as tkfont
from pathlib import Path
from tkinter import (
    BooleanVar,
    DISABLED,
    END,
    IntVar,
    NORMAL,
    StringVar,
    Text,
    Tk,
    filedialog,
    messagebox,
    ttk,
)
from urllib import error, request


BASE_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = BASE_DIR / "main.py"
REPORT_SCRIPT = BASE_DIR / "report.py"
SETTINGS_FILE = BASE_DIR / "settings.json"


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text via a temp file in the same directory + os.replace.

    Prevents truncated/corrupt JSON if the process is killed mid-write.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)

PATH_SETTINGS = frozenset({
    "input_dir", "processed_dir", "output_jsonl", "errors_jsonl",
    "summary_csv", "findings_csv", "table_html",
})


def _first_available_family(root: Tk, candidates: tuple[str, ...]) -> str:
    try:
        raw = tkfont.families(root=root)
    except Exception:  # noqa: BLE001
        return candidates[-1]
    by_lower = {name.casefold(): name for name in raw}
    for want in candidates:
        found = by_lower.get(want.casefold())
        if found:
            return found
    return candidates[-1]


class LauncherApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("ДеклараторLM")
        self.root.geometry("820x600")
        self.root.minsize(700, 500)
        self._setup_style()

        self.input_dir = StringVar(value=str(BASE_DIR / "dataset_declarations"))
        self.processed_dir = StringVar(value=str(BASE_DIR / "dataset_declarations_done"))
        self.move_processed = BooleanVar(value=True)
        self.max_files = IntVar(value=1)
        self.model = StringVar(value="llama3.1")
        self.host = StringVar(value="http://127.0.0.1:11434")
        self.timeout = IntVar(value=600)
        self.retries = IntVar(value=2)
        self.retry_delay = IntVar(value=5)
        self.max_chars = IntVar(value=64000)
        self.num_predict = IntVar(value=16000)
        self.make_report = BooleanVar(value=True)
        self.no_dedupe = BooleanVar(value=False)
        self.output_jsonl = StringVar(value=str(BASE_DIR / "analysis_results.jsonl"))
        self.errors_jsonl = StringVar(value=str(BASE_DIR / "analysis_errors.jsonl"))
        self.summary_csv = StringVar(value=str(BASE_DIR / "report_summary.csv"))
        self.findings_csv = StringVar(value=str(BASE_DIR / "report_findings.csv"))
        self.table_html = StringVar(value=str(BASE_DIR / "report_table.html"))
        self.advanced_open = BooleanVar(value=False)

        self._load_settings()
        self._build_ui()

        self.is_running = False
        self.status_base = "Готово"
        self._status_animation_step = 0
        self._status_anim_job = None
        self._progress_re = re.compile(r"\[(\d+)/(\d+)\]\s+(OK|ERR)\s+(.+)")
        self._spinner_frames = ["|", "/", "-", "\\"]
        self.current_proc: subprocess.Popen[str] | None = None
        self.paused = False
        self.stop_requested = False
        self.control_file = BASE_DIR / ".run_control.json"
        self._progress_determinate = False

        # Fetch models in background after UI is ready.
        self.root.after(300, self._fetch_models)

    # ── Persist settings ────────────────────────────────────────────────────

    def _settings_map(self) -> dict:
        return {
            "input_dir": self.input_dir,
            "processed_dir": self.processed_dir,
            "move_processed": self.move_processed,
            "max_files": self.max_files,
            "model": self.model,
            "host": self.host,
            "timeout": self.timeout,
            "retries": self.retries,
            "retry_delay": self.retry_delay,
            "max_chars": self.max_chars,
            "num_predict": self.num_predict,
            "make_report": self.make_report,
            "no_dedupe": self.no_dedupe,
            "output_jsonl": self.output_jsonl,
            "errors_jsonl": self.errors_jsonl,
            "summary_csv": self.summary_csv,
            "findings_csv": self.findings_csv,
            "table_html": self.table_html,
        }

    @staticmethod
    def _resolve_path(raw: str) -> str:
        """Relative paths become absolute relative to BASE_DIR."""
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        return str(p)

    @staticmethod
    def _make_relative(raw: str) -> str:
        """If path is under BASE_DIR, store as relative; otherwise keep absolute."""
        try:
            p = Path(raw).resolve()
            return str(p.relative_to(BASE_DIR.resolve()))
        except ValueError:
            return raw

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.exists():
            return
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        smap = self._settings_map()
        for key, var in smap.items():
            if key not in data:
                continue
            try:
                value = data[key]
                if key in PATH_SETTINGS and isinstance(value, str):
                    value = self._resolve_path(value)
                var.set(value)
            except Exception:  # noqa: BLE001
                pass

    def _save_settings(self) -> None:
        smap = self._settings_map()
        data = {}
        for key, var in smap.items():
            value = var.get()
            if key in PATH_SETTINGS and isinstance(value, str):
                value = self._make_relative(value)
            data[key] = value
        try:
            _atomic_write_text(
                SETTINGS_FILE,
                json.dumps(data, ensure_ascii=False, indent=2),
            )
        except Exception:  # noqa: BLE001
            pass

    # ── Ollama model discovery ───────────────────────────────────────────────

    def _fetch_models(self) -> None:
        """Background: query Ollama /api/tags and populate the model combobox."""
        def _worker() -> None:
            host = self.host.get().rstrip("/")
            try:
                req = request.Request(f"{host}/api/tags", method="GET")
                with request.urlopen(req, timeout=4) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                models = [m["name"] for m in raw.get("models", [])]
            except Exception:  # noqa: BLE001
                models = []
            if models:
                self.root.after(0, lambda m=models: self._set_model_values(m))

        threading.Thread(target=_worker, daemon=True).start()

    def _set_model_values(self, models: list[str]) -> None:
        if hasattr(self, "_model_combo"):
            self._model_combo["values"] = models
            if self.model.get() not in models and models:
                # Keep user's current value even if not in list.
                pass

    # ── Style ────────────────────────────────────────────────────────────────

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        ui = _first_available_family(
            self.root,
            (
                "Inter",
                "Inter Variable",
                "Inter Display",
                "Segoe UI Variable Display",
                "Segoe UI Variable Text",
                "Segoe UI Variable",
                "Bahnschrift",
                "Segoe UI",
            ),
        )
        style.configure("Title.TLabel", font=(ui, 18, "bold"))
        style.configure("SubTitle.TLabel", font=(ui, 11), foreground="#445")
        style.configure("StatusLine.TLabel", font=(ui, 11), foreground="#446")
        style.configure("TLabel", font=(ui, 11))
        style.configure("TButton", font=(ui, 11))
        style.configure("TCheckbutton", font=(ui, 11))
        style.configure("TLabelframe.Label", font=(ui, 11))
        style.configure("TEntry", font=(ui, 11))
        style.configure("TCombobox", font=(ui, 11))
        style.configure("Card.TLabelframe", padding=8)
        style.configure("Primary.TButton", padding=(12, 6))
        style.configure("Secondary.TButton", padding=(8, 4))

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="ДеклараторLM", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frm,
            text="beta · v0.70",
            style="SubTitle.TLabel",
        ).pack(anchor="w", pady=(0, 4))

        basic = ttk.LabelFrame(frm, text="Основні параметри", style="Card.TLabelframe")
        basic.pack(fill="x", pady=(0, 5))
        self._row_with_browse_folder(
            basic, 0, "Папка з деклараціями", self.input_dir, "Оберіть папку з JSON"
        )
        self._row_with_browse_folder(
            basic,
            1,
            "Папка оброблених JSON",
            self.processed_dir,
            "Куди перемістити файли після успішного аналізу",
        )
        self._row(basic, 2, "Кількість файлів (0 = усі)", self.max_files)
        self._row_model_combobox(basic, 3, "Модель")
        self._row_host(basic, 4, "Хост Ollama")

        flags = ttk.Frame(frm)
        flags.pack(fill="x", pady=(0, 5))
        ttk.Checkbutton(flags, text="Створити табличні звіти", variable=self.make_report).pack(
            side="left", padx=(0, 14)
        )
        ttk.Checkbutton(
            flags,
            text="Переміщувати успішні JSON",
            variable=self.move_processed,
        ).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(
            flags,
            text="Без дедуплікації",
            variable=self.no_dedupe,
        ).pack(side="left", padx=(0, 14))

        adv_wrap = ttk.Frame(frm)
        adv_wrap.pack(fill="x", pady=(0, 5))
        self.adv_btn = ttk.Button(
            adv_wrap,
            text="▶ Розширені налаштування",
            command=self.toggle_advanced,
            style="Secondary.TButton",
        )
        self.adv_btn.pack(anchor="w")

        self.adv_frame = ttk.LabelFrame(
            frm, text="Розширені налаштування", style="Card.TLabelframe"
        )
        self._build_advanced_content(self.adv_frame)

        actions = ttk.Frame(frm)
        self.actions_frame = actions
        actions.pack(fill="x", pady=(2, 5))
        self.run_btn = ttk.Button(
            actions, text="Запустити пайплайн", command=self.start_run, style="Primary.TButton"
        )
        self.run_btn.pack(side="left")
        self.pause_btn = ttk.Button(
            actions,
            text="Пауза",
            command=self.pause_resume_run,
            style="Secondary.TButton",
            state=DISABLED,
        )
        self.pause_btn.pack(side="left", padx=(8, 0))
        self.stop_btn = ttk.Button(
            actions,
            text="Зупинити",
            command=self.stop_run,
            style="Secondary.TButton",
            state=DISABLED,
        )
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.open_report_btn = ttk.Button(
            actions,
            text="Відкрити HTML-звіт",
            command=self._open_report,
            style="Secondary.TButton",
            state=DISABLED,
        )
        self.open_report_btn.pack(side="left", padx=(8, 0))

        self.status_lbl = ttk.Label(actions, text="Готово", anchor="w")
        self.status_lbl.pack(side="left", padx=(12, 0))
        self.spinner_lbl = ttk.Label(actions, text="", width=2, anchor="center")
        self.spinner_lbl.pack(side="left", padx=(2, 0))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=(12, 0))

        log_frame = ttk.LabelFrame(frm, text="Живий лог", style="Card.TLabelframe")
        log_frame.pack(fill="both", expand=True, pady=(0, 0))
        log_font = _first_available_family(
            self.root,
            ("Cascadia Mono", "Cascadia Code", "Consolas", "Lucida Console", "Courier New"),
        )
        log_container = ttk.Frame(log_frame)
        log_container.pack(fill="both", expand=True)
        self.log = Text(
            log_container,
            wrap="word",
            height=12,
            font=(log_font, 12),
            foreground="#222",
        )
        scrollbar = ttk.Scrollbar(log_container, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state=DISABLED)

        # Define log color tags.
        self.log.tag_configure("ok_tag", foreground="#1a7a1a")
        self.log.tag_configure("err_tag", foreground="#cc2200")
        self.log.tag_configure("info_tag", foreground="#666666")
        self.log.tag_configure("done_tag", foreground="#1a4fa0")

        status_bar = ttk.Frame(frm)
        status_bar.pack(fill="x", pady=(6, 0))
        self.current_task_lbl = ttk.Label(
            status_bar,
            text="Очікує запуску",
            style="StatusLine.TLabel",
            anchor="nw",
            justify="left",
            wraplength=760,
        )
        self.current_task_lbl.pack(fill="x", anchor="nw")

        def _sync_status_wrap(event: object) -> None:
            if getattr(event, "widget", None) is not self.root:
                return
            w = int(getattr(event, "width", 0) or 0)
            if w > 0:
                self.current_task_lbl.configure(wraplength=max(280, w - 48))

        self.root.bind("<Configure>", _sync_status_wrap, add=True)

    def _build_advanced_content(self, parent: ttk.Widget) -> None:
        self._row(parent, 0, "Таймаут (сек)", self.timeout)
        self._row(parent, 1, "Кількість повторів", self.retries)
        self._row(parent, 2, "Пауза між повторами (сек)", self.retry_delay)
        self._row(parent, 3, "Макс. символів в payload", self.max_chars)
        self._row(
            parent,
            4,
            "Макс. токенів відповіді (num_predict)",
            self.num_predict,
        )

        self._row_with_browse_file(
            parent,
            5,
            "Файл результатів (JSONL)",
            self.output_jsonl,
            "Оберіть файл JSONL для результатів",
            [("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        self._row_with_browse_file(
            parent,
            6,
            "Файл помилок (JSONL)",
            self.errors_jsonl,
            "Оберіть файл JSONL для помилок",
            [("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        self._row_with_browse_file(
            parent,
            7,
            "Звіт summary (CSV)",
            self.summary_csv,
            "Оберіть файл summary CSV",
            [("CSV files", "*.csv"), ("All files", "*.*")],
        )
        self._row_with_browse_file(
            parent,
            8,
            "Звіт findings (CSV)",
            self.findings_csv,
            "Оберіть файл findings CSV",
            [("CSV files", "*.csv"), ("All files", "*.*")],
        )
        self._row_with_browse_file(
            parent,
            9,
            "Таблиця (HTML)",
            self.table_html,
            "Оберіть файл HTML звіту",
            [("HTML files", "*.html"), ("All files", "*.*")],
        )

    # ── Row helpers ──────────────────────────────────────────────────────────

    def _row(self, parent: ttk.Widget, row: int, label: str, var: object) -> None:
        ttk.Label(parent, text=label, width=26).grid(row=row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(parent, textvariable=var, width=78)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        parent.grid_columnconfigure(1, weight=1)

    def _row_model_combobox(self, parent: ttk.Widget, row: int, label: str) -> None:
        ttk.Label(parent, text=label, width=26).grid(row=row, column=0, sticky="w", pady=2)
        combo_frame = ttk.Frame(parent)
        combo_frame.grid(row=row, column=1, columnspan=2, sticky="ew", pady=2)
        combo_frame.grid_columnconfigure(0, weight=1)
        self._model_combo = ttk.Combobox(combo_frame, textvariable=self.model, width=50)
        self._model_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            combo_frame,
            text="↻ Оновити",
            style="Secondary.TButton",
            command=self._fetch_models,
        ).grid(row=0, column=1, padx=(6, 0))
        parent.grid_columnconfigure(1, weight=1)

    def _row_host(self, parent: ttk.Widget, row: int, label: str) -> None:
        ttk.Label(parent, text=label, width=26).grid(row=row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(parent, textvariable=self.host, width=78)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        parent.grid_columnconfigure(1, weight=1)

    def _row_with_browse_folder(
        self, parent: ttk.Widget, row: int, label: str, var: StringVar, title: str
    ) -> None:
        ttk.Label(parent, text=label, width=26).grid(row=row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(parent, textvariable=var, width=72)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(
            parent,
            text="Обрати",
            style="Secondary.TButton",
            command=lambda: self.pick_folder(var, title),
        ).grid(row=row, column=2, padx=(6, 0))
        parent.grid_columnconfigure(1, weight=1)

    def _row_with_browse_file(
        self,
        parent: ttk.Widget,
        row: int,
        label: str,
        var: StringVar,
        title: str,
        filetypes: list[tuple[str, str]],
    ) -> None:
        ttk.Label(parent, text=label, width=26).grid(row=row, column=0, sticky="w", pady=2)
        entry = ttk.Entry(parent, textvariable=var, width=72)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(
            parent,
            text="Обрати",
            style="Secondary.TButton",
            command=lambda: self.pick_file(var, title, filetypes),
        ).grid(row=row, column=2, padx=(6, 0))
        parent.grid_columnconfigure(1, weight=1)

    def pick_folder(self, var: StringVar, title: str) -> None:
        selected = filedialog.askdirectory(title=title, initialdir=str(BASE_DIR))
        if selected:
            var.set(selected)

    def pick_file(
        self, var: StringVar, title: str, filetypes: list[tuple[str, str]]
    ) -> None:
        initial = Path(var.get().strip() or str(BASE_DIR))
        selected = filedialog.asksaveasfilename(
            title=title,
            initialdir=str(initial.parent if initial.parent.exists() else BASE_DIR),
            initialfile=initial.name,
            filetypes=filetypes,
            defaultextension=filetypes[0][1].replace("*", ""),
        )
        if selected:
            var.set(selected)

    def toggle_advanced(self) -> None:
        is_open = self.advanced_open.get()
        if is_open:
            self.adv_frame.pack_forget()
            self.adv_btn.configure(text="▶ Розширені налаштування")
        else:
            self.adv_frame.pack(fill="x", pady=(0, 5), before=self.actions_frame)
            self.adv_btn.configure(text="▼ Розширені налаштування")
        self.advanced_open.set(not is_open)

    # ── Log helpers ──────────────────────────────────────────────────────────

    def append_log(self, text: str, tag: str = "") -> None:
        self.log.configure(state=NORMAL)
        if tag:
            self.log.insert(END, text, tag)
        else:
            self.log.insert(END, text)
        self.log.see(END)
        self.log.configure(state=DISABLED)

    def _tag_for_line(self, line: str) -> str:
        stripped = line.strip()
        if self._progress_re.search(line):
            return "ok_tag" if " OK " in line else "err_tag"
        if stripped.startswith("[OK]") or "] OK " in line:
            return "ok_tag"
        if stripped.startswith("[ERR]") or "] ERR " in line or "[ПОМИЛКА]" in line:
            return "err_tag"
        if stripped.startswith("[INFO]") or "===" in stripped:
            return "info_tag"
        if "Готово" in stripped or "Done" in stripped:
            return "done_tag"
        return ""

    # ── Status animation ─────────────────────────────────────────────────────

    def _animate_status(self) -> None:
        if not self.is_running:
            return
        frame = self._spinner_frames[self._status_animation_step % len(self._spinner_frames)]
        self.status_lbl.configure(text=self.status_base)
        self.spinner_lbl.configure(text=frame)
        self._status_animation_step += 1
        self._status_anim_job = self.root.after(350, self._animate_status)

    # ── Control file ─────────────────────────────────────────────────────────

    def _write_control_command(self, command: str) -> None:
        try:
            _atomic_write_text(
                self.control_file,
                json.dumps({"command": command}, ensure_ascii=False),
            )
        except OSError:
            pass

    # ── Preflight checks ─────────────────────────────────────────────────────

    def _check_preflight(self) -> bool:
        """Return True if it's safe to start the pipeline."""
        input_path = Path(self.input_dir.get().strip())
        if not input_path.exists():
            messagebox.showerror(
                "Помилка",
                f"Папка з деклараціями не існує:\n{input_path}",
            )
            return False

        host = self.host.get().rstrip("/")
        try:
            req = request.Request(f"{host}/api/tags", method="GET")
            with request.urlopen(req, timeout=4):
                pass
        except error.URLError:
            messagebox.showerror(
                "Ollama недоступний",
                f"Не вдається підключитись до Ollama за адресою:\n{host}\n\n"
                "Переконайтесь, що Ollama запущений (`ollama serve`).",
            )
            return False
        except Exception:  # noqa: BLE001
            messagebox.showerror(
                "Ollama недоступний",
                f"Не вдається підключитись до Ollama за адресою:\n{host}",
            )
            return False

        return True

    # ── Open report ──────────────────────────────────────────────────────────

    def _check_errors_after_run(self) -> None:
        """Read errors JSONL and surface a summary in the log + optional dialog."""
        import json as _json
        errors_path = Path(self.errors_jsonl.get().strip())
        if not errors_path.exists():
            return
        try:
            lines = [l for l in errors_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        except OSError:
            return
        if not lines:
            return

        # Collect errors from the most recent run only.
        current_model = self.model.get().strip()
        recent: list = []
        for l in lines:
            try:
                item = _json.loads(l)
                meta = item.get("run_meta") or {}
                if meta.get("model", "") == current_model:
                    recent.append(item)
            except Exception:  # noqa: BLE001
                pass

        if not recent:
            return

        unique_errors: dict = {}
        for item in recent:
            err = str(item.get("error", ""))[:120]
            unique_errors[err] = unique_errors.get(err, 0) + 1

        self.append_log(
            f"\n[⚠ ПОМИЛКИ] Модель '{current_model}': "
            f"{len(recent)} файл(ів) не вдалось обробити.\n",
            "err_tag",
        )
        for err, cnt in list(unique_errors.items())[:3]:
            self.append_log(f"  × ({cnt}×) {err}\n", "err_tag")

        # If ALL attempts failed, show a dialog.
        if len(recent) >= len(lines) // 2:
            messagebox.showwarning(
                "Помилки аналізу",
                f"Модель '{current_model}' спричинила {len(recent)} помилок.\n\n"
                + "\n".join(f"• {e}" for e in list(unique_errors)[:3])
                + "\n\nПереконайтесь, що модель встановлена: ollama list",
            )

    def _open_report(self) -> None:
        path = self.table_html.get().strip()
        if path and Path(path).exists():
            try:
                os.startfile(path)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Помилка", f"Не вдається відкрити файл:\n{exc}")
        else:
            messagebox.showinfo("HTML-звіт", f"Файл не знайдено:\n{path}")

    # ── Running state ────────────────────────────────────────────────────────

    def set_running_state(self, running: bool, report_ready: bool = False) -> None:
        self.is_running = running
        self.run_btn.configure(state=DISABLED if running else NORMAL)
        self.pause_btn.configure(state=NORMAL if running else DISABLED)
        self.stop_btn.configure(state=NORMAL if running else DISABLED)
        if running:
            self.status_base = "Виконується"
            self._status_animation_step = 0
            self.paused = False
            self.stop_requested = False
            self._progress_determinate = False
            self.pause_btn.configure(text="Пауза")
            self._write_control_command("run")
            if self._status_anim_job is not None:
                self.root.after_cancel(self._status_anim_job)
                self._status_anim_job = None
            self.status_lbl.configure(text=self.status_base)
            self.spinner_lbl.configure(text=self._spinner_frames[0])
            self._animate_status()
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
            self.current_task_lbl.configure(text="Підготовка до запуску...")
            self.open_report_btn.configure(state=DISABLED)
        else:
            if self._status_anim_job is not None:
                self.root.after_cancel(self._status_anim_job)
                self._status_anim_job = None
            self.status_lbl.configure(text="Готово")
            self.spinner_lbl.configure(text="")
            self.progress.stop()
            self.progress.configure(mode="indeterminate", value=0)
            self.current_task_lbl.configure(text="Очікує запуску")
            self.current_proc = None
            self.pause_btn.configure(text="Пауза")
            self._write_control_command("run")
            if report_ready:
                self.open_report_btn.configure(state=NORMAL)

    def _snapshot_run_config(self) -> dict:
        """Read every Tk Var on the main thread before spawning the worker.

        Tkinter is not thread-safe — reading StringVar/IntVar/BooleanVar from a
        background thread can crash on some platforms. The worker uses this
        immutable dict instead of touching `self.<var>.get()`.
        """
        return {
            "input_dir": self.input_dir.get().strip(),
            "output_jsonl": self.output_jsonl.get().strip(),
            "errors_jsonl": self.errors_jsonl.get().strip(),
            "model": self.model.get().strip(),
            "host": self.host.get().strip(),
            "timeout": int(self.timeout.get()),
            "max_files": int(self.max_files.get()),
            "max_chars": int(self.max_chars.get()),
            "retries": int(self.retries.get()),
            "retry_delay": int(self.retry_delay.get()),
            "num_predict": int(self.num_predict.get()),
            "move_processed": bool(self.move_processed.get()),
            "processed_dir": self.processed_dir.get().strip(),
            "make_report": bool(self.make_report.get()),
            "summary_csv": self.summary_csv.get().strip(),
            "findings_csv": self.findings_csv.get().strip(),
            "table_html": self.table_html.get().strip(),
            "no_dedupe": bool(self.no_dedupe.get()),
        }

    def start_run(self) -> None:
        if self.is_running:
            return
        if not self._check_preflight():
            return
        self._save_settings()
        self.set_running_state(True)
        self.append_log("\n=== Новий запуск ===\n", "info_tag")
        cfg = self._snapshot_run_config()
        thread = threading.Thread(
            target=self._run_pipeline, args=(cfg,), daemon=True
        )
        thread.start()

    def pause_resume_run(self) -> None:
        if not self.is_running:
            return
        self.paused = not self.paused
        if self.paused:
            self.status_base = "Пауза"
            self.pause_btn.configure(text="Продовжити")
            self._write_control_command("pause")
            self.current_task_lbl.configure(
                text="Пауза запитана. Зупинка після поточної декларації."
            )
            self.append_log("\n[INFO] Запит паузи надіслано.\n", "info_tag")
        else:
            self.status_base = "Виконується"
            self.pause_btn.configure(text="Пауза")
            self._write_control_command("run")
            self.current_task_lbl.configure(text="Відновлено виконання.")
            self.append_log("\n[INFO] Виконання відновлено.\n", "info_tag")

    def stop_run(self) -> None:
        if not self.is_running:
            return
        self.stop_requested = True
        self.status_base = "Зупинка"
        self._write_control_command("stop")
        self.current_task_lbl.configure(
            text="Безпечна зупинка запитана. Чекаємо завершення поточної декларації."
        )
        self.append_log("\n[INFO] Запит безпечної зупинки надіслано.\n", "info_tag")

    # ── Output consumption ───────────────────────────────────────────────────

    def _consume_output_line(self, line: str) -> None:
        tag = self._tag_for_line(line)
        self.append_log(line, tag)
        match = self._progress_re.search(line)
        if match:
            cur, total, status, file_name = match.groups()
            status_ua = "успішно" if status == "OK" else "помилка"
            self.current_task_lbl.configure(
                text=f"Аналіз: {cur}/{total} | {status_ua} | {file_name.strip()}"
            )
            try:
                n, m = int(cur), int(total)
                if m > 0:
                    pct = n / m * 100
                    if not self._progress_determinate:
                        self.progress.stop()
                        self.progress.configure(mode="determinate")
                        self._progress_determinate = True
                    self.progress.configure(value=pct)
            except (ValueError, TypeError):
                pass

    def _run_cmd(self, cmd: list[str], title: str) -> int:
        self.root.after(0, lambda: self.append_log(f"\n[{title}] {' '.join(cmd)}\n", "info_tag"))
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self.current_proc = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            self.root.after(0, lambda ln=line: self._consume_output_line(ln))
        return proc.wait()

    def _run_pipeline(self, cfg: dict) -> None:
        report_ready = False
        try:
            self.root.after(0, lambda: self.current_task_lbl.configure(text="Запуск аналізу..."))
            main_cmd = [
                sys.executable,
                str(MAIN_SCRIPT),
                "--input-dir",
                cfg["input_dir"],
                "--output",
                cfg["output_jsonl"],
                "--errors-output",
                cfg["errors_jsonl"],
                "--model",
                cfg["model"],
                "--host",
                cfg["host"],
                "--timeout",
                str(cfg["timeout"]),
                "--max-files",
                str(cfg["max_files"]),
                "--max-chars",
                str(cfg["max_chars"]),
                "--retries",
                str(cfg["retries"]),
                "--retry-delay",
                str(cfg["retry_delay"]),
                "--num-predict",
                str(cfg["num_predict"]),
                "--control-file",
                str(self.control_file),
                "--on-limit",
                "fail-run",
            ]
            if cfg["move_processed"]:
                proc_path = cfg["processed_dir"]
                if proc_path:
                    main_cmd.extend(["--processed-dir", proc_path])
            main_cmd.append("--no-save-compact-declarations")
            code = self._run_cmd(main_cmd, "АНАЛІЗ МОДЕЛІ")
            if code != 0:
                self.root.after(
                    0, lambda: self.append_log(f"\n[ПОМИЛКА] аналіз не завершився: exit={code}\n", "err_tag")
                )
                return

            if self.stop_requested:
                self.root.after(
                    0,
                    lambda: self.append_log(
                        "\n[INFO] Зупинка виконана. Формування звіту пропущено.\n", "info_tag"
                    ),
                )
                return

            if cfg["make_report"]:
                self.root.after(
                    0, lambda: self.current_task_lbl.configure(text="Формування звітів...")
                )
                report_cmd = [
                    sys.executable,
                    str(REPORT_SCRIPT),
                    "--input",
                    cfg["output_jsonl"],
                    "--errors-input",
                    cfg["errors_jsonl"],
                    "--summary-csv",
                    cfg["summary_csv"],
                    "--findings-csv",
                    cfg["findings_csv"],
                    "--table-html",
                    cfg["table_html"],
                ]
                if cfg["no_dedupe"]:
                    report_cmd.append("--no-dedupe")
                code = self._run_cmd(report_cmd, "ФОРМУВАННЯ ЗВІТУ")
                if code != 0:
                    self.root.after(
                        0, lambda: self.append_log(f"\n[ПОМИЛКА] звіт не зібрано: exit={code}\n", "err_tag")
                    )
                    return
                report_ready = True

                try:
                    from main import is_under_project_deep_research
                    from dossier_html_summary import run_dossier_table_summary_append

                    in_path = Path(cfg["input_dir"])
                    if not in_path.is_absolute():
                        in_path = BASE_DIR / in_path
                    if is_under_project_deep_research(in_path):
                        th = Path(cfg["table_html"])
                        if not th.is_absolute():
                            th = BASE_DIR / th
                        try:
                            from dossier_charts_html import append_dossier_charts_to_html

                            err_p = Path(cfg["errors_jsonl"])
                            if not err_p.is_absolute():
                                err_p = BASE_DIR / err_p
                            out_p = Path(cfg["output_jsonl"])
                            if not out_p.is_absolute():
                                out_p = BASE_DIR / out_p
                            self.root.after(
                                0,
                                lambda: self.append_log(
                                    "\n=== Графіки досьє (HTML) ===\n",
                                    "info_tag",
                                ),
                            )
                            _ok_ch, ch_msg = append_dossier_charts_to_html(
                                th,
                                input_dir=in_path,
                                output_jsonl=out_p,
                                errors_jsonl=err_p,
                                base_dir=BASE_DIR,
                                no_dedupe=bool(cfg.get("no_dedupe")),
                            )
                            self.root.after(
                                0,
                                lambda m=ch_msg: self.append_log(m + "\n", "info_tag"),
                            )
                        except Exception as exc_ch:  # noqa: BLE001
                            self.root.after(
                                0,
                                lambda e=exc_ch: self.append_log(
                                    f"[Досьє/Charts] {e}\n",
                                    "err_tag",
                                ),
                            )
                        self.root.after(
                            0,
                            lambda: self.append_log(
                                "\n=== Підсумок досьє (LLM по HTML-звіту) ===\n",
                                "info_tag",
                            ),
                        )
                        ok_dr, dr_msg = run_dossier_table_summary_append(
                            table_html_path=th,
                            model=cfg["model"],
                            host=cfg["host"],
                            timeout_sec=cfg["timeout"],
                        )
                        self.root.after(
                            0,
                            lambda m=dr_msg: self.append_log(m + "\n", "info_tag"),
                        )
                        if not ok_dr:
                            self.root.after(
                                0,
                                lambda: self.append_log(
                                    "[INFO] Табличний звіт лишається без змін; аналіз успішний.\n",
                                    "info_tag",
                                ),
                            )
                except Exception as exc:  # noqa: BLE001
                    self.root.after(
                        0,
                        lambda e=exc: self.append_log(
                            f"[Досьє] Помилка підсумку: {e}\n",
                            "err_tag",
                        ),
                    )

            self.root.after(0, lambda: self.append_log("\n[OK] Готово. Пайплайн завершено.\n", "done_tag"))
            self.root.after(0, self._check_errors_after_run)
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, lambda e=exc: self.append_log(f"\n[ПОМИЛКА] {e}\n", "err_tag"))
        finally:
            rr = report_ready
            self.root.after(0, lambda: self.set_running_state(False, report_ready=rr))


def main() -> None:
    root = Tk()
    app = LauncherApp(root)

    def _on_close() -> None:
        proc = getattr(app, "current_proc", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
