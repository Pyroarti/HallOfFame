from tkinter import filedialog, messagebox
from io import BytesIO
import json
import os
import uuid
import threading
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

import customtkinter as ctk
from PIL import Image


# ---------- Konfiguration ----------
DATA_FILE = "hall_of_fame.json"
CONFIG_FILE = "hall_of_fame_config.json"
COVERS_DIR = "covers"
CARD_WIDTH = 300
CARD_HEIGHT = 400
COVER_HEIGHT = 200
HTTP_TIMEOUT = 12
USER_AGENT = "HallOfFame/1.0"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg": "#1a1a1f",
    "card_bg": "#252530",
    "card_hover": "#2f2f3d",
    "accent": "#a855f7",
    "accent_hover": "#9333ea",
    "game_color": "#3b82f6",
    "anime_color": "#ec4899",
    "text": "#f0f0f5",
    "text_dim": "#9ca3af",
    "danger": "#dc2626",
}

class DataManager:
    def __init__(self, filepath):
        self.filepath = filepath
        self.entries = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)

    def add(self, entry):
        entry["id"] = str(uuid.uuid4())
        entry["date_added"] = datetime.now().isoformat()
        self.entries.append(entry)
        self.save()

    def update(self, entry_id, updated):
        for i, e in enumerate(self.entries):
            if e["id"] == entry_id:
                updated["id"] = entry_id
                updated["date_added"] = e.get("date_added", datetime.now().isoformat())
                self.entries[i] = updated
                self.save()
                return

    def delete(self, entry_id):
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        self.save()

    def filter(self, type_filter="all", search=""):
        result = self.entries
        if type_filter != "all":
            result = [e for e in result if e.get("type") == type_filter]
        if search:
            s = search.lower()
            result = [e for e in result if s in e.get("title", "").lower()]
        return result


class ConfigManager:
    """Lagrar appens inställningar (t.ex. API-nyckel) i en separat fil."""

    def __init__(self, filepath):
        self.filepath = filepath
        self.config = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"rawg_api_key": ""}

    def save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)

    def get_rawg_key(self):
        return self.config.get("rawg_api_key", "")

    def set_rawg_key(self, key):
        self.config["rawg_api_key"] = key.strip()
        self.save()


class CoverFetcher:
    """Söker och laddar ner omslag från externa API:er."""

    @staticmethod
    def _http_get_json(url):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def search_anime(query, limit=12):
        """Jikan API – fritt, ingen nyckel."""
        url = (
            "https://api.jikan.moe/v4/anime"
            f"?q={urllib.parse.quote(query)}&limit={limit}&sfw=true"
        )
        data = CoverFetcher._http_get_json(url)
        results = []
        for item in data.get("data", []):
            images = (item.get("images") or {}).get("jpg") or {}
            year = None
            aired_from = (item.get("aired") or {}).get("from")
            if aired_from:
                year = aired_from[:4]
            title = item.get("title_english") or item.get("title") or ""
            results.append({
                "title": title,
                "year": year,
                "image_url": images.get("large_image_url") or images.get("image_url"),
            })
        return [r for r in results if r["image_url"]]

    @staticmethod
    def search_game(query, api_key, limit=12):
        """RAWG API – kräver gratis nyckel från rawg.io/apidocs."""
        if not api_key:
            raise ValueError(
                "RAWG API-nyckel saknas. "
                "Hämta en gratis från https://rawg.io/apidocs och ange den under ⚙️ Inställningar."
            )
        url = (
            "https://api.rawg.io/api/games"
            f"?key={urllib.parse.quote(api_key)}"
            f"&search={urllib.parse.quote(query)}"
            f"&page_size={limit}"
        )
        data = CoverFetcher._http_get_json(url)
        results = []
        for item in data.get("results", []):
            year = None
            released = item.get("released")
            if released:
                year = released[:4]
            results.append({
                "title": item.get("name", ""),
                "year": year,
                "image_url": item.get("background_image"),
            })
        return [r for r in results if r["image_url"]]

    @staticmethod
    def download_image(url, target_dir):
        """Laddar ner en bild och returnerar den lokala sökvägen."""
        os.makedirs(target_dir, exist_ok=True)
        ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
            ext = "jpg"
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(target_dir, filename)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            with open(filepath, "wb") as f:
                f.write(resp.read())
        return filepath


