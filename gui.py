import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import sender


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bot Sender")
        self.geometry("860x640")
        self.minsize(820, 600)

        self.config_path = "config.json"
        self.env_path = ".env"

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._sending = False

        self._build_style()
        self._build_ui()
        self._load_data()
        self.after(100, self._drain_log)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f6f7fb")
        style.configure("TLabel", background="#f6f7fb", foreground="#1f2937")
        style.configure("TButton", padding=6)
        style.configure("Header.TLabel", font=("DejaVu Sans", 14, "bold"))
        style.configure("Section.TLabel", font=("DejaVu Sans", 11, "bold"))

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Label(container, text="Рассылка в Telegram и VK", style="Header.TLabel")
        header.pack(anchor=tk.W, pady=(0, 8))

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.message_tab = ttk.Frame(notebook, padding=12)
        self.telegram_tab = ttk.Frame(notebook, padding=12)
        self.vk_tab = ttk.Frame(notebook, padding=12)
        self.settings_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.message_tab, text="Сообщение")
        notebook.add(self.telegram_tab, text="Telegram")
        notebook.add(self.vk_tab, text="VK")
        notebook.add(self.settings_tab, text="Настройки")

        self._build_message_tab()
        self._build_telegram_tab()
        self._build_vk_tab()
        self._build_settings_tab()

        footer = ttk.Frame(container)
        footer.pack(fill=tk.X, pady=(12, 0))

        self.dry_run_var = tk.BooleanVar(value=False)
        dry_run = ttk.Checkbutton(footer, text="Тестовый прогон (без отправки)", variable=self.dry_run_var)
        dry_run.pack(side=tk.LEFT)

        self.send_button = ttk.Button(footer, text="Отправить", command=self._on_send)
        self.send_button.pack(side=tk.RIGHT)

        save_button = ttk.Button(footer, text="Сохранить настройки", command=self._on_save)
        save_button.pack(side=tk.RIGHT, padx=(0, 8))

    def _build_message_tab(self) -> None:
        message_frame = ttk.Frame(self.message_tab)
        message_frame.pack(fill=tk.BOTH, expand=True)

        helper = ttk.Label(
            message_frame,
            text="Поддерживаются шаблоны: {date}, {time}, {datetime}",
        )
        helper.pack(anchor=tk.W, pady=(0, 6))

        self.message_text = tk.Text(message_frame, height=14, wrap=tk.WORD)
        self.message_text.pack(fill=tk.BOTH, expand=True)

        log_label = ttk.Label(message_frame, text="Лог", style="Section.TLabel")
        log_label.pack(anchor=tk.W, pady=(10, 4))

        self.log_text = tk.Text(message_frame, height=8, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=False)

        clear_button = ttk.Button(message_frame, text="Очистить лог", command=self._clear_log)
        clear_button.pack(anchor=tk.E, pady=(6, 0))

    def _build_telegram_tab(self) -> None:
        enabled_frame = ttk.Frame(self.telegram_tab)
        enabled_frame.pack(anchor=tk.W, pady=(0, 8))

        self.telegram_enabled = tk.BooleanVar(value=True)
        enabled = ttk.Checkbutton(enabled_frame, text="Включить Telegram", variable=self.telegram_enabled)
        enabled.pack(anchor=tk.W)

        token_frame = ttk.Frame(self.telegram_tab)
        token_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(token_frame, text="Bot token").pack(anchor=tk.W)
        self.telegram_token = tk.StringVar()
        self.telegram_token_entry = ttk.Entry(token_frame, textvariable=self.telegram_token, show="*")
        self.telegram_token_entry.pack(fill=tk.X)

        self.telegram_show_token = tk.BooleanVar(value=False)
        show_box = ttk.Checkbutton(
            token_frame,
            text="Показать токен",
            variable=self.telegram_show_token,
            command=self._toggle_telegram_token,
        )
        show_box.pack(anchor=tk.W, pady=(4, 0))

        targets_label = ttk.Label(self.telegram_tab, text="Список chat_id (каждый с новой строки)")
        targets_label.pack(anchor=tk.W)
        self.telegram_targets = tk.Text(self.telegram_tab, height=10, wrap=tk.WORD)
        self.telegram_targets.pack(fill=tk.BOTH, expand=True)

    def _build_vk_tab(self) -> None:
        enabled_frame = ttk.Frame(self.vk_tab)
        enabled_frame.pack(anchor=tk.W, pady=(0, 8))

        self.vk_enabled = tk.BooleanVar(value=True)
        enabled = ttk.Checkbutton(enabled_frame, text="Включить VK", variable=self.vk_enabled)
        enabled.pack(anchor=tk.W)

        token_frame = ttk.Frame(self.vk_tab)
        token_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(token_frame, text="Access token").pack(anchor=tk.W)
        self.vk_token = tk.StringVar()
        self.vk_token_entry = ttk.Entry(token_frame, textvariable=self.vk_token, show="*")
        self.vk_token_entry.pack(fill=tk.X)

        self.vk_show_token = tk.BooleanVar(value=False)
        show_box = ttk.Checkbutton(
            token_frame,
            text="Показать токен",
            variable=self.vk_show_token,
            command=self._toggle_vk_token,
        )
        show_box.pack(anchor=tk.W, pady=(4, 0))

        targets_label = ttk.Label(self.vk_tab, text="Список peer_id (каждый с новой строки)")
        targets_label.pack(anchor=tk.W)
        self.vk_targets = tk.Text(self.vk_tab, height=10, wrap=tk.WORD)
        self.vk_targets.pack(fill=tk.BOTH, expand=True)

    def _build_settings_tab(self) -> None:
        settings_frame = ttk.Frame(self.settings_tab)
        settings_frame.pack(fill=tk.BOTH, expand=True)

        interval_label = ttk.Label(settings_frame, text="Интервал между отправками (сек)")
        interval_label.pack(anchor=tk.W)
        self.interval_value = tk.StringVar(value="2")
        interval_entry = ttk.Entry(settings_frame, textvariable=self.interval_value)
        interval_entry.pack(fill=tk.X, pady=(0, 8))

        telegram_interval_label = ttk.Label(settings_frame, text="Интервал Telegram (сек, пусто = общий)")
        telegram_interval_label.pack(anchor=tk.W)
        self.telegram_interval_value = tk.StringVar()
        telegram_interval_entry = ttk.Entry(settings_frame, textvariable=self.telegram_interval_value)
        telegram_interval_entry.pack(fill=tk.X, pady=(0, 8))

        vk_interval_label = ttk.Label(settings_frame, text="Интервал VK (сек, пусто = общий)")
        vk_interval_label.pack(anchor=tk.W)
        self.vk_interval_value = tk.StringVar()
        vk_interval_entry = ttk.Entry(settings_frame, textvariable=self.vk_interval_value)
        vk_interval_entry.pack(fill=tk.X, pady=(0, 8))

        parse_label = ttk.Label(settings_frame, text="Telegram parse_mode")
        parse_label.pack(anchor=tk.W)
        self.parse_mode_value = tk.StringVar()
        parse_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.parse_mode_value,
            values=["", "HTML", "MarkdownV2"],
            state="readonly",
        )
        parse_combo.pack(fill=tk.X, pady=(0, 8))

        vk_label = ttk.Label(settings_frame, text="VK API version")
        vk_label.pack(anchor=tk.W)
        self.vk_api_value = tk.StringVar(value="5.199")
        vk_entry = ttk.Entry(settings_frame, textvariable=self.vk_api_value)
        vk_entry.pack(fill=tk.X, pady=(0, 8))

        self.avoid_duplicate_var = tk.BooleanVar(value=True)
        avoid_box = ttk.Checkbutton(
            settings_frame,
            text="Не отправлять повтор, если последний текст совпадает",
            variable=self.avoid_duplicate_var,
        )
        avoid_box.pack(anchor=tk.W, pady=(4, 0))

        hint = ttk.Label(
            settings_frame,
            text="Подсказка: токены сохраняются в .env, остальное - в config.json",
        )
        hint.pack(anchor=tk.W, pady=(8, 0))

    def _toggle_telegram_token(self) -> None:
        self.telegram_token_entry.configure(show="" if self.telegram_show_token.get() else "*")

    def _toggle_vk_token(self) -> None:
        self.vk_token_entry.configure(show="" if self.vk_show_token.get() else "*")

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _log(self, message: str) -> None:
        self._log_queue.put(message)

    def _drain_log(self) -> None:
        while not self._log_queue.empty():
            message = self._log_queue.get()
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.configure(state=tk.DISABLED)
            self.log_text.see(tk.END)
        self.after(120, self._drain_log)

    def _load_data(self) -> None:
        config = sender.load_config(self.config_path, allow_missing=True)
        env_data = sender.read_env(self.env_path)

        settings = config.get("settings", {})
        self.interval_value.set(str(settings.get("interval_seconds", 2)))
        telegram_interval = settings.get("telegram_interval_seconds")
        self.telegram_interval_value.set("" if telegram_interval in (None, "") else str(telegram_interval))
        vk_interval = settings.get("vk_interval_seconds")
        self.vk_interval_value.set("" if vk_interval in (None, "") else str(vk_interval))
        self.parse_mode_value.set(str(settings.get("telegram_parse_mode", "")))
        self.vk_api_value.set(str(settings.get("vk_api_version", "5.199")))
        self.avoid_duplicate_var.set(bool(settings.get("avoid_duplicate", True)))

        telegram = config.get("telegram", {})
        self.telegram_enabled.set(bool(telegram.get("enabled", True)))
        telegram_targets = "\n".join(str(t) for t in telegram.get("targets", []))
        self.telegram_targets.delete("1.0", tk.END)
        self.telegram_targets.insert(tk.END, telegram_targets)

        vk = config.get("vk", {})
        self.vk_enabled.set(bool(vk.get("enabled", True)))
        vk_targets = "\n".join(str(t) for t in vk.get("targets", []))
        self.vk_targets.delete("1.0", tk.END)
        self.vk_targets.insert(tk.END, vk_targets)

        self.telegram_token.set(env_data.get("TELEGRAM_BOT_TOKEN", ""))
        self.vk_token.set(env_data.get("VK_ACCESS_TOKEN", ""))

    def _parse_targets(self, raw_text: str) -> list[int]:
        ids: list[int] = []
        for raw in raw_text.replace(",", "\n").splitlines():
            value = raw.strip()
            if not value:
                continue
            try:
                ids.append(int(value))
            except ValueError as exc:
                raise ValueError(f"Некорректный ID: {value}") from exc
        return ids

    def _collect_config(self) -> dict:
        interval_value = float(self.interval_value.get())
        config = sender.default_config()
        config["settings"]["interval_seconds"] = interval_value
        telegram_interval = self.telegram_interval_value.get().strip()
        config["settings"]["telegram_interval_seconds"] = (
            None if telegram_interval == "" else float(telegram_interval)
        )
        vk_interval = self.vk_interval_value.get().strip()
        config["settings"]["vk_interval_seconds"] = None if vk_interval == "" else float(vk_interval)
        parse_mode = self.parse_mode_value.get().strip()
        config["settings"]["telegram_parse_mode"] = parse_mode
        config["settings"]["vk_api_version"] = self.vk_api_value.get().strip() or "5.199"
        config["settings"]["avoid_duplicate"] = self.avoid_duplicate_var.get()

        config["telegram"]["enabled"] = self.telegram_enabled.get()
        config["telegram"]["targets"] = self._parse_targets(self.telegram_targets.get("1.0", tk.END))

        config["vk"]["enabled"] = self.vk_enabled.get()
        config["vk"]["targets"] = self._parse_targets(self.vk_targets.get("1.0", tk.END))

        return config

    def _on_save(self) -> None:
        try:
            config = self._collect_config()
            sender.save_config(self.config_path, config)
            sender.write_env(
                self.env_path,
                {
                    "TELEGRAM_BOT_TOKEN": self.telegram_token.get().strip(),
                    "VK_ACCESS_TOKEN": self.vk_token.get().strip(),
                },
            )
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        messagebox.showinfo("Готово", "Настройки сохранены")

    def _on_send(self) -> None:
        if self._sending:
            return
        try:
            config = self._collect_config()
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))
            return

        message = self.message_text.get("1.0", tk.END).strip()
        if not message:
            messagebox.showwarning("Сообщение", "Введите текст сообщения")
            return

        try:
            message = sender.render_template(message)
        except Exception as exc:
            messagebox.showerror("Ошибка шаблона", str(exc))
            return

        interval = float(config["settings"].get("interval_seconds", 2))
        dry_run = self.dry_run_var.get()
        telegram_token = self.telegram_token.get().strip()
        vk_token = self.vk_token.get().strip()

        self._sending = True
        self.send_button.configure(state=tk.DISABLED)
        self._log("--- start ---")

        thread = threading.Thread(
            target=self._send_worker,
            args=(message, config, telegram_token, vk_token, interval, dry_run),
            daemon=True,
        )
        thread.start()

    def _send_worker(
        self,
        message: str,
        config: dict,
        telegram_token: str,
        vk_token: str,
        interval: float,
        dry_run: bool,
    ) -> None:
        try:
            sender.send_all(message, config, telegram_token, vk_token, interval, dry_run, self._log)
        except Exception as exc:
            self._log(f"error: {exc}")
        finally:
            self._log("--- end ---")
            self.after(0, self._finish_send)

    def _finish_send(self) -> None:
        self._sending = False
        self.send_button.configure(state=tk.NORMAL)


if __name__ == "__main__":
    app = App()
    app.mainloop()
