"""SPIKE 2 VPX desktop player."""

import os
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from spike2_vpx.player import STERN_IMAGES, Player, artwork_paths, folder_images, image_version, supported_tables
from spike2_vpx_setup import ROWS, VIRTUALIZATION_HELP, VPX_RELEASE, Setup
from spike2_vpx import backglass, cabinet, lighting, sessions, support
import padisplay
import padlaunch
import play_spike2


LAUNCH_STAGES = ("Checking files", "Starting Stern", "Connecting controller", "Opening VPX")
BACKGROUND, SURFACE, TEXT, MUTED, ACCENT = "#11151c", "#1b2330", "#edf2f7", "#acbbcd", "#79ddc5"
LCD_FULLSCREEN_MODE = "Borderless fullscreen"
LCD_WINDOWED_MODE = "Windowed"


def configure_style(root):
    root.configure(background=BACKGROUND)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Segoe UI", 10), background=BACKGROUND, foreground=TEXT,
                    bordercolor="#46556a", lightcolor=SURFACE, darkcolor=SURFACE,
                    fieldbackground=SURFACE, selectbackground="#334a60", selectforeground=TEXT,
                    arrowcolor=TEXT, insertcolor=TEXT, troughcolor=BACKGROUND)
    style.configure("Heading.TLabel", font=("Segoe UI", 26, "bold"))
    style.configure("Game.TLabel", font=("Segoe UI", 23, "bold"))
    style.configure("CabinetTitle.TLabel", font=("Segoe UI", 38, "bold"))
    style.configure("CabinetText.TLabel", font=("Segoe UI", 17))
    style.configure("Section.TLabel", font=("Segoe UI", 12, "bold"))
    style.configure("Hint.TLabel", foreground=MUTED)
    style.configure("TButton", background=SURFACE, padding=(10, 5))
    style.map("TButton", background=[("active", "#35475d")], foreground=[("disabled", "#8595a8")])
    style.configure("Primary.TButton", background=ACCENT, foreground=BACKGROUND, padding=(18, 9),
                    font=("Segoe UI", 12, "bold"))
    style.map("Primary.TButton", background=[("disabled", SURFACE), ("active", "#acf1e1")],
              bordercolor=[("focus", TEXT)])
    # clam lights a checkbox's background when it is disabled or hovered: a pale box on the dark window
    style.map("TCheckbutton", background=[("disabled", BACKGROUND), ("active", BACKGROUND)],
              foreground=[("disabled", "#8595a8")])
    style.configure("GameCard.TButton", anchor="w", justify="left", padding=(12, 10),
                    background=SURFACE, font=("Segoe UI", 11))
    style.map("GameCard.TButton", background=[("active", "#35475d")], bordercolor=[("focus", ACCENT)])
    style.configure("SelectedCard.TButton", anchor="w", justify="left", padding=(12, 10),
                    background="#324c61", bordercolor=ACCENT, font=("Segoe UI", 11, "bold"))
    style.configure("TNotebook.Tab", background=SURFACE, padding=(13, 7))
    style.map("TNotebook.Tab", background=[("selected", "#32465d")],
              foreground=[("selected", TEXT)])
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, rowheight=30)
    style.configure("Treeview.Heading", background=SURFACE, foreground=TEXT)
    style.map("Treeview", background=[("selected", "#355570")], foreground=[("selected", TEXT)])
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
              selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)


def artwork_preview(root, path, width, height):
    if not path:
        return None
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(12_000_001)
    except (OSError, ValueError):
        return None
    return photo_preview(root, data, width, height)