# ---------- Inställningsdialog ----------
class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: ConfigManager):
        super().__init__(parent)
        self.title("Inställningar")
        self.geometry("520x320")
        self.transient(parent)
        self.after(100, self.grab_set)

        self.config_mgr = config
        self._build()

    def _build(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=24)

        ctk.CTkLabel(container, text="⚙️ Inställningar",
                     font=("Helvetica", 20, "bold")).pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(container, text="RAWG API-nyckel (för omslagshämtning av spel)",
                     anchor="w", font=("Helvetica", 12, "bold")
                     ).pack(fill="x")
        ctk.CTkLabel(
            container,
            text="Hämta en gratis nyckel från https://rawg.io/apidocs (tar ~30 sek)",
            anchor="w", text_color=COLORS["text_dim"], font=("Helvetica", 11)
        ).pack(fill="x", pady=(2, 6))

        self.key_entry = ctk.CTkEntry(container, height=36, show="•")
        self.key_entry.pack(fill="x", pady=(0, 6))
        self.key_entry.insert(0, self.config_mgr.get_rawg_key())

        self.show_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(container, text="Visa nyckel",
                        variable=self.show_var,
                        command=self._toggle_show).pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(
            container,
            text="ℹ️  Anime-sök behöver ingen nyckel (använder Jikan/MyAnimeList).",
            anchor="w", text_color=COLORS["text_dim"], font=("Helvetica", 11)
        ).pack(fill="x", pady=(0, 16))

        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", side="bottom")
        ctk.CTkButton(btn_frame, text="Avbryt", fg_color="gray30",
                      hover_color="gray25", width=100,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Spara", width=100,
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      command=self._save).pack(side="right")

    def _toggle_show(self):
        self.key_entry.configure(show="" if self.show_var.get() else "•")

    def _save(self):
        self.config_mgr.set_rawg_key(self.key_entry.get())
        self.destroy()


# ---------- Sökdialog för online-omslag ----------
class CoverSearchDialog(ctk.CTkToplevel):
    def __init__(self, parent, item_type, initial_title, rawg_key, on_select):
        super().__init__(parent)
        self.title("Sök omslag online")
        self.geometry("760x640")
        self.transient(parent)
        self.after(100, self.grab_set)

        self.item_type = item_type
        self.rawg_key = rawg_key
        self.on_select = on_select
        self._photo_refs = []  # håll referenser så bilder inte GC:as
        self._is_searching = False

        self._build()

        if initial_title.strip():
            self.search_entry.insert(0, initial_title)
            self.after(150, self._do_search)

    def _build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 8))

        type_emoji = "🎮" if self.item_type == "game" else "🌸"
        type_word = "spel" if self.item_type == "game" else "anime"
        ctk.CTkLabel(top, text=f"{type_emoji}  Söker {type_word}-omslag",
                     font=("Helvetica", 14, "bold")
                     ).pack(anchor="w", pady=(0, 8))

        search_row = ctk.CTkFrame(top, fg_color="transparent")
        search_row.pack(fill="x")
        self.search_entry = ctk.CTkEntry(search_row, height=36,
                                          placeholder_text="Sök titel...")
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        ctk.CTkButton(search_row, text="Sök", width=80, height=36,
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      command=self._do_search).pack(side="right")

        self.status_label = ctk.CTkLabel(self, text="", anchor="w",
                                          text_color=COLORS["text_dim"])
        self.status_label.pack(fill="x", padx=20, pady=(2, 4))

        self.results_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.results_frame.pack(fill="both", expand=True, padx=16, pady=(4, 16))

    def _do_search(self):
        if self._is_searching:
            return
        query = self.search_entry.get().strip()
        if not query:
            self.status_label.configure(text="Skriv en titel att söka efter.")
            return

        for w in self.results_frame.winfo_children():
            w.destroy()
        self._photo_refs = []

        self._is_searching = True
        self.status_label.configure(text="Söker...")

        def fetch():
            try:
                if self.item_type == "anime":
                    results = CoverFetcher.search_anime(query)
                else:
                    results = CoverFetcher.search_game(query, self.rawg_key)
                self.after(0, lambda: self._display_results(results))
            except urllib.error.URLError as e:
                msg = f"Nätverksfel: {e.reason}"
                self.after(0, lambda: self._on_error(msg))
            except ValueError as e:
                msg = str(e)
                self.after(0, lambda: self._on_error(msg))
            except Exception as e:
                msg = f"Oväntat fel: {e}"
                self.after(0, lambda: self._on_error(msg))

        threading.Thread(target=fetch, daemon=True).start()

    def _on_error(self, message):
        self._is_searching = False
        self.status_label.configure(text=message)

    def _display_results(self, results):
        self._is_searching = False
        if not results:
            self.status_label.configure(text="Inga resultat.")
            return
        self.status_label.configure(
            text=f"{len(results)} resultat — klicka på ett för att välja."
        )

        cols = 3
        for i, r in enumerate(results):
            row, col = divmod(i, cols)
            card = self._make_result_card(r)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="n")
        for c in range(cols):
            self.results_frame.grid_columnconfigure(c, weight=1)

    def _make_result_card(self, result):
        card = ctk.CTkFrame(self.results_frame, fg_color=COLORS["card_bg"],
                            corner_radius=8, width=210, height=290)
        card.pack_propagate(False)

        img_holder = ctk.CTkFrame(card, fg_color="#15151c", height=200)
        img_holder.pack(fill="x", padx=8, pady=(8, 6))
        img_holder.pack_propagate(False)

        loading_label = ctk.CTkLabel(img_holder, text="Laddar...",
                                     text_color=COLORS["text_dim"])
        loading_label.pack(expand=True)

        title = result.get("title") or "Okänd"
        display_title = title if len(title) <= 30 else title[:28] + "…"
        title_label = ctk.CTkLabel(card, text=display_title,
                                    font=("Helvetica", 11, "bold"),
                                    text_color=COLORS["text"], wraplength=190,
                                    anchor="w", justify="left")
        title_label.pack(fill="x", padx=8)

        year_label = None
        if result.get("year"):
            year_label = ctk.CTkLabel(card, text=str(result["year"]),
                                       font=("Helvetica", 10),
                                       text_color=COLORS["text_dim"], anchor="w")
            year_label.pack(fill="x", padx=8, pady=(0, 4))

        def on_click(_e=None):
            self._select(result)

        for w in (card, img_holder, loading_label, title_label):
            w.bind("<Button-1>", on_click)
        if year_label:
            year_label.bind("<Button-1>", on_click)

        card.bind("<Enter>", lambda e: card.configure(fg_color=COLORS["card_hover"]))
        card.bind("<Leave>", lambda e: card.configure(fg_color=COLORS["card_bg"]))

        url = result.get("image_url")
        if url:
            def load_thumb():
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                        data = resp.read()
                    img = Image.open(BytesIO(data))
                    img.thumbnail((190, 190))

                    def update_ui():
                        if not card.winfo_exists():
                            return
                        photo = ctk.CTkImage(light_image=img, dark_image=img,
                                              size=img.size)
                        self._photo_refs.append(photo)
                        loading_label.destroy()
                        img_label = ctk.CTkLabel(img_holder, image=photo, text="")
                        img_label.pack(expand=True)
                        img_label.bind("<Button-1>", on_click)

                    self.after(0, update_ui)
                except Exception:
                    def fail():
                        if loading_label.winfo_exists():
                            loading_label.configure(text="Bild saknas")
                    self.after(0, fail)

            threading.Thread(target=load_thumb, daemon=True).start()

        return card

    def _select(self, result):
        url = result.get("image_url")
        if not url:
            return
        self.status_label.configure(text="Laddar ner omslag...")

        def download():
            try:
                local_path = CoverFetcher.download_image(url, COVERS_DIR)
                def done():
                    self.on_select(local_path, result)
                    self.destroy()
                self.after(0, done)
            except Exception as e:
                msg = f"Misslyckades: {e}"
                self.after(0, lambda: self.status_label.configure(text=msg))

        threading.Thread(target=download, daemon=True).start()