def photo_preview(root, data, width, height):
    if len(data) > 12_000_000:
        return None
    header = data[:24]
    if header.startswith(backglass.PNG) and len(header) == 24:
        size = (int.from_bytes(header[16:20]), int.from_bytes(header[20:24]))
    elif header.startswith((b"GIF87a", b"GIF89a")) and len(header) >= 10:
        size = (int.from_bytes(header[6:8], "little"), int.from_bytes(header[8:10], "little"))
    else:
        return None
    if any(not 0 < side <= 6000 for side in size) or size[0] * size[1] > 16_000_000:
        return None
    try:
        image = tk.PhotoImage(master=root, data=b64encode(data))
        scale = max(1, (image.width() + width - 1) // width, (image.height() + height - 1) // height)
        return image.subsample(scale)
    except tk.TclError:
        return None


def game_preview(root, game, width, height):
    if game:
        for path in artwork_paths(game):
            preview = artwork_preview(root, path, width, height)
            if preview:
                return preview
    return None


class PlayerWindow:
    def __init__(self, root, setup):
        self.root = root
        self.setup = setup
        self.player = Player(setup)
        self.results = queue.Queue()
        self.preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backglass-preview")
        self.preview_identity = None
        self.preview_job = None
        self.busy = False
        self.playing = False
        self.checks = {}
        self.game = None
        self.cache_note = ""
        self.first_check = True
        self.cabinet_mode = False
        self.recover_game = None
        self.launch_error_game = None
        self.launching = False
        self.last_stage = ""
        self.lighting_notice = ""
        self.details_open = False
        root.title("SPIKE 2 VPX")
        root.geometry("960x730")
        root.minsize(840, 660)
        root.protocol("WM_DELETE_WINDOW", self.close)

        configure_style(root)
        self.page = page = ttk.Frame(root, padding=(24, 18))
        page.pack(fill="both", expand=True)
        header = ttk.Frame(page)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="SPIKE 2 VPX", style="Heading.TLabel").pack(side="left")
        ttk.Button(header, text="Cabinet mode  ·  F11", command=self.toggle_cabinet).pack(side="right")
        root.bind("<F11>", lambda _: self.toggle_cabinet())
        self.tabs = ttk.Notebook(page)
        self.tabs.pack(fill="both", expand=True)
        self.games_page = ttk.Frame(self.tabs, padding=18)
        self.tables_page = ttk.Frame(self.tabs, padding=18)
        self.setup_page = ttk.Frame(self.tabs, padding=18)
        self.settings_page = ttk.Frame(self.tabs, padding=18)
        self.cabinet_page = ttk.Frame(self.tabs, padding=18)
        self.lighting_page = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(self.games_page, text="Games")
        self.tabs.add(self.tables_page, text="Supported Tables")
        self.tabs.add(self.setup_page, text="Setup")
        self.tabs.add(self.cabinet_page, text="Cabinet")
        self.tabs.add(self.lighting_page, text="Lighting")
        self.tabs.add(self.settings_page, text="Settings")

        self.build_games()
        self.build_supported_tables()
        self.build_setup()
        self.build_cabinet()
        self.lighting = lighting.LightingPage(self, self.lighting_page)
        self.build_settings()
        self.build_cabinet_mode()

        status = ttk.Frame(page)
        status.pack(fill="x", pady=(12, 0))
        self.summary = ttk.Label(status, wraplength=650, justify="left")
        self.summary.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=110)
        self.progress.pack(side="right", padx=(12, 0))
        self.tabs.select(self.setup_page)
        self.reload_library()
        self.check_again()
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed, add="+")

    def build_games(self):
        page = self.games_page
        library = ttk.Frame(page, width=250)
        library.pack(side="left", fill="y", padx=(0, 20))
        ttk.Label(library, text="Game library", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        shelf = ttk.Frame(library)
        shelf.pack(fill="both", expand=True)
        self.library_filter = tk.StringVar(value="All games")
        filters = ttk.Combobox(library, textvariable=self.library_filter,
                               values=("All games", "Favorites", "Recently played"), state="readonly", width=24)
        filters.pack(fill="x", before=shelf, pady=(0, 8))
        filters.bind("<<ComboboxSelected>>", lambda _: self.reload_library())
        self.library_canvas = tk.Canvas(shelf, width=255, highlightthickness=0, background=BACKGROUND)
        scroll = ttk.Scrollbar(shelf, orient="vertical", command=self.library_canvas.yview)
        self.library_canvas.configure(yscrollcommand=scroll.set)
        self.library_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.cards = ttk.Frame(self.library_canvas)
        cards_window = self.library_canvas.create_window(0, 0, anchor="nw", window=self.cards)
        self.cards.bind("<Configure>", lambda _: self.library_canvas.configure(
            scrollregion=self.library_canvas.bbox("all")))
        self.library_canvas.bind("<Configure>", lambda event: self.library_canvas.itemconfigure(
            cards_window, width=event.width))
        self.library_canvas.bind("<MouseWheel>", self.scroll_library)
        self.library_hint = ttk.Label(library, style="Hint.TLabel", wraplength=230)
        self.library_hint.pack(anchor="w", pady=(6, 0))
        self.remove_button = ttk.Button(library, text="Remove pairing…", command=self.remove_game)
        self.remove_button.pack(anchor="w", pady=(10, 0))

        detail = ttk.Frame(page)
        detail.pack(side="left", fill="both", expand=True)
        hero = ttk.Frame(detail)
        hero.pack(fill="x", pady=(0, 10))
        self.game_art = ttk.Label(hero)
        self.game_art.pack(side="right", padx=(8, 0))
        self.game_title = ttk.Label(hero, style="Game.TLabel", wraplength=385)
        self.game_title.pack(anchor="w")
        self.game_facts = ttk.Label(hero, style="Hint.TLabel", wraplength=380, justify="left")
        self.game_facts.pack(anchor="w", pady=(4, 0))
        image = self.image_panel = ttk.LabelFrame(detail, text="Prepare image", padding=10)
        image.pack(fill="x", pady=(0, 8))
        images = ttk.Frame(image)
        images.pack(fill="x", pady=(8, 0))
        self.image_button = ttk.Button(images, text="Import image…", command=self.choose_image)
        self.image_button.pack(side="left")
        self.folder_button = ttk.Button(images, text="Choose folder…", command=self.choose_folder)
        self.folder_button.pack(side="left", padx=(0, 8))
        ttk.Button(images, text="Get image from Stern", command=self.get_image).pack(side="left")

        table = self.table_panel = ttk.LabelFrame(detail, text="Prepare table", padding=10)
        table.pack(fill="x", pady=(0, 8))
        pairing = ttk.Frame(table)
        pairing.pack(fill="x", pady=(8, 0))
        self.table_button = ttk.Button(pairing, text="Choose table…", command=self.choose_table)
        self.table_button.pack(side="left")
        self.backglass_button = ttk.Button(pairing, text="Attach backglass…", command=self.attach_backglass)
        self.backglass_button.pack(side="left", padx=(8, 0))

        actions = ttk.Frame(detail)
        actions.pack(fill="x", pady=(4, 8), before=image)
        self.play_button = ttk.Button(actions, style="Primary.TButton", command=self.next_game_step)
        self.play_button.pack(side="left")
        self.export_button = ttk.Button(actions, text="Export launch script…", command=self.export_game)
        self.export_button.pack(side="left", padx=(8, 0))
        # VR is a play-time choice, remembered; shown once Setup finds a VR player
        self.vr_var = tk.BooleanVar(value=self.setup.vr_wanted())
        self.vr_check = ttk.Checkbutton(actions, text="Enable VR", variable=self.vr_var, command=self.toggle_vr)
        self.play_hint = ttk.Label(detail, style="Hint.TLabel", wraplength=440, justify="left")
        self.play_hint.pack(anchor="w", pady=(0, 8), before=image)
        self.vpx_hint = ttk.Label(detail, style="Hint.TLabel", wraplength=440, justify="left")
        self.vpx_hint.pack(anchor="w", pady=(8, 0))
        tools = ttk.Frame(detail)
        tools.pack(fill="x", pady=(8, 0))
        self.details_button = ttk.Button(tools, text="Show details", command=self.toggle_details)
        self.details_button.pack(side="left")
        self.favorite_button = ttk.Button(tools, text="Favorite", command=self.favorite)
        self.favorite_button.pack(side="left", padx=6)
        self.art_button = ttk.Button(tools, text="Choose artwork…", command=self.choose_artwork)
        self.art_button.pack(side="left")
        self.detail_panel = ttk.Frame(detail)
        self.file_details = ttk.Label(self.detail_panel, wraplength=460, justify="left", style="Hint.TLabel")
        self.file_details.pack(anchor="w")
        details_actions = ttk.Frame(self.detail_panel)
        details_actions.pack(anchor="w", pady=5)
        ttk.Button(details_actions, text="Open logs", command=self.open_logs).pack(side="left")
        self.clear_art = ttk.Button(details_actions, text="Remove artwork", command=lambda: self.edit_game(artwork=""))
        self.clear_art.pack(side="left", padx=6)
        self.launch_text = tk.StringVar()
        ttk.Label(detail, textvariable=self.launch_text, style="Hint.TLabel", wraplength=460,
                  justify="left").pack(anchor="w", pady=(5, 0))

    def build_supported_tables(self):
        page = self.tables_page
        ttk.Label(page, text="Supported SPIKE 2 games", style="Section.TLabel").pack(anchor="w")
        ttk.Label(page, text="Choose the VPX table and version listed for your game. "
                             "You supply the SD-card image and table.", wraplength=700).pack(
            anchor="w", pady=(4, 10))
        search = ttk.Frame(page)
        search.pack(fill="x", pady=(0, 8))
        self.table_filter = tk.StringVar()
        ttk.Label(search, text="Search games or tables").pack(side="left")
        ttk.Entry(search, textvariable=self.table_filter).pack(side="left", fill="x", expand=True,
                                                               padx=(10, 0))
        results = ttk.Frame(page)
        results.pack(fill="both", expand=True)
        self.catalog = ttk.Treeview(results, columns=("game", "table"), show="headings", selectmode="browse")
        self.catalog.heading("game", text="SPIKE 2 game")
        self.catalog.heading("table", text="Compatible VPX table")
        self.catalog.column("game", width=200, minwidth=140, stretch=False)
        self.catalog.column("table", width=550, minwidth=280)
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.catalog.yview)
        self.catalog.configure(yscrollcommand=scroll.set)
        self.catalog.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        footer = ttk.Frame(page)
        footer.pack(fill="x", pady=(10, 0))
        self.catalog_detail = ttk.Label(footer, style="Hint.TLabel", wraplength=530)
        self.catalog_detail.pack(side="left", fill="x", expand=True)
        self.table_page_button = ttk.Button(footer, text="Open table page", command=self.open_table_page)
        self.table_page_button.pack(side="right", padx=(12, 0))
        self.table_rows = supported_tables()
        self.catalog.bind("<<TreeviewSelect>>", self.show_supported_table)
        self.table_filter.trace_add("write", self.filter_supported_tables)
        self.filter_supported_tables()

    def filter_supported_tables(self, *_):
        terms = self.table_filter.get().casefold().split()
        self.catalog.delete(*self.catalog.get_children())
        for index, row in enumerate(self.table_rows):
            description = f"{row.game} {row.table}".casefold()
            if all(term in description for term in terms):
                self.catalog.insert("", "end", iid=str(index), values=(row.game, row.table))
        self.show_supported_table()

    def show_supported_table(self, _event=None):
        selected = self.catalog.selection()
        row = self.table_rows[int(selected[0])] if selected else None
        if row:
            details = []
            if row.author:
                details.append(f"Table by {row.author}.")
            if not row.url:
                details.append("No table page is listed for this version.")
            self.catalog_detail.configure(text=" ".join(details))
        else:
            count = len(self.catalog.get_children())
            self.catalog_detail.configure(text=f"{count} compatible table entries." if count else
                                          "No compatible table entries match this search.")
        self.table_page_button.state(["!disabled"] if row and row.url else ["disabled"])

    def open_table_page(self):
        selected = self.catalog.selection()
        if selected and (url := self.table_rows[int(selected[0])].url):
            webbrowser.open(url)

    def build_cabinet_mode(self):
        self.cockpit = ttk.Frame(self.root, padding=36)
        header = ttk.Frame(self.cockpit)
        header.pack(fill="x", pady=(0, 20))
        ttk.Label(header, text="SPIKE 2 VPX", style="Heading.TLabel").pack(side="left")
        ttk.Button(header, text="Exit cabinet mode", command=self.toggle_cabinet).pack(side="right")
        body = ttk.Frame(self.cockpit)
        body.pack(fill="both", expand=True)
        self.cabinet_list = tk.Listbox(body, width=28, font=("Segoe UI", 20, "bold"),
                                      background=SURFACE, foreground=TEXT, exportselection=False,
                                      selectbackground="#355570", selectforeground=TEXT,
                                      highlightbackground="#46556a", highlightcolor=ACCENT,
                                      highlightthickness=3, activestyle="none")
        self.cabinet_list.pack(side="left", fill="y", padx=(0, 28))
        self.cabinet_list.bind("<<ListboxSelect>>", self.select_cabinet_game)
        detail = ttk.Frame(body)
        detail.pack(side="left", fill="both", expand=True)
        self.cabinet_art = ttk.Label(detail)
        self.cabinet_art.pack(anchor="w")
        self.cabinet_title = ttk.Label(detail, style="CabinetTitle.TLabel", wraplength=650)
        self.cabinet_title.pack(anchor="w")
        self.cabinet_facts = ttk.Label(detail, style="CabinetText.TLabel", wraplength=630, justify="left")
        self.cabinet_facts.pack(anchor="w", pady=(6, 18))
        self.cabinet_play = ttk.Button(detail, style="Primary.TButton", command=self.next_game_step)
        self.cabinet_play.pack(anchor="w", pady=(0, 10))
        self.cabinet_status = ttk.Label(detail, style="CabinetText.TLabel", wraplength=630, justify="left")
        self.cabinet_status.pack(anchor="w")
        ttk.Label(detail, textvariable=self.launch_text, style="CabinetText.TLabel",
                  wraplength=630, justify="left").pack(anchor="w")
        ttk.Label(self.cockpit, text="Up / Down or Shift keys to browse  ·  Enter to select  ·  Esc to exit",
                  style="Hint.TLabel").pack(anchor="w", pady=(20, 0))
        self.cabinet_list.bind("<Return>", lambda _: self.cabinet_play.invoke())
        self.cabinet_list.bind("<space>", lambda _: self.cabinet_play.invoke())
        self.cabinet_list.bind("<Shift_L>", lambda _: self.move_cabinet(-1))
        self.cabinet_list.bind("<Shift_R>", lambda _: self.move_cabinet(1))
        self.root.bind("<Escape>", lambda _: self.toggle_cabinet() if self.cabinet_mode else None)

    def toggle_cabinet(self):
        if self.busy:
            return
        self.cabinet_mode = not self.cabinet_mode
        if self.cabinet_mode:
            self.page.pack_forget()
            self.cockpit.pack(fill="both", expand=True)
            self.root.attributes("-fullscreen", True)
            self.reload_cabinet(self.game, choose_first=True)
            self.cabinet_list.focus_set()
        else:
            self.root.attributes("-fullscreen", False)
            self.cockpit.pack_forget()
            self.page.pack(fill="both", expand=True)

    def reload_cabinet(self, selected, choose_first=False):
        self.cabinet_games = sorted(self.saved, key=lambda game: (not game.favorite, game.name.casefold()))
        self.cabinet_list.delete(0, "end")
        for game in self.cabinet_games:
            self.cabinet_list.insert("end", ("★  " if game.favorite else "     ") + game.name)
        if choose_first and not selected and self.cabinet_games:
            selected = self.cabinet_games[0]
            self.show_game(selected)
        if selected in self.cabinet_games:
            index = self.cabinet_games.index(selected)
            self.cabinet_list.selection_set(index)
            self.cabinet_list.activate(index)
            self.cabinet_list.see(index)

    def select_cabinet_game(self, _event=None):
        chosen = self.cabinet_list.curselection()
        if chosen and not self.busy:
            self.cache_note = ""
            self.show_game(self.cabinet_games[chosen[0]])

    def move_cabinet(self, direction):
        chosen = self.cabinet_list.curselection()
        if self.cabinet_games and not self.busy:
            index = max(0, min(len(self.cabinet_games) - 1, (chosen[0] if chosen else 0) + direction))
            self.cabinet_list.selection_clear(0, "end")
            self.cabinet_list.selection_set(index)
            self.cabinet_list.activate(index)
            self.cabinet_list.see(index)
            self.select_cabinet_game()
        return "break"

    def build_setup(self):
        requirements = ttk.Frame(self.setup_page)
        requirements.pack(fill="x", pady=(0, 8))
        ttk.Label(requirements, text="WSL 2 and hardware virtualization are required. "
                  "Set up installs the Windows components it needs.",
                  style="Hint.TLabel", wraplength=560, justify="left").pack(side="left")
        ttk.Button(requirements, text="Virtualization help",
                   command=lambda: webbrowser.open(VIRTUALIZATION_HELP)).pack(side="right")
        checklist = ttk.LabelFrame(self.setup_page, text="Setup checklist", padding=(12, 4, 12, 10))
        checklist.pack(fill="both", expand=True)
        checklist.columnconfigure(0, weight=1)
        self.labels = {}
        for index, (key, name) in enumerate(ROWS.items()):
            row = index * 3
            ttk.Label(checklist, text=name, style="Section.TLabel").grid(
                row=row, column=0, sticky="w", pady=(6, 0))
            status = ttk.Label(checklist, text="Checking…")
            status.grid(row=row, column=1, sticky="e", pady=(6, 0))
            detail = ttk.Label(checklist, wraplength=680, justify="left")
            detail.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(2, 4))
            self.labels[key] = status, detail
            if index < len(ROWS) - 1:
                ttk.Separator(checklist).grid(row=row + 2, column=0, columnspan=2, sticky="ew")
        checklist.bind("<Configure>", self.wrap_details)
        actions = ttk.Frame(self.setup_page)
        actions.pack(fill="x", pady=(10, 0))
        self.primary = ttk.Button(actions, text="Set up", command=self.repair)
        self.primary.pack(side="left")
        self.refresh = ttk.Button(actions, text="Check again", command=self.check_again)
        self.refresh.pack(side="left", padx=8)
        self.browse = ttk.Button(actions, text="Choose VPX…", command=self.choose_vpx)
        self.browse.pack(side="left")
        ttk.Button(actions, text="Get VPX", command=lambda: webbrowser.open(VPX_RELEASE)).pack(
            side="left", padx=8)
        ttk.Button(actions, text="Open logs", command=self.open_logs).pack(side="right")

    def build_cabinet(self):
        page = self.cabinet_page
        page.columnconfigure(1, weight=1)
        ttk.Label(page, text="Cabinet display setup", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(page, text="Identify your screens, assign a role to each screen, then test and save.",
                  wraplength=620).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 14))
        self.screen_vars = {}
        self.screen_boxes = {}
        self.screens = padisplay.monitors()
        for row, (role, label) in enumerate(cabinet.ROLES.items(), start=2):
            if role == "lcd":
                ttk.Label(page, text="Stern LCD mode").grid(row=row, column=0, sticky="w", pady=7)
                self.lcd_mode = tk.StringVar()
                mode = ttk.Combobox(page, textvariable=self.lcd_mode, state="readonly", width=42,
                                    values=(LCD_FULLSCREEN_MODE, LCD_WINDOWED_MODE))
                mode.grid(row=row, column=1, sticky="w", padx=16)
                mode.bind("<<ComboboxSelected>>", lambda _: self.check_layout())
                row += 1
                label = "Stern LCD screen"
            ttk.Label(page, text=label).grid(row=row, column=0, sticky="w", pady=7)
            self.screen_vars[role] = tk.StringVar()
            box = ttk.Combobox(page, textvariable=self.screen_vars[role], state="readonly", width=42)
            box.grid(row=row, column=1, sticky="w", padx=16)
            box.bind("<<ComboboxSelected>>", lambda _: self.check_layout())
            self.screen_boxes[role] = box
        buttons = ttk.Frame(page)
        buttons.grid(row=6, column=0, columnspan=2, sticky="w", pady=(16, 8))
        for label, action in (("Refresh screens", self.refresh_screens),
                              ("Identify screens", self.identify_screens),
                              ("Single-screen preset", self.single_screen),
                              ("Test layout", self.test_layout)):
            ttk.Button(buttons, text=label, command=action).pack(side="left", padx=(0, 8))
        self.save_cabinet = ttk.Button(page, text="Save display layout", command=self.save_layout)
        self.save_cabinet.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.cabinet_hint = ttk.Label(page, style="Hint.TLabel", wraplength=620, justify="left")
        self.cabinet_hint.grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Label(page, text="Use VPX windowed mode when assigning a playfield screen. "
                  "A backglass needs 64-bit B2S Server and a matching .directb2s file.",
                  style="Hint.TLabel", wraplength=620, justify="left").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(page, text="Get B2S Server", command=lambda: webbrowser.open(
            "https://github.com/vpinball/b2s-backglass/releases")).grid(
            row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))
        profile_tools = ttk.Frame(page)
        profile_tools.grid(row=11, column=0, columnspan=2, sticky="w", pady=(10, 0))
        active = self.setup.settings.get("display_profile")
        self.profile = tk.StringVar(value=active if active in support.PROFILES else "Desktop")
        ttk.Label(profile_tools, text="Display profile").pack(side="left")
        ttk.Combobox(profile_tools, textvariable=self.profile, values=support.PROFILES,
                     width=12, state="readonly").pack(side="left", padx=8)
        self.load_profile_button = ttk.Button(profile_tools, text="Load profile", command=self.load_profile)
        self.load_profile_button.pack(side="left", padx=(0, 8))
        self.tone_button = ttk.Button(profile_tools, text="Test speakers", command=self.test_speakers)
        self.tone_button.pack(side="left")
        self.overlays = []
        self.overlay_timer = None
        self.set_screen_choices(self.player.layout(self.screens))

    def selected_layout(self):
        layout = {role: self.screen_choices[role][variable.get()]
                  for role, variable in self.screen_vars.items()}
        if self.lcd_mode.get() == LCD_WINDOWED_MODE:
            layout["lcd"] = cabinet.WINDOWED_LCD
        return {role: key for role, key in layout.items() if key}

    def set_screen_choices(self, layout):
        windowed = layout.get("lcd") == cabinet.WINDOWED_LCD
        self.lcd_mode.set(LCD_WINDOWED_MODE if windowed else LCD_FULLSCREEN_MODE)
        self.screen_choices = {}
        for role, variable in self.screen_vars.items():
            choices = {cabinet.DEFAULTS[role]: ""}
            if role == "backglass":
                choices["Disabled"] = cabinet.DISABLED_B2S
            for monitor in self.screens:
                name = f"{cabinet.screen_name(monitor)} · {monitor['w']} × {monitor['h']}"
                if monitor["primary"]:
                    name += " · primary"
                choices[name] = cabinet.screen_key(monitor)
            key = "" if role == "lcd" and windowed else layout.get(role, "")
            selected = next((label for label, value in choices.items() if value == key), None)
            if selected is None:
                selected = "Saved screen · disconnected"
                choices[selected] = key
            self.screen_choices[role] = choices
            self.screen_boxes[role].configure(values=list(choices))
            variable.set(selected)
        self.check_layout()

    def check_layout(self):
        layout = self.selected_layout()
        windowed = layout.get("lcd") == cabinet.WINDOWED_LCD
        self.screen_boxes["lcd"].configure(state="disabled" if windowed else "readonly")
        try:
            roles = cabinet.resolve(layout, self.screens)
        except ValueError as exc:
            self.cabinet_hint.configure(text=str(exc))
        else:
            lcd = roles.get("lcd")
            if lcd:
                text = f"The Stern LCD will run borderless fullscreen on {cabinet.screen_name(lcd)}."
                if lcd["primary"] and "playfield" not in roles:
                    text += " It can cover VPX if the playfield is also on that screen."
            elif windowed:
                text = "The Stern LCD will run in a window."
            else:
                text = "No spare screen is available. The Stern LCD will run in a window unless you pick a screen."
            if layout.get("backglass") == cabinet.DISABLED_B2S:
                text += " B2S will stay off on the next launch."
            self.cabinet_hint.configure(text=text)

    def load_profile(self):
        profile = self.profile.get()
        defaults = {"lcd": cabinet.WINDOWED_LCD} if profile == "Desktop" else {}
        layout = self.player.profiles().get(profile, defaults)
        self.set_screen_choices(layout)
        self.save_layout()

    def test_speakers(self):
        try:
            volume = self.volume.get()
            if not 1 <= volume <= 100:
                raise ValueError("Set game volume between 1 and 100 to hear the tone.")
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Test speakers", str(exc), parent=self.root)
            return
        self.start(lambda: support.test_tone(volume),
                   lambda _: self.summary.configure(text="Played a test tone through the default Windows audio output."),
                   "Testing the default Windows audio output…")

    def refresh_screens(self):
        layout = self.selected_layout()
        self.screens = padisplay.monitors()
        self.set_screen_choices(layout)

    def single_screen(self):
        self.set_screen_choices({"lcd": cabinet.WINDOWED_LCD})

    def identify_screens(self):
        self.refresh_screens()
        self.show_screens([(monitor, cabinet.screen_name(monitor)) for monitor in self.screens])

    def test_layout(self):
        self.refresh_screens()
        try:
            roles = cabinet.resolve(self.selected_layout(), self.screens)
        except ValueError as exc:
            messagebox.showerror("Test layout", str(exc), parent=self.root)
            return
        primary = self.screens[0]
        preview = []
        for monitor in self.screens:
            labels = [cabinet.ROLES[role] + (" · fullscreen" if role == "lcd" else "")
                      for role, screen in roles.items() if screen == monitor]
            if monitor == primary:
                for role in ("playfield", "lcd"):
                    if role not in roles:
                        mode = "Windowed" if role == "lcd" else cabinet.DEFAULTS[role]
                        labels.append(f"{cabinet.ROLES[role]} · {mode}")
            if labels:
                preview.append((monitor, "\n".join(labels)))
        self.show_screens(preview, full=True)

    def dismiss_screens(self, _event=None):
        if self.overlay_timer:
            self.root.after_cancel(self.overlay_timer)
            self.overlay_timer = None
        for overlay in self.overlays:
            overlay.destroy()
        self.overlays.clear()

    def show_screens(self, screens, full=False):
        self.dismiss_screens()
        for screen, label in screens:
            overlay = tk.Toplevel(self.root)
            overlay.withdraw()
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.configure(background=ACCENT)
            pane = tk.Frame(overlay, background="#142b46")
            pane.pack(fill="both", expand=True, padx=5, pady=5)
            tk.Label(pane, text=label, font=("Segoe UI", 23, "bold"),
                     foreground="white", background="#142b46").pack(expand=True)
            tk.Label(pane, text="Click to close", foreground="#d8e5f3",
                     background="#142b46").pack(pady=(0, 12))
            overlay.bind("<Button-1>", self.dismiss_screens)
            overlay.bind("<Escape>", self.dismiss_screens)
            width, height = ((screen["w"], screen["h"]) if full else
                             (min(430, screen["w"]), min(180, screen["h"])))
            overlay.geometry(f"{width}x{height}")
            overlay.deiconify()
            overlay.update_idletasks()
            x = screen["x"] + (screen["w"] - width) // 2
            y = screen["y"] + (screen["h"] - height) // 2
            self.position_preview(overlay, x, y, width, height)
            self.overlays.append(overlay)
        self.overlay_timer = self.root.after(6000, self.dismiss_screens)

    @staticmethod
    def position_preview(overlay, x, y, width, height):
        if os.name != "nt":
            overlay.geometry(f"+{x}+{y}")
            return
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetAncestor.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        hwnd = user32.GetAncestor(ctypes.c_void_p(overlay.winfo_id()), 2)
        previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            user32.SetWindowPos(ctypes.c_void_p(hwnd), None, x, y, width, height, 0x0004 | 0x0010)
        finally:
            if previous:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))

    def build_settings(self):
        page = self.settings_page
        page.columnconfigure(1, weight=1)
        settings = self.setup.settings
        volume = settings.get("volume", 100)
        self.volume = tk.IntVar(value=volume if isinstance(volume, int) and 0 <= volume <= 100 else 100)
        self.cache = tk.BooleanVar(value=padlaunch.cache_on())
        ttk.Button(page, text="Cabinet display setup…",
                   command=lambda: self.tabs.select(self.cabinet_page)).grid(row=0, column=0, sticky="w", pady=10)
        ttk.Label(page, text="Game volume", style="Section.TLabel").grid(row=1, column=0, sticky="w", pady=10)
        ttk.Spinbox(page, textvariable=self.volume, from_=0, to=100, width=6).grid(
            row=1, column=1, sticky="w", padx=16)
        ttk.Label(page, text="SD-card cache", style="Section.TLabel").grid(row=2, column=0, sticky="w", pady=10)
        ttk.Checkbutton(page, variable=self.cache, text="Cache images in the WSL runtime").grid(
            row=2, column=1, sticky="w", padx=16)
        self.save_options = ttk.Button(page, text="Save settings", command=self.save_settings)
        self.save_options.grid(row=3, column=0, sticky="w", pady=(12, 20))
        ttk.Separator(page).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Button(page, text="VPX and runtime setup…",
                   command=lambda: self.tabs.select(self.setup_page)).grid(row=5, column=0, sticky="w")
        ttk.Button(page, text="Open logs", command=self.open_logs).grid(row=5, column=1, sticky="w", padx=16)
        ttk.Separator(page).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 12))
        ttk.Label(page, text="Library and support", style="Section.TLabel").grid(row=7, column=0, sticky="w")
        actions = ttk.Frame(page)
        actions.grid(row=8, column=0, columnspan=2, sticky="w", pady=8)
        self.backup_button = ttk.Button(actions, text="Back up library…", command=self.backup_library)
        self.backup_button.pack(side="left")
        self.restore_button = ttk.Button(actions, text="Restore backup…", command=self.restore_library)
        self.restore_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Preview support report…", command=self.preview_support).pack(side="left")

    def backup_library(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Back up your SPIKE 2 VPX library",
                                            defaultextension=".json", initialfile="SPIKE2-VPX-Library.json",
                                            filetypes=[("Library backup", "*.json")])
        if not path:
            return
        data = support.backup(self.setup.settings, padlaunch.cache_on())
        try:
            support.atomic_write(path, json.dumps(data, indent=2).encode("utf-8"))
        except OSError as exc:
            messagebox.showerror("Back up library", str(exc), parent=self.root)
        else:
            self.summary.configure(text="Library backup saved. It stores paths to your images, tables, and artwork.")

    def restore_library(self):
        path = filedialog.askopenfilename(parent=self.root, title="Choose a library backup",
                                          filetypes=[("Library backup", "*.json")])
        if not path:
            return
        try:
            data = support.read_backup(path)
            count = len(data["preferences"].get("games", []))
            if not messagebox.askyesno("Restore backup", f"Replace the current library and preferences "
                                       f"with this backup containing {count} game pairings?", parent=self.root):
                return
            self.player.restore(data)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Restore backup", str(exc), parent=self.root)
            return
        self.volume.set(self.setup.settings.get("volume", 100))
        self.cache.set(padlaunch.cache_on())
        self.profile.set(self.setup.settings.get("display_profile", "Desktop"))
        self.set_screen_choices(self.player.layout(self.screens))
        self.library_filter.set("All games")
        self.reload_library()
        self.summary.configure(text="Backup restored. Use Locate on any game whose files moved.")

    def preview_support(self):
        report = support.report(self.setup, self.checks)
        dialog = tk.Toplevel(self.root)
        dialog.title("Preview support report")
        dialog.geometry("690x500")
        dialog.transient(self.root)
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Review what will be included before you save the ZIP.").pack(anchor="w")
        text = tk.Text(body, wrap="word", background=SURFACE, foreground=TEXT, takefocus=True)
        text.insert("1.0", report)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, pady=10)

        def export():
            path = filedialog.asksaveasfilename(parent=dialog, title="Save support report",
                                                defaultextension=".zip", initialfile="SPIKE2-VPX-Support.zip",
                                                filetypes=[("Support report", "*.zip")])
            if path:
                try:
                    support.write_report(path, report)
                except OSError as exc:
                    messagebox.showerror("Save support report", str(exc), parent=dialog)
                else:
                    dialog.destroy()
                    self.summary.configure(text="Support report saved.")

        ttk.Button(body, text="Save ZIP…", command=export).pack(side="right")
        ttk.Button(body, text="Close", command=dialog.destroy).pack(side="right", padx=8)

    def wrap_details(self, event):
        for _, detail in self.labels.values():
            detail.configure(wraplength=max(240, event.width - 28))

    def open_logs(self):
        try:
            os.startfile(self.setup.log_path.parent)
        except OSError as exc:
            messagebox.showerror("Logs", str(exc), parent=self.root)

    def close(self):
        if self.busy:
            text = "Close Visual Pinball X to finish the game." if self.playing else "Wait for the current step to finish."
            messagebox.showinfo("SPIKE 2 VPX", text, parent=self.root)
            return
        self.preview_executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def ready(self, *keys):
        return all(key in self.checks and self.checks[key].state == "Ready" for key in keys)

    def update_buttons(self):
        image = self.ready("wsl", "runtime")
        has_table = self.game and self.game.table and Path(self.game.table).is_file()
        states = (
            (self.image_button, image), (self.folder_button, image),
            (self.table_button, self.game is not None),
            (self.remove_button, self.game is not None and self.game in self.saved),
            (self.play_button, True),
            (self.backglass_button, has_table and not Path(self.game.table).with_suffix(".directb2s").is_file()),
            (self.export_button, has_table and self.ready(*ROWS) and Path(self.game.image).is_file()),
            (self.primary, self.next_step(self.checks)), (self.refresh, True),
            (self.browse, True), (self.save_options, True), (self.save_cabinet, True),
            (self.load_profile_button, True), (self.tone_button, True), (self.cabinet_play, True),
            (self.backup_button, True), (self.restore_button, True),
            (self.favorite_button, self.game is not None and self.game in self.saved),
            (self.art_button, self.game is not None and self.game in self.saved),
            (self.clear_art, self.game is not None and bool(self.game.artwork)),
        )
        for button, enabled in states:
            button.state(["!disabled"] if enabled and not self.busy else ["disabled"])
        label, self.game_action, hint = self.game_step()
        self.play_button.configure(text=label)
        self.cabinet_play.configure(text=label)
        if label == "Import image…":
            self.image_button.pack_forget()
        else:
            self.image_button.pack(side="left", before=self.folder_button, padx=(0, 8))
        if label == "Choose table…":
            self.table_button.pack_forget()
        else:
            self.table_button.pack(side="left", before=self.backglass_button)
        self.play_hint.configure(text=hint)
        self.cabinet_status.configure(text=hint)
        vpx = self.checks.get("vpx")
        runtime, why = self.setup.vr
        has_vr_player = self.setup.vpx_executable(vr=True) is not None
        # only beside Play: not while a game is being added, located or set up
        if self.game_action == self.play and (has_vr_player or self.vr_var.get()):
            self.vr_check.pack(side="left", padx=(12, 0), after=self.export_button)
        else:
            self.vr_check.pack_forget()
        # off is always allowed, so a broken VR setup never blocks play
        self.vr_check.state(["!disabled"] if (runtime or self.vr_var.get()) and not self.busy else ["disabled"])
        lines = [vpx.detail.split(" · ", 1)[0] if vpx and vpx.state == "Ready"
                 else "Requires Visual Pinball X 10.8+ x64"]
        if self.vr_var.get() or (has_vr_player and not runtime):
            lines.append(f"VR: {runtime}" if runtime else f"VR unavailable. {why}")
        self.vpx_hint.configure(text="\n".join(lines))

    def game_step(self):
        if self.same_game(self.game, self.recover_game):
            return "Recover session", self.recover_session, "The previous Stern run stopped before it finished cleaning up."
        if not self.ready("wsl", "runtime"):
            return "Open Setup", lambda: self.open_tab(self.setup_page), "Set up WSL and the SPIKE 2 runtime."
        if not self.game:
            return "Import image…", self.choose_image, "Get an SD-card image from Stern, then import the file."
        if not Path(self.game.image).is_file():
            repair = lambda: self.choose_image(expected=self.game)
            return "Locate image…", repair, "The saved image is missing. Locate it to restore this pairing."
        if not self.game.table or not Path(self.game.table).is_file():
            hint = ("The saved VPX table is missing. Choose it again." if self.game.table else
                    "Use Supported Tables to find a compatible release for this edition.")
            return ("Locate table…" if self.game.table else "Choose table…"), self.choose_table, hint
        if not self.ready(*ROWS):
            return "Open Setup", lambda: self.open_tab(self.setup_page), "Complete the remaining setup checks."
        try:
            warnings = self.player.preflight(self.game)
        except ValueError as exc:
            return "Review cabinet layout", lambda: self.open_tab(self.cabinet_page), str(exc)
        done = ("Playing in VR: put on your headset. Close VPX to end the game." if self.vr_var.get()
                else "Close VPX to end the game.")
        play = "Play in VR" if self.vr_var.get() else "Play"
        return ("Try again" if self.same_game(self.game, self.launch_error_game) else play), self.play, (
            "\n".join(warnings) or done)

    def next_game_step(self):
        self.game_action()

    def toggle_vr(self):
        try:
            self.setup.set_vr(self.vr_var.get())
        except OSError as exc:
            self.vr_var.set(self.setup.vr_wanted())
            messagebox.showerror("Enable VR", str(exc), parent=self.root)
        self.update_buttons()

    def open_tab(self, page):
        if self.cabinet_mode:
            self.toggle_cabinet()
        self.tabs.select(page)

    def tab_changed(self, _event):
        if self.tabs.select() == str(self.cabinet_page):
            self.refresh_screens()
        if self.tabs.select() == str(self.lighting_page):
            self.lighting.refresh()
        self.update_buttons()

    def reload_library(self, select=None):
        self.saved = self.player.library()
        mode = self.library_filter.get()
        if mode == "Favorites":
            self.visible_games = [game for game in self.saved if game.favorite]
        elif mode == "Recently played":
            self.visible_games = sorted((game for game in self.saved if game.last_played),
                                        key=lambda game: game.last_played, reverse=True)
        else:
            self.visible_games = sorted(self.saved, key=lambda game: (not game.favorite, game.name.casefold()))
        for card in self.cards.winfo_children():
            card.destroy()
        self.card_buttons = []
        for game in self.visible_games:
            title = ("★ " if game.favorite else "") + game.name
            card = ttk.Button(self.cards, text=f"{title}\n{self.library_status(game)}",
                              style="GameCard.TButton", command=lambda item=game: self.select_game(item))
            card.pack(fill="x", pady=(0, 5), padx=(0, 4))
            card.bind("<MouseWheel>", self.scroll_library)
            self.card_buttons.append((game, card))
        self.library_hint.configure(text="" if self.visible_games else "No games in this view.")
        self.show_game(select)
        self.reload_cabinet(select)

    def library_status(self, game):
        if self.same_game(game, self.recover_game) or not Path(game.image).is_file():
            return "Needs attention"
        if not game.table or not Path(game.table).is_file():
            return "Needs table"
        return "Ready" if self.ready(*ROWS) else "Needs setup"

    def scroll_library(self, event):
        self.library_canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def select_game(self, game):
        if not self.busy and game != self.game:
            self.cache_note = ""
            self.show_game(game)

    def remove_game(self):
        if not messagebox.askyesno("Remove pairing", f"Remove {self.game.name} from the library? "
                                   "Its image and table files will stay in place.", parent=self.root):
            return
        try:
            self.player.remove(self.game)
        except OSError as exc:
            messagebox.showerror("Remove pairing", str(exc), parent=self.root)
            return
        self.cache_note = ""
        self.reload_library()
        self.summary.configure(text="Pairing removed.")

    @staticmethod
    def same_game(left, right):
        return bool(left and right and (left.title, left.image) == (right.title, right.image))

    def show_game(self, game):
        if game != self.game and not self.same_game(game, self.game):
            self.launch_text.set("")
            self.lighting_notice = ""
        self.game = game
        self.lighting.show_game(game, self.lighting_notice)
        for item, card in self.card_buttons:
            card.configure(style="SelectedCard.TButton" if game == item else "GameCard.TButton")
        self.game_title.configure(text=game.name if game else "Add a game")
        self.cabinet_title.configure(text=self.game_title["text"])
        self.favorite_button.configure(text="Remove favorite" if game and game.favorite else "Add favorite")
        facts, paths = [], []
        if game:
            version = game.image_version or image_version(Path(game.image).name)
            facts = [self.library_status(game), f"Image v{version} (filename)" if version else "Image version unavailable"]
            if release := self.player.table_release(game):
                facts.append(release)
            if game.last_played:
                try:
                    local = datetime.fromisoformat(game.last_played).astimezone()
                    facts.append(f"Last played {local:%b %d, %Y}")
                except ValueError:
                    pass
            paths = [f"Image  {game.image}"]
            if game.table:
                paths.append(f"Table  {game.table}")
            if game.artwork:
                paths.append(f"Artwork  {game.artwork}")
            if self.cache_note:
                paths.append(self.cache_note)
        self.game_facts.configure(text="  ·  ".join(facts))
        self.cabinet_facts.configure(text="\n".join(facts))
        self.file_details.configure(text="\n".join(paths))
        self.show_preview(game)
        self.update_buttons()

    def preview_labels(self):
        return ((self.game_art, 130, 96), (self.cabinet_art, 440, 300))

    def show_preview(self, game):
        key = backglass.preview_key(game.table) if game else None
        identity = (game.title, game.artwork, key) if game else None
        if identity == self.preview_identity:
            return
        self.preview_identity = identity
        if self.preview_job:
            self.preview_job.cancel()
            self.preview_job = None
        for label, width, height in self.preview_labels():
            label.image = game_preview(self.root, game, width, height)
            label.configure(image=label.image or "")
        if key and not artwork_preview(self.root, game.artwork, 130, 96):
            self.preview_job = self.preview_executor.submit(backglass.thumbnail, key)
            self.root.after(60, self.finish_preview, self.preview_job)

    def finish_preview(self, job):
        if job is not self.preview_job:
            return
        if not job.done():
            self.root.after(60, self.finish_preview, job)
            return
        try:
            data = job.result()
        except Exception:
            self.setup.log.exception("Backglass preview failed")
            return
        for label, width, height in self.preview_labels():
            if preview := photo_preview(self.root, data, width, height):
                label.image = preview
                label.configure(image=preview)

    def toggle_details(self):
        self.details_open = not self.details_open
        if self.details_open:
            self.detail_panel.pack(fill="x", pady=(8, 0))
        else:
            self.detail_panel.pack_forget()
        self.details_button.configure(text="Hide details" if self.details_open else "Show details")

    def favorite(self):
        if self.game:
            self.edit_game(favorite=not self.game.favorite)

    def choose_artwork(self):
        path = filedialog.askopenfilename(parent=self.root, title="Choose local game artwork",
                                          filetypes=[("Game artwork", "*.png *.gif")])
        if path and (Path(path).suffix.casefold() not in {".png", ".gif"}
                     or not artwork_preview(self.root, path, 130, 96)):
            messagebox.showerror("Game artwork", "Choose a valid PNG or GIF under 12 MB.", parent=self.root)
        elif path:
            self.edit_game(artwork=str(Path(path).resolve()))

    def edit_game(self, **changes):
        try:
            self.reload_library(self.player.update_game(self.game, **changes))
        except OSError as exc:
            messagebox.showerror("Game library", str(exc), parent=self.root)

    def start(self, work, done, message, failed=None):
        if self.busy:
            return
        self.busy = True
        self.summary.configure(text=message)
        self.progress.start(12)
        self.update_buttons()

        def worker():
            try:
                self.results.put(("done", work(), done))
            except Exception as exc:
                self.setup.log.exception("Desktop operation failed")
                self.results.put(("error", exc, failed))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(80, self.finish)

    def report(self, message, playing):
        self.results.put(("progress", message, playing))

    def report_lighting(self, message):
        self.results.put(("lighting", message, None))

    def finish(self):
        while True:
            try:
                kind, value, extra = self.results.get_nowait()
            except queue.Empty:
                self.root.after(80, self.finish)
                return
            if kind == "lighting":
                if value:
                    self.lighting_notice = value
                    self.summary.configure(text=value)
                self.lighting.show_game(self.game, self.lighting_notice)
                continue
            if kind == "progress":
                self.summary.configure(text=" ".join(filter(None, (value, self.lighting_notice)))
                                       if self.launching else value)
                if self.launching and value in LAUNCH_STAGES:
                    self.last_stage = value
                    index = LAUNCH_STAGES.index(value)
                    stages = "\n".join(
                        ("✓  " if step < index else "›  " if step == index else "     ") + stage
                        for step, stage in enumerate(LAUNCH_STAGES))
                    self.launch_text.set("\n".join(filter(None, (stages, self.lighting_notice))))
                if extra:
                    self.playing = True
                    self.launch_text.set("Playing in Visual Pinball X")
                    self.root.withdraw()
                continue
            self.busy = False
            self.progress.stop()
            if self.playing:
                self.playing = False
                self.root.deiconify()
                if self.cabinet_mode:
                    self.cabinet_list.focus_set()
            self.launching = False
            if kind == "done":
                extra(value)
            elif extra:
                extra(value)
            else:
                self.summary.configure(text=str(value))
                messagebox.showerror("SPIKE 2 VPX", str(value), parent=self.root)
            self.update_buttons()
            return

    def check_again(self):
        def work():
            resume = "restart_boot" in self.setup.settings
            checks = self.setup.checks()
            return self.run_setup_steps(checks) if resume else checks

        self.start(work, self.show_checks, "Checking this PC…")

    def show_checks(self, checks):
        self.checks = checks
        for key, check in checks.items():
            status, detail = self.labels[key]
            status.configure(text=check.state)
            detail.configure(text=check.detail)
        states = {check.state for check in checks.values()}
        if "Restart required" in states:
            summary = "Restart Windows, then reopen SPIKE 2 VPX to resume setup."
        elif self.ready(*ROWS):
            summary = "Setup complete."
            if self.first_check or self.tabs.select() == str(self.setup_page):
                self.tabs.select(self.games_page)
        elif states & {"Setup failed", "Check failed"}:
            summary = "Review the setup logs, then retry or check again."
        else:
            summary = "Follow the instructions beside each item that needs attention."
        self.first_check = False
        self.reload_library(self.game)
        self.summary.configure(text=summary)
        self.primary.configure(text="Retry setup" if "Setup failed" in states else
                               "Repair" if "Repair needed" in states else "Set up")

    @staticmethod
    def next_step(checks):
        if any(check.state == "Restart required" for check in checks.values()):
            return None
        for key, check in checks.items():
            if check.state == "Setup failed" and check.action:
                return key, check.action
        return next(((key, check.action) for key, check in checks.items() if check.action), None)

    def run_setup_steps(self, checks):
        while (step := self.next_step(checks)):
            key, action = step
            self.report(f"Setting up {ROWS[key]}… Windows may ask for administrator permission.", False)
            checks = self.setup.repair(key, action)
            if checks[key].state == "Setup failed":
                break
        return checks

    def repair(self):
        self.start(lambda: self.run_setup_steps(self.setup.checks()), self.show_checks,
                   "Setting up this PC… Windows may ask for administrator permission.")

    def choose_vpx(self):
        folder = filedialog.askdirectory(parent=self.root, title="Choose the Visual Pinball X folder")
        if not folder:
            return

        def work():
            self.setup.choose_vpx(folder)
            return self.setup.checks()

        self.start(work, self.show_checks, "Checking the selected VPX installation…")

    def choose_image(self, expected=None):
        path = filedialog.askopenfilename(parent=self.root, title="Choose a SPIKE 2 image",
                                          filetypes=[("SD-card images and ZIP archives", "*.raw *.zip"),
                                                     ("All files", "*.*")])
        if path:
            self.load_image(path, expected)

    def get_image(self):
        webbrowser.open(STERN_IMAGES)

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="Choose an SD-card image folder")
        if not folder:
            return
        try:
            candidates = folder_images(folder)
        except OSError as exc:
            messagebox.showerror("Choose folder", str(exc), parent=self.root)
            return
        if not candidates:
            messagebox.showinfo("Choose folder", "This folder contains no .raw images.", parent=self.root)
            return
        if len(candidates) == 1:
            self.load_image(candidates[0])
            return
        if self.game:
            try:
                match = play_spike2.card_in_folder(Path(folder), self.game.title)
            except ValueError:
                pass
            else:
                self.load_image(match)
                return
        self.pick_candidate(candidates)

    def pick_candidate(self, candidates):
        dialog = tk.Toplevel(self.root)
        dialog.title("Choose an image")
        dialog.geometry("580x320")
        dialog.transient(self.root)
        pane = ttk.Frame(dialog, padding=12)
        pane.pack(fill="both", expand=True)
        ttk.Label(pane, text="This folder has several .raw images. Choose one to inspect.").pack(anchor="w")
        choices = tk.Listbox(pane, exportselection=False)
        choices.pack(fill="both", expand=True, pady=8)
        for path in candidates:
            choices.insert("end", path.name)

        def accept(_event=None):
            selected = choices.curselection()
            if selected:
                dialog.destroy()
                self.load_image(candidates[selected[0]])

        choices.bind("<Double-1>", accept)
        choices.bind("<Return>", accept)
        ttk.Button(pane, text="Choose image", command=accept).pack(side="right")
        ttk.Button(pane, text="Cancel", command=dialog.destroy).pack(side="right", padx=8)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        choices.selection_set(0)
        choices.focus_set()
        dialog.grab_set()

    def load_image(self, path, expected=None):
        def work():
            image, note = self.player.prepare_image(path, expected)
            if expected and expected in self.saved:
                image = self.player.relink_image(expected, image)
            elif not any(game.title == image.title and game.image == image.image for game in self.saved):
                self.player.save(image)
            return image, note

        def done(result):
            image, self.cache_note = result
            saved = next((row for row in self.player.library() if row.title == image.title and
                          Path(row.image) == Path(image.image)), None)
            self.reload_library(saved or image)
            self.summary.configure(text=f"{image.name} · image verified.")

        message = "Extracting and inspecting the SD-card image…" if Path(path).suffix.casefold() == ".zip" else (
            "Inspecting the SD-card image…")
        self.start(work, done, message)

    def choose_table(self):
        game = self.game
        path = filedialog.askopenfilename(parent=self.root, title=f"Choose a VPX table for {game.name}",
                                          filetypes=[("Visual Pinball X table", "*.vpx")])
        if not path:
            return

        def work():
            prepared = self.player.prepare_table(game, path, self.report)
            self.player.save(prepared)
            return prepared

        def done(prepared):
            self.reload_library(prepared)
            self.summary.configure(text=f"Saved {prepared.name} to the game library.")

        self.start(work, done, "Checking table compatibility…")

    def play(self):
        game = self.game
        try:
            warnings = self.player.preflight(game)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Before playing", str(exc), parent=self.root)
            self.update_buttons()
            return
        if warnings and not messagebox.askokcancel("Backglass setup", "\n".join(warnings) +
                                                  "\n\nContinue playing?", parent=self.root):
            return

        self.launching = True
        self.launch_error_game = None
        self.last_stage = "Checking files"
        self.lighting_notice = ""
        self.lighting.show_game(game, "")
        self.launch_text.set("›  Checking files")

        def done(code):
            self.launch_text.set("")
            if code:
                text = f"VPX exited with code {code}. Open logs in Settings for details."
                failed(RuntimeError(text))
            else:
                self.summary.configure(text=self.lighting_notice or "Game ended. The runtime has stopped.")
            updated = next((row for row in self.player.library() if row.title == game.title
                            and row.image == game.image), game)
            self.reload_library(updated)

        def failed(error):
            text = str(error)
            if isinstance(error, sessions.StaleSession):
                self.recover_game = game
            else:
                self.launch_error_game = game
            self.summary.configure(text=text)
            self.launch_text.set(f"Stopped at {self.last_stage.lower()}\n{text}")
            self.reload_library(self.game)

        self.start(lambda: self.player.play(game, self.report, lighting_update=self.report_lighting),
                   done, f"Starting {game.name}…", failed)

    def recover_session(self):
        game = self.game

        def done(_):
            self.recover_game = None
            self.launch_text.set("Stale session recovered.")
            self.play()

        def failed(error):
            self.recover_game = None
            self.launch_error_game = game
            self.launch_text.set(str(error))
            self.summary.configure(text=str(error))

        self.start(lambda: sessions.recover(self.setup, game.title), done,
                   "Verifying the stopped session…", failed)

    def attach_backglass(self):
        game = self.game
        path = filedialog.askopenfilename(parent=self.root, title="Choose a backglass for this table",
                                          filetypes=[("B2S backglass", "*.directb2s")])
        if path:
            def done(_):
                self.show_preview(game)
                self.summary.configure(text="Backglass attached to the prepared table.")

            self.start(lambda: self.player.attach_backglass(game, path), done, "Checking the backglass file…")

    def export_game(self):
        game = self.game
        path = filedialog.asksaveasfilename(parent=self.root, title="Export a front-end launch script",
                                           defaultextension=".bat", initialfile=f"{game.name}.bat",
                                           filetypes=[("Windows launch script", "*.bat *.cmd")])
        if not path:
            return

        def done(warnings):
            text = "Set the game’s Application Path in LaunchBox to this script. It waits until VPX closes."
            if warnings:
                text += "\n\n" + "\n".join(warnings)
            self.summary.configure(text=f"Exported {Path(path).name}.")
            messagebox.showinfo("Launch script exported", text, parent=self.root)

        self.start(lambda: self.player.export(game, path), done, "Validating and exporting the pairing…")

    def save_layout(self):
        self.refresh_screens()
        try:
            self.player.save_layout(self.selected_layout(), self.screens, self.profile.get())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save display layout", str(exc), parent=self.root)
        else:
            self.summary.configure(text=f"{self.profile.get()} display profile saved and active.")
        self.update_buttons()

    def save_settings(self):
        try:
            volume = self.volume.get()
            if not 0 <= volume <= 100:
                raise ValueError("Enter a game volume from 0 to 100.")
            self.player.save_preferences(volume, self.cache.get())
        except (OSError, ValueError, tk.TclError) as exc:
            messagebox.showerror("Save settings", str(exc), parent=self.root)
        else:
            self.summary.configure(text="Settings saved.")

def main():
    root = tk.Tk()
    root.withdraw()
    if os.name == "nt":
        root.iconbitmap(default=str(Path(__file__).resolve().parent / "assets" / "spike2_vpx.ico"))
    try:
        setup = Setup()
        # A second setup window must not share an active download or import.
        import msvcrt

        with (Path(setup.data) / "setup.lock").open("a+b") as lock:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                messagebox.showinfo("SPIKE 2 VPX", "SPIKE 2 VPX is already open.", parent=root)
                return
            PlayerWindow(root, setup)
            root.deiconify()
            root.mainloop()
    except OSError as exc:
        messagebox.showerror("SPIKE 2 VPX", f"SPIKE 2 VPX could not open.\n\n{exc}", parent=root)


if __name__ == "__main__":
    main()