# ---------- Lägg till / redigera ----------
class EntryDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_save, config: ConfigManager, entry=None):
        super().__init__(parent)
        self.title("Lägg till" if entry is None else "Redigera")
        self.geometry("540x720")
        self.transient(parent)
        self.after(100, self.grab_set)

        self.on_save = on_save
        self.config_mgr = config
        self.entry = entry or {}
        self.cover_path = self.entry.get("cover_path", "")

        self._build()

    def _build(self):
        container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=(20, 0))

        ctk.CTkLabel(container, text="Titel *", anchor="w",
                     font=("Helvetica", 12, "bold")).pack(fill="x")
        self.title_entry = ctk.CTkEntry(container, height=36)
        self.title_entry.pack(fill="x", pady=(2, 14))
        self.title_entry.insert(0, self.entry.get("title", ""))

        ctk.CTkLabel(container, text="Typ *", anchor="w",
                     font=("Helvetica", 12, "bold")).pack(fill="x")
        self.type_var = ctk.StringVar(value=self.entry.get("type", "game"))
        type_frame = ctk.CTkFrame(container, fg_color="transparent")
        type_frame.pack(fill="x", pady=(2, 14))
        ctk.CTkRadioButton(type_frame, text="🎮 Spel", variable=self.type_var,
                           value="game").pack(side="left", padx=(0, 24))
        ctk.CTkRadioButton(type_frame, text="🌸 Anime", variable=self.type_var,
                           value="anime").pack(side="left")

        self.to_be_played_watched = ctk.CTkCheckBox(type_frame, text="To be played/watched?")
        self.to_be_played_watched.pack()

        ctk.CTkLabel(container, text="Betyg (0–10) — valfritt", anchor="w",
                     font=("Helvetica", 12, "bold")).pack(fill="x")
        self.rating_entry = ctk.CTkEntry(container, height=36)
        self.rating_entry.pack(fill="x", pady=(2, 14))
        if self.entry.get("rating") is not None:
            self.rating_entry.insert(0, str(self.entry["rating"]))

        ctk.CTkLabel(container, text="År — valfritt", anchor="w",
                     font=("Helvetica", 12, "bold")).pack(fill="x")
        self.year_entry = ctk.CTkEntry(container, height=36)
        self.year_entry.pack(fill="x", pady=(2, 14))
        if self.entry.get("year"):
            self.year_entry.insert(0, str(self.entry["year"]))

        ctk.CTkLabel(container, text="Anteckningar", anchor="w",
                     font=("Helvetica", 12, "bold")).pack(fill="x")
        self.notes_text = ctk.CTkTextbox(container, height=140, wrap="word")
        self.notes_text.pack(fill="x", pady=(2, 14))
        self.notes_text.insert("1.0", self.entry.get("notes", ""))

        ctk.CTkLabel(container, text="Omslagsbild — valfritt", anchor="w",
                     font=("Helvetica", 12, "bold")).pack(fill="x")
        self.cover_label = ctk.CTkLabel(container, text=self._cover_text(),
                                         anchor="w",
                                         text_color=COLORS["text_dim"])
        self.cover_label.pack(fill="x", pady=(2, 6))

        cover_btns = ctk.CTkFrame(container, fg_color="transparent")
        cover_btns.pack(fill="x", pady=(0, 14))
        ctk.CTkButton(cover_btns, text="🔍 Sök online", width=130,
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      command=self._search_online).pack(side="left", padx=(0, 6))
        ctk.CTkButton(cover_btns, text="📁 Bläddra", width=110,
                      fg_color="gray30", hover_color="gray25",
                      command=self._pick_cover).pack(side="left", padx=(0, 6))
        ctk.CTkButton(cover_btns, text="✕ Rensa", width=80,
                      fg_color="gray30", hover_color="gray25",
                      command=self._clear_cover).pack(side="left")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=20)
        ctk.CTkButton(btn_frame, text="Avbryt", fg_color="gray30",
                      hover_color="gray25", width=100,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Spara", width=100,
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      command=self._save).pack(side="right")

    def _cover_text(self):
        if self.cover_path:
            return f"📎 {os.path.basename(self.cover_path)}"
        return "Ingen bild vald"

    def _pick_cover(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("Bildfiler", "*.png *.jpg *.jpeg *.webp *.gif *.bmp")],
        )
        if path:
            self.cover_path = path
            self.cover_label.configure(text=self._cover_text())

    def _clear_cover(self):
        self.cover_path = ""
        self.cover_label.configure(text=self._cover_text())

    def _search_online(self):
        title = self.title_entry.get().strip()
        item_type = self.type_var.get()

        if not title:
            messagebox.showinfo("Saknas",
                                "Skriv in en titel först så kan jag söka efter omslag.",
                                parent=self)
            self.title_entry.focus_set()
            return

        rawg_key = self.config_mgr.get_rawg_key()
        if item_type == "game" and not rawg_key:
            answer = messagebox.askyesno(
                "API-nyckel saknas",
                "För att söka spel-omslag automatiskt behövs en gratis "
                "RAWG API-nyckel.\n\n"
                "Hämta den från: https://rawg.io/apidocs\n"
                "(Tar ungefär 30 sekunder med ett konto.)\n\n"
                "Vill du öppna inställningarna nu?",
                parent=self,
            )
            if answer:
                SettingsDialog(self, self.config_mgr)
            return

        def on_select(local_path, result):
            self.cover_path = local_path
            self.cover_label.configure(text=self._cover_text())
            if result.get("year") and not self.year_entry.get().strip():
                self.year_entry.insert(0, str(result["year"]))

        CoverSearchDialog(self, item_type, title, rawg_key, on_select)

    def _save(self):
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showwarning("Saknas", "Titel måste anges.", parent=self)
            return

        rating_str = self.rating_entry.get().strip()
        rating = None
        if rating_str:
            try:
                rating = float(rating_str.replace(",", "."))
                if not 0 <= rating <= 10:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Fel",
                                       "Betyg måste vara ett tal mellan 0 och 10.",
                                       parent=self)
                return

        year_str = self.year_entry.get().strip()
        year = None
        if year_str:
            try:
                year = int(year_str)
            except ValueError:
                messagebox.showwarning("Fel", "År måste vara ett heltal.",
                                       parent=self)
                return
        to_be_played_watched_value = self.to_be_played_watched.get()

        data = {
            "title": title,
            "type": self.type_var.get(),
            "rating": rating,
            "year": year,
            "notes": self.notes_text.get("1.0", "end").strip(),
            "cover_path": self.cover_path,
            "To_be_play_or_watched": to_be_played_watched_value
        }
        self.on_save(data)
        self.destroy()


# ---------- Kort ----------
class Card(ctk.CTkFrame):
    def __init__(self, parent, entry, on_click):
        super().__init__(
            parent, width=CARD_WIDTH, height=CARD_HEIGHT,
            fg_color=COLORS["card_bg"], corner_radius=12,
        )
        self.pack_propagate(False)
        self.entry = entry
        self.on_click = on_click
        self._photo_ref = None

        self._build()
        self._bind_recursive(self)

    def _build(self):
        cover_frame = ctk.CTkFrame(self, height=COVER_HEIGHT,
                                   fg_color="#15151c", corner_radius=8)
        cover_frame.pack(fill="x", padx=10, pady=(10, 8))
        cover_frame.pack_propagate(False)

        cover_path = self.entry.get("cover_path", "")
        if cover_path and os.path.exists(cover_path):
            try:
                img = Image.open(cover_path)
                img.thumbnail((CARD_WIDTH - 30, COVER_HEIGHT - 8))
                self._photo_ref = ctk.CTkImage(light_image=img, dark_image=img,
                                                size=img.size)
                ctk.CTkLabel(cover_frame, image=self._photo_ref, text=""
                             ).pack(expand=True)
            except Exception:
                self._placeholder(cover_frame)
        else:
            self._placeholder(cover_frame)

        is_game = self.entry.get("type") == "game"
        type_color = COLORS["game_color"] if is_game else COLORS["anime_color"]
        type_text = "🎮 SPEL" if is_game else "🌸 ANIME"
        ctk.CTkLabel(self, text=type_text, font=("Helvetica", 18, "bold"),
                     text_color=type_color, anchor="w").pack(fill="x", padx=12)

        title = self.entry.get("title", "Untitled")
        if len(title) > 28:
            title = title[:26] + "…"
        ctk.CTkLabel(self, text=title, font=("Helvetica", 20, "bold"),
                     text_color=COLORS["text"], anchor="w"
                     ).pack(fill="x", padx=12, pady=(2, 0))

        meta_parts = []
        if self.entry.get("rating") is not None:
            meta_parts.append(f"★ {self.entry['rating']}/10")
        if self.entry.get("year"):
            meta_parts.append(str(self.entry["year"]))
        ctk.CTkLabel(self, text="  ·  ".join(meta_parts),
                     font=("Helvetica", 16),
                     text_color=COLORS["text_dim"], anchor="w"
                     ).pack(fill="x", padx=12, pady=(0, 10))

    def _placeholder(self, parent):
        emoji = "🎮" if self.entry.get("type") == "game" else "🌸"
        ctk.CTkLabel(parent, text=emoji, font=("Helvetica", 60)).pack(expand=True)

    def _bind_recursive(self, widget):
        widget.bind("<Button-1>", lambda e: self.on_click(self.entry))
        widget.bind("<Enter>", lambda e: self.configure(fg_color=COLORS["card_hover"]))
        widget.bind("<Leave>", lambda e: self.configure(fg_color=COLORS["card_bg"]))
        for child in widget.winfo_children():
            self._bind_recursive(child)


# ---------- Detaljvy ----------
class DetailDialog(ctk.CTkToplevel):
    def __init__(self, parent, entry, on_edit, on_delete):
        super().__init__(parent)
        self.title(entry.get("title", "Detaljer"))
        self.geometry("580x680")
        self.transient(parent)
        self.after(100, self.grab_set)

        self.entry = entry
        self.on_edit = on_edit
        self.on_delete = on_delete
        self._photo_ref = None

        self._build()

    def _build(self):
        container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=(24, 0))

        cover_path = self.entry.get("cover_path", "")
        if cover_path and os.path.exists(cover_path):
            try:
                img = Image.open(cover_path)
                img.thumbnail((420, 320))
                self._photo_ref = ctk.CTkImage(light_image=img, dark_image=img,
                                                size=img.size)
                ctk.CTkLabel(container, image=self._photo_ref, text=""
                             ).pack(pady=(0, 14))
            except Exception:
                pass

        is_game = self.entry.get("type") == "game"
        type_color = COLORS["game_color"] if is_game else COLORS["anime_color"]
        type_text = "🎮 SPEL" if is_game else "🌸 ANIME"
        ctk.CTkLabel(container, text=type_text, font=("Helvetica", 12, "bold"),
                     text_color=type_color).pack(anchor="w")

        ctk.CTkLabel(container, text=self.entry.get("title", "Untitled"),
                     font=("Helvetica", 24, "bold"), wraplength=500,
                     justify="left", anchor="w"
                     ).pack(anchor="w", fill="x", pady=(4, 8))

        meta_parts = []
        if self.entry.get("rating") is not None:
            meta_parts.append(f"★ {self.entry['rating']}/10")
        if self.entry.get("year"):
            meta_parts.append(str(self.entry["year"]))
        if meta_parts:
            ctk.CTkLabel(container, text="  ·  ".join(meta_parts),
                         font=("Helvetica", 13), text_color=COLORS["text_dim"]
                         ).pack(anchor="w", pady=(0, 14))

        notes = self.entry.get("notes", "")
        if notes:
            ctk.CTkLabel(container, text="ANTECKNINGAR",
                         font=("Helvetica", 11, "bold"),
                         text_color=COLORS["text_dim"]
                         ).pack(anchor="w", pady=(8, 4))
            notes_box = ctk.CTkTextbox(container, height=200, wrap="word",
                                        fg_color=COLORS["card_bg"])
            notes_box.pack(fill="x", pady=(0, 12))
            notes_box.insert("1.0", notes)
            notes_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=20)
        ctk.CTkButton(btn_frame, text="Stäng", fg_color="gray30",
                      hover_color="gray25", width=100,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Ta bort", fg_color=COLORS["danger"],
                      hover_color="#b91c1c", width=100,
                      command=self._delete).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Redigera", width=100,
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      command=self._edit).pack(side="right")

    def _edit(self):
        self.destroy()
        self.on_edit(self.entry)

    def _delete(self):
        if messagebox.askyesno(
            "Bekräfta",
            f"Vill du verkligen ta bort \"{self.entry.get('title')}\"?",
            parent=self,
        ):
            self.on_delete(self.entry["id"])
            self.destroy()


# ---------- Huvudfönster ----------
class HallOfFameApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🏆 Hall of Fame")
        self.geometry("1920x1080")
        self.minsize(1920, 1080)
        self.configure(fg_color=COLORS["bg"])
        self.resizable(True, False)

        self.data = DataManager(DATA_FILE)
        self.config_mgr = ConfigManager(CONFIG_FILE)
        self.current_filter = "all"
        self.search_query = ""

        self._build()
        self._render()

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 0))

        ctk.CTkLabel(header, text="🏆 Hall of Fame",
                     font=("Helvetica", 28, "bold"),
                     text_color=COLORS["text"]).pack(side="left")

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right")

        ctk.CTkButton(right, text="⚙️", width=42, height=38,
                      font=("Helvetica", 16),
                      fg_color="gray25", hover_color="gray20",
                      command=self._open_settings).pack(side="left", padx=(0, 8))

        ctk.CTkButton(right, text="+ Lägg till", height=38, width=130,
                      font=("Helvetica", 13, "bold"),
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      command=self._add_entry).pack(side="left")

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=24, pady=(16, 8))

        self.filter_buttons = {}
        for key, label in [("all", "Alla"), ("game", "🎮 Spel"), ("anime", "🌸 Anime")]:
            btn = ctk.CTkButton(
                controls, text=label, height=32, width=90,
                fg_color=COLORS["accent"] if key == "all" else "gray25",
                hover_color=COLORS["accent_hover"] if key == "all" else "gray20",
                command=lambda k=key: self._set_filter(k),
            )
            btn.pack(side="left", padx=(0, 8))
            self.filter_buttons[key] = btn

        self.search_entry = ctk.CTkEntry(controls, placeholder_text="🔍 Sök titel...",
                                          height=32, width=240)
        self.search_entry.pack(side="right")
        self.search_entry.bind("<KeyRelease>", self._on_search)

        self.counter_label = ctk.CTkLabel(self, text="", anchor="w",
                                           text_color=COLORS["text_dim"],
                                           font=("Helvetica", 12))
        self.counter_label.pack(fill="x", padx=24, pady=(0, 8))

        self.grid_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _open_settings(self):
        SettingsDialog(self, self.config_mgr)

    def _set_filter(self, key):
        self.current_filter = key
        for k, btn in self.filter_buttons.items():
            btn.configure(
                fg_color=COLORS["accent"] if k == key else "gray25",
                hover_color=COLORS["accent_hover"] if k == key else "gray20",
            )
        self._render()

    def _on_search(self, _event):
        self.search_query = self.search_entry.get()
        self._render()

    def _render(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()

        entries = self.data.filter(self.current_filter, self.search_query)

        total = len(self.data.entries)
        games = sum(1 for e in self.data.entries if e.get("type") == "game")
        animes = sum(1 for e in self.data.entries if e.get("type") == "anime")
        self.counter_label.configure(
            text=f"Visar {len(entries)} av {total}  ·  {games} spel · {animes} anime"
        )

        if not entries:
            msg = ("Inga poster matchar sökningen."
                   if self.data.entries
                   else "Tom Hall of Fame.\nKlicka på \"+ Lägg till\" för att börja.")
            ctk.CTkLabel(self.grid_frame, text=msg,
                         font=("Helvetica", 14),
                         text_color=COLORS["text_dim"]).pack(pady=80)
            return

        def sort_key(e):
            rating = e.get("rating") if e.get("rating") is not None else -1
            try:
                ts = datetime.fromisoformat(e.get("date_added", "")).timestamp()
            except ValueError:
                ts = 0
            return (-rating, -ts)

        entries.sort(key=sort_key)

        cols = 4
        # Räkna ut antal kolumner baserat på faktisk bredd
        self.grid_frame.update_idletasks()
        available_width = self.grid_frame.winfo_width()
        if available_width <= 1:
            available_width = 1880  # fallback vid första rendern
        cols = max(1, available_width // (CARD_WIDTH + 20))  # 20 = padx*2

        for i, entry in enumerate(entries):
            row, col = divmod(i, cols)
            card = Card(self.grid_frame, entry, on_click=self._show_detail)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nw")

        # weight=0 = kolumner sträcks INTE ut, korten packas tätt till vänster
        for c in range(cols):
            self.grid_frame.grid_columnconfigure(c, weight=0)

    def _add_entry(self):
        EntryDialog(self, on_save=self._save_new, config=self.config_mgr)

    def _save_new(self, data):
        self.data.add(data)
        self._render()

    def _show_detail(self, entry):
        DetailDialog(self, entry, on_edit=self._edit_entry,
                     on_delete=self._delete_entry)

    def _edit_entry(self, entry):
        def save(updated):
            self.data.update(entry["id"], updated)
            self._render()
        EntryDialog(self, on_save=save, config=self.config_mgr, entry=entry)

    def _delete_entry(self, entry_id):
        self.data.delete(entry_id)
        self._render()


if __name__ == "__main__":
    app = HallOfFameApp()
    app.mainloop()
