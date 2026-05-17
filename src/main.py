import os
import sys
import re
import zlib
import struct
import shutil
import threading
import queue
import webbrowser
from pathlib import Path
# pyrefly: ignore [missing-import]
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Safely locate the project root directory when running natively
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

# --- GUI Color Theme System (Based on Base Color #A3D9D4) ---
BG_COLOR = "#12141a"            # Very deep charcoal black
CARD_COLOR = "#1b1d24"          # Slightly lighter slate grey card back
ACCENT_COLOR = "#A3D9D4"        # Primary pastel teal/mint
ACCENT_HOVER_COLOR = "#8bc4bf"  # Slightly darker hover state teal
ACCENT_MUTED = "#2e4845"        # Very deep/dark teal for passive borders
GREEN_COLOR = "#57c22d"         # Action success glowing green
RED_COLOR = "#d9534f"           # Safety warning/delete red
TEXT_PRIMARY = "#ffffff"        # High-contrast white
TEXT_SECONDARY = "#8b949e"      # Muted grey text
TEXT_DARK = "#12141a"           # Text color on light button backgrounds

# Configure CustomTkinter default styling
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")  # Using default system theme as base, overrides below

class ToolTip:
    """Helper to attach sleek floating tooltips to widgets."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + self.widget.winfo_rooty() + 20
        self.tip_window = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        
        # Sleek popup window styling
        frame = ctk.CTkFrame(tw, fg_color="#1f232b", border_color=ACCENT_COLOR, border_width=1, corner_radius=6)
        frame.pack(padx=1, pady=1)
        label = ctk.CTkLabel(frame, text=self.text, font=("Inter", 11), text_color=TEXT_PRIMARY, justify="left", wraplength=200)
        label.pack(padx=8, pady=5)

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

class SymlinkManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Steam Deck Symlink Manager")
        self.geometry("900x700")
        self.configure(fg_color=BG_COLOR)
        
        # Set main icon window minimum size
        self.minsize(800, 600)
        
        # Load custom app logos if they exist
        self.logo_image = None
        try:
            icon_large_path = resource_path("assets/icon_large.png")
            if os.path.exists(icon_large_path):
                pil_img = Image.open(icon_large_path)
                # Keep scale 1:1, sizing at 48x48 fits perfectly inside the header
                self.logo_image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(48, 48))
        except Exception:
            pass
            
        # Set Window Taskbar/Desktop Icon
        try:
            icon_small_path = resource_path("assets/icon_small.png")
            if os.path.exists(icon_small_path):
                img = Image.open(icon_small_path)
                photo = ImageTk.PhotoImage(img)
                self.iconphoto(False, photo)
        except Exception:
            pass
        
        # State variables
        self.steam_path_var = ctk.StringVar()
        self.sd_path_var = ctk.StringVar()
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self.filter_games)
        
        self.games_data = []         # Master list of scanned compatdata directories
        self.resolved_names = {}     # Dictionary of appid -> game_name
        self.size_cache = {}         # Dictionary of path -> size_bytes
        self.size_threads = {}       # Active threads computing sizes
        self.active_tab = "all"      # current list filter: all, ssd, sd
        
        # Load local JSON cache of resolved AppIDs to avoid redundant scans/requests
        self.cache_file = Path(sys.argv[0]).parent / "resolved_names_cache.json"
        self.load_local_cache()

        # Background worker queue for safe multithreaded file operations
        self.op_queue = queue.Queue()
        
        # Auto-discover initial directories
        self.discover_paths()
        
        # Scan game manifests & shortcuts in background
        self.load_game_names_async()
        
        # Build UI layout
        self.create_widgets()
        
        # Start scanning directory compatdata
        self.scan_compatdata()
        
        # Poll operation queue for background worker updates
        self.poll_queue()

    def load_local_cache(self):
        """Loads cached AppID -> Game Name mappings from a local JSON file."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    import json
                    cached = json.load(f)
                    self.resolved_names.update(cached)
        except Exception:
            pass

    def save_local_cache(self):
        """Saves current resolved names map to a local JSON cache file."""
        try:
            import json
            # Only save actual names, filter out placeholders like "Game ID: XXX"
            to_save = {k: v for k, v in self.resolved_names.items() if not v.startswith("Game ID:")}
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(to_save, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # --- Path Auto-Discovery & File Resolvers ---
    
    def discover_paths(self):
        """Auto-detect Steam paths and SD card mount points on Linux & Windows."""
        is_linux = sys.platform.startswith("linux")
        
        detected_steam = ""
        detected_sd = ""
        
        if is_linux:
            # Check native Steam install path
            native_steam = Path("/home/deck/.local/share/Steam")
            # Check Flatpak Steam install path
            flatpak_steam = Path("/home/deck/.var/app/com.valvesoftware.Steam/.local/share/Steam")
            
            if native_steam.exists():
                detected_steam = str(native_steam)
            elif flatpak_steam.exists():
                detected_steam = str(flatpak_steam)
                
            # Scan /run/media/ for SD cards
            media_root = Path("/run/media")
            if media_root.exists():
                found_drives = []
                try:
                    # Traverse /run/media/ and /run/media/deck/ to find mounted directories
                    for child in media_root.iterdir():
                        if child.is_dir():
                            if child.name == "deck":
                                for sd_card in child.iterdir():
                                    if sd_card.is_dir():
                                        found_drives.append(sd_card)
                            else:
                                found_drives.append(child)
                except Exception:
                    pass
                
                # Check for existing SteamLibrary on detected drives
                for drive in found_drives:
                    sd_library = drive / "SteamLibrary"
                    if sd_library.exists():
                        detected_sd = str(sd_library / "steamapps" / "compatdata")
                        break
                    elif (drive / "steamapps").exists():
                        detected_sd = str(drive / "steamapps" / "compatdata")
                        break
                        
                # If no SteamLibrary found, but we did find a mounted drive, suggest creating it there!
                if not detected_sd and found_drives:
                    detected_sd = str(found_drives[0] / "SteamLibrary" / "steamapps" / "compatdata")
        else:
            # Windows fallback paths for local developer testing
            detected_steam = r"C:\Program Files (x86)\Steam"
            detected_sd = r"D:\SteamLibrary\steamapps\compatdata"
            
        self.steam_path_var.set(detected_steam)
        self.sd_path_var.set(detected_sd)

    def load_game_names_async(self):
        """Launches a thread to parse .acf manifests and shortcuts.vdf to resolve AppIDs."""
        threading.Thread(target=self._resolve_names_worker, daemon=True).start()

    def _resolve_names_worker(self):
        steam_base = Path(self.steam_path_var.get())
        if not steam_base.exists():
            return
            
        temp_names = {}
        
        # 1. Parse Internal Steam Apps (.acf manifests)
        steamapps_internal = steam_base / "steamapps"
        if steamapps_internal.exists():
            self._parse_manifests(steamapps_internal, temp_names)
            
        # 2. Parse external Steam Apps (on SD card if mounted)
        sd_path = self.sd_path_var.get()
        if sd_path:
            # Extract the steamapps root directory from SD path
            sd_steamapps = Path(sd_path).parent
            if sd_steamapps.exists() and sd_steamapps.name == "steamapps":
                self._parse_manifests(sd_steamapps, temp_names)
                
        # 3. Parse Non-Steam Shortcuts (shortcuts.vdf)
        userdata_dir = steam_base / "userdata"
        if userdata_dir.exists():
            for user_id in userdata_dir.iterdir():
                vdf_path = user_id / "config" / "shortcuts.vdf"
                if vdf_path.exists():
                    self._parse_shortcuts_binary(vdf_path, temp_names)
                    
        self.resolved_names.update(temp_names)
        self.save_local_cache()
        self.log_message(f"Resolved {len(self.resolved_names)} game names from manifests and shortcuts.")
        # Trigger an update of the GUI labels in the main thread
        self.after(0, self.refresh_game_display_names)

    def _parse_manifests(self, path, name_dict):
        """Parse all appmanifest_[ID].acf files in a library directory."""
        for acf_file in path.glob("appmanifest_*.acf"):
            try:
                with open(acf_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                appid_match = re.search(r'"appid"\s+"(\d+)"', content)
                name_match = re.search(r'"name"\s+"([^"]+)"', content)
                if appid_match and name_match:
                    name_dict[appid_match.group(1)] = name_match.group(2)
            except Exception:
                pass

    def _parse_shortcuts_binary(self, filepath, name_dict):
        """Parse Valve binary shortcuts.vdf file to resolve non-Steam shortcuts."""
        try:
            with open(filepath, "rb") as f:
                data = f.read()
        except Exception:
            return
            
        idx = 0
        def read_str():
            nonlocal idx
            start = idx
            while idx < len(data) and data[idx] != 0:
                idx += 1
            s = data[start:idx].decode("utf-8", errors="ignore")
            idx += 1 # skip null byte
            return s
            
        def read_int32():
            nonlocal idx
            val = struct.unpack("<I", data[idx:idx+4])[0]
            idx += 4
            return val

        try:
            if len(data) < 10 or data[idx] != 0:
                return
            idx += 1
            root_key = read_str()
            if root_key != "shortcuts":
                return
                
            while idx < len(data):
                type_byte = data[idx]
                idx += 1
                if type_byte == 8: # End of root dictionary
                    break
                    
                read_str() # skip index key
                
                shortcut = {}
                while idx < len(data):
                    t = data[idx]
                    idx += 1
                    if t == 8: # End of shortcut entry dictionary
                        break
                        
                    key = read_str()
                    if t == 1:
                        val = read_str()
                        shortcut[key] = val
                    elif t == 2:
                        val = read_int32()
                        shortcut[key] = val
                    elif t == 0:
                        # Skip nested sub-dictionaries (like tags)
                        read_str()
                        depth = 1
                        while idx < len(data) and depth > 0:
                            nt = data[idx]
                            idx += 1
                            if nt == 8:
                                depth -= 1
                            elif nt == 0:
                                depth += 1
                                read_str()
                            elif nt == 1:
                                read_str()
                                read_str()
                            elif nt == 2:
                                read_str()
                                idx += 4
                                
                appname = shortcut.get("AppName", "")
                appid = shortcut.get("appid", 0)
                
                if appname and appid:
                    # Resolve to unsigned 32-bit integer representing folder name
                    unsigned_appid = appid & 0xffffffff
                    name_dict[str(unsigned_appid)] = appname
                    
                    # Also pre-calculate secondary CRC32 hash fallback used by newer steam clients
                    exe = shortcut.get("Exe", "")
                    if exe:
                        key_str = f'"{exe}"{appname}'
                        crc = zlib.crc32(key_str.encode("utf-8"))
                        calc_appid = (crc & 0xffffffff) | 0x80000000
                        name_dict[str(calc_appid)] = appname
        except Exception:
            pass

    def fetch_missing_names_online_async(self):
        """Starts a background thread to fetch unresolved AppID names from the Steam Store API."""
        unresolved_ids = []
        for game in self.games_data:
            if game["name"] == f"Game ID: {game['appid']}":
                unresolved_ids.append(game["appid"])
                
        if unresolved_ids:
            threading.Thread(target=self._online_resolver_worker, args=(unresolved_ids,), daemon=True).start()

    def _online_resolver_worker(self, appids):
        import urllib.request
        import json
        import ssl
        import time
        
        self.log_message(f"Checking Steam online store registry for {len(appids)} legacy folder IDs...")
        
        # 1. Fetch from the high-performance daily-updated community database mirror
        mirror_url = "https://raw.githubusercontent.com/dgibbs64/SteamCMD-AppID-List/master/steamcmd_appid.json"
        lookup_map = {}
        try:
            req = urllib.request.Request(
                mirror_url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            ctx = ssl._create_unverified_context()
            self.log_message("Connecting to Steam database mirror...")
            with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
                self.log_message("Database mirror fetched successfully! Indexing catalog...")
                raw_data = response.read().decode('utf-8')
                data = json.loads(raw_data)
                if isinstance(data, list):
                    lookup_map = {str(app.get("appid")): app.get("name") for app in data if isinstance(app, dict) and "appid" in app}
                    self.log_message(f"Mirror indexed: {len(lookup_map)} titles found!")
                else:
                    self.log_message("Warning: Unexpected JSON format from mirror.")
        except Exception as e:
            self.log_message(f"Failed to fetch database mirror: {e}")
            
        # 2. Resolve whatever matches we can find in the mirror
        resolved_any = False
        matched_count = 0
        unresolved_remaining = []
        
        for appid in appids:
            # Double check in case it was resolved in the meantime
            if appid in self.resolved_names and self.resolved_names[appid] != f"Game ID: {appid}":
                continue
                
            game_name = lookup_map.get(str(appid))
            if game_name:
                self.resolved_names[str(appid)] = game_name
                self.log_message(f"Resolved from mirror: App ID {appid} -> '{game_name}'")
                resolved_any = True
                matched_count += 1
            else:
                unresolved_remaining.append(appid)
                
        self.log_message(f"Mirror pass: successfully matched {matched_count} / {len(appids)} folder IDs.")
        
        # 3. For any remaining unresolved IDs (e.g. brand new games or DLCs), query official store API
        if unresolved_remaining:
            self.log_message(f"Querying Steam Store API for {len(unresolved_remaining)} remaining unresolved items...")
            ctx = ssl._create_unverified_context()
            
            for i, appid in enumerate(unresolved_remaining):
                if i > 0:
                    time.sleep(0.5) # Gentle rate-limit spacing
                    
                url = f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=basic"
                try:
                    req = urllib.request.Request(
                        url, 
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                    )
                    with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                        res_data = json.loads(response.read().decode('utf-8'))
                        if res_data and str(appid) in res_data and res_data[str(appid)].get("success"):
                            game_name = res_data[str(appid)]["data"].get("name")
                            if game_name:
                                self.resolved_names[str(appid)] = game_name
                                self.log_message(f"Live resolved: App ID {appid} -> '{game_name}'")
                                resolved_any = True
                except Exception as e:
                    self.log_message(f"Could not resolve App ID {appid} from Live API: {e}")
                    
        if resolved_any:
            self.save_local_cache()
            self.after(0, self.refresh_game_display_names)
            
        self.log_message("Online folder name lookup complete.")

    # --- Scanning & Processing Filesystem Tasks ---

    def scan_compatdata(self):
        """Scans the internal compatdata folder and indexes subfolders."""
        steam_base = self.steam_path_var.get()
        if not steam_base:
            self.log_message("Error: Steam Base path not defined.")
            return
            
        compatdata_dir = Path(steam_base) / "steamapps" / "compatdata"
        if not compatdata_dir.exists():
            # Check flatpak path as fallback
            flatpak_compat = Path("/home/deck/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata")
            if flatpak_compat.exists():
                compatdata_dir = flatpak_compat
                self.steam_path_var.set("/home/deck/.var/app/com.valvesoftware.Steam/.local/share/Steam")
            else:
                self.log_message(f"Error: Internal compatdata directory not found at {compatdata_dir}")
                return
                
        self.log_message(f"Scanning compatdata directory: {compatdata_dir}")
        self.games_data = []
        
        try:
            for item in compatdata_dir.iterdir():
                # Compatdata folder names are AppIDs (integers)
                if item.is_dir() and item.name.isdigit():
                    appid = item.name
                    is_symlink = item.is_symlink()
                    
                    target_path = ""
                    if is_symlink:
                        try:
                            target_path = os.readlink(item)
                        except Exception:
                            target_path = "Unknown Link Location"
                            
                    game_name = self.resolved_names.get(appid, f"Game ID: {appid}")
                    
                    # Set up game data model
                    game_info = {
                        "appid": appid,
                        "name": game_name,
                        "path": str(item),
                        "is_symlink": is_symlink,
                        "target_path": target_path,
                        "size": "Scanning...",
                        "size_bytes": 0
                    }
                    
                    self.games_data.append(game_info)
                    
                    # Trigger async size calculation
                    self.calculate_size_async(game_info)
        except Exception as e:
            self.log_message(f"Error reading compatdata directory: {e}")
            
        self.filter_games()
        self.update_storage_summary()
        self.fetch_missing_names_online_async()

    def calculate_size_async(self, game_info):
        """Calculates directory size recursively in a separate thread so GUI doesn't lag."""
        path_to_scan = game_info["target_path"] if game_info["is_symlink"] else game_info["path"]
        
        # Check cache first
        if path_to_scan in self.size_cache:
            size_bytes = self.size_cache[path_to_scan]
            game_info["size_bytes"] = size_bytes
            game_info["size"] = self.format_size(size_bytes)
            self.after(0, self.refresh_single_row_size, game_info)
            return

        def size_worker():
            total = 0
            try:
                # Walk the path and sum files
                p = Path(path_to_scan)
                if p.exists():
                    for root, dirs, files in os.walk(path_to_scan):
                        for f in files:
                            fp = os.path.join(root, f)
                            if not os.path.islink(fp):
                                total += os.path.getsize(fp)
            except Exception:
                pass
                
            self.size_cache[path_to_scan] = total
            game_info["size_bytes"] = total
            game_info["size"] = self.format_size(total)
            
            # Post back to GUI main thread
            self.after(0, self.refresh_single_row_size, game_info)
            self.after(0, self.update_storage_summary)
            
        t = threading.Thread(target=size_worker, daemon=True)
        self.size_threads[path_to_scan] = t
        t.start()

    def format_size(self, size_bytes):
        """Formulate readable byte size representation."""
        if size_bytes == 0:
            return "0 Bytes"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    # --- UI Grid Drawing & Component Creation ---

    def create_widgets(self):
        # 1. Top Title & Space Reclaimed Header Card
        self.header_frame = ctk.CTkFrame(self, fg_color=CARD_COLOR, height=100, border_color=ACCENT_MUTED, border_width=1, corner_radius=10)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 10))
        self.header_frame.pack_propagate(False)
        
        # Brand new high-fidelity logo next to title
        if self.logo_image:
            self.logo_label = ctk.CTkLabel(self.header_frame, image=self.logo_image, text="")
            self.logo_label.pack(side="left", padx=(25, 5), pady=20)
            self.title_label = ctk.CTkLabel(self.header_frame, text="STEAM DECK SYMLINK MANAGER", font=("Outfit", 20, "bold"), text_color=ACCENT_COLOR)
            self.title_label.pack(side="left", padx=(5, 25), pady=20)
        else:
            self.title_label = ctk.CTkLabel(self.header_frame, text="STEAM DECK SYMLINK MANAGER", font=("Outfit", 20, "bold"), text_color=ACCENT_COLOR)
            self.title_label.pack(side="left", padx=25, pady=20)
        
        # Large dashboard metrics card
        self.stats_frame = ctk.CTkFrame(self.header_frame, fg_color="#12141a", border_color=ACCENT_MUTED, border_width=1, corner_radius=8)
        self.stats_frame.pack(side="right", padx=25, pady=15, fill="y")
        
        self.stats_title = ctk.CTkLabel(self.stats_frame, text="SSD SPACE RECLAIMED", font=("Inter", 9, "bold"), text_color=TEXT_SECONDARY)
        self.stats_title.pack(padx=15, pady=(5, 0))
        
        self.stats_value = ctk.CTkLabel(self.stats_frame, text="0.0 GB", font=("Outfit", 20, "bold"), text_color=GREEN_COLOR)
        self.stats_value.pack(padx=15, pady=(0, 5))
        
        # 2. Paths Management Panel (Collapsible/Editable)
        self.paths_frame = ctk.CTkFrame(self, fg_color=CARD_COLOR, border_color=ACCENT_MUTED, border_width=1, corner_radius=10)
        self.paths_frame.pack(fill="x", padx=15, pady=5)
        
        # Grid layout for settings paths
        self.paths_frame.columnconfigure(1, weight=1)
        
        # Internal Steam path
        lbl_steam = ctk.CTkLabel(self.paths_frame, text="Internal Steam Directory:", font=("Inter", 12, "bold"), text_color=TEXT_SECONDARY)
        lbl_steam.grid(row=0, column=0, padx=(15, 10), pady=(12, 6), sticky="w")
        
        entry_steam = ctk.CTkEntry(self.paths_frame, textvariable=self.steam_path_var, font=("Courier", 11), fg_color="#12141a", border_color=ACCENT_MUTED, text_color=TEXT_PRIMARY, corner_radius=6)
        entry_steam.grid(row=0, column=1, padx=5, pady=(12, 6), sticky="ew")
        
        btn_steam_browse = ctk.CTkButton(self.paths_frame, text="Browse", width=70, font=("Inter", 11, "bold"), fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER_COLOR, text_color=TEXT_DARK, corner_radius=6, command=self.browse_steam_path)
        btn_steam_browse.grid(row=0, column=2, padx=(5, 15), pady=(12, 6))
        ToolTip(btn_steam_browse, "Specify the directory where Steam is installed.")
        
        # SD Card mount path
        lbl_sd = ctk.CTkLabel(self.paths_frame, text="SD Card Destination:", font=("Inter", 12, "bold"), text_color=TEXT_SECONDARY)
        lbl_sd.grid(row=1, column=0, padx=(15, 10), pady=(6, 12), sticky="w")
        
        entry_sd = ctk.CTkEntry(self.paths_frame, textvariable=self.sd_path_var, font=("Courier", 11), fg_color="#12141a", border_color=ACCENT_MUTED, text_color=TEXT_PRIMARY, corner_radius=6)
        entry_sd.grid(row=1, column=1, padx=5, pady=(6, 12), sticky="ew")
        
        btn_sd_browse = ctk.CTkButton(self.paths_frame, text="Browse", width=70, font=("Inter", 11, "bold"), fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER_COLOR, text_color=TEXT_DARK, corner_radius=6, command=self.browse_sd_path)
        btn_sd_browse.grid(row=1, column=2, padx=(5, 15), pady=(6, 12))
        ToolTip(btn_sd_browse, "Set custom path on the SD card to move compatdata to.")
        
        # 3. Actions & Search Filters Control Panel
        self.control_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.control_frame.pack(fill="x", padx=15, pady=(10, 5))
        
        # Search bar
        self.search_entry = ctk.CTkEntry(self.control_frame, textvariable=self.search_var, placeholder_text="Search game by Name or ID...", font=("Inter", 12), fg_color=CARD_COLOR, border_color=ACCENT_MUTED, border_width=1, corner_radius=8, width=280)
        self.search_entry.pack(side="left", fill="y", pady=2)
        
        # Filter Tabs
        self.tabs_frame = ctk.CTkFrame(self.control_frame, fg_color=CARD_COLOR, border_color=ACCENT_MUTED, border_width=1, corner_radius=8)
        self.tabs_frame.pack(side="left", padx=15)
        
        self.btn_tab_all = ctk.CTkButton(self.tabs_frame, text="All", width=60, font=("Inter", 11, "bold"), fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER_COLOR, text_color=TEXT_DARK, corner_radius=6, command=lambda: self.set_active_filter("all"))
        self.btn_tab_all.pack(side="left", padx=2, pady=2)
        
        self.btn_tab_ssd = ctk.CTkButton(self.tabs_frame, text="SSD", width=60, font=("Inter", 11, "bold"), fg_color="transparent", hover_color=ACCENT_MUTED, text_color=TEXT_SECONDARY, corner_radius=6, command=lambda: self.set_active_filter("ssd"))
        self.btn_tab_ssd.pack(side="left", padx=2, pady=2)
        ToolTip(self.btn_tab_ssd, "Show games residing on internal SSD storage.")
        
        self.btn_tab_sd = ctk.CTkButton(self.tabs_frame, text="SD Card", width=70, font=("Inter", 11, "bold"), fg_color="transparent", hover_color=ACCENT_MUTED, text_color=TEXT_SECONDARY, corner_radius=6, command=lambda: self.set_active_filter("sd"))
        self.btn_tab_sd.pack(side="left", padx=2, pady=2)
        ToolTip(self.btn_tab_sd, "Show symlinked games relocated to external SD card.")
        
        # Refresh Scan Button
        self.btn_refresh = ctk.CTkButton(self.control_frame, text="Scan Folders", width=100, font=("Inter", 12, "bold"), fg_color=ACCENT_COLOR, hover_color=ACCENT_HOVER_COLOR, text_color=TEXT_DARK, corner_radius=8, command=self.scan_compatdata)
        self.btn_refresh.pack(side="right", fill="y", pady=2)
        
        # 4. Games Library List Container (Scrollable Scrollbar)
        self.library_frame = ctk.CTkScrollableFrame(self, fg_color=BG_COLOR, border_color=ACCENT_MUTED, border_width=1, corner_radius=10)
        self.library_frame.pack(fill="both", expand=True, padx=15, pady=(5, 10))
        
        # Empty placeholder state label
        self.empty_label = ctk.CTkLabel(self.library_frame, text="No games found. Check your Steam paths above or scan folders.", font=("Inter", 14), text_color=TEXT_SECONDARY)
        
        # 5. Status Console & Logs / Progress Indicators
        self.status_frame = ctk.CTkFrame(self, fg_color=CARD_COLOR, height=130, border_color=ACCENT_MUTED, border_width=1, corner_radius=10)
        self.status_frame.pack(fill="x", padx=15, pady=(5, 15))
        self.status_frame.pack_propagate(False)
        
        # Console logs output textbox
        self.log_text = ctk.CTkTextbox(self.status_frame, fg_color="#12141a", font=("Courier", 10), border_color=ACCENT_MUTED, border_width=1, text_color=TEXT_SECONDARY, corner_radius=6)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        self.log_text.configure(state="disabled")
        
        # Progress Indicator Panel
        self.progress_panel = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.progress_panel.pack(fill="x", padx=10, pady=(0, 10))
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_panel, height=8, progress_color=ACCENT_COLOR, fg_color="#12141a")
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_bar.set(0)
        
        self.status_lbl = ctk.CTkLabel(self.progress_panel, text="Idle", font=("Inter", 11, "bold"), text_color=TEXT_SECONDARY, width=120, anchor="e")
        self.status_lbl.pack(side="right")

    # --- Core UI Rendering & Dynamically Refreshing Grid ---

    def filter_games(self, *args):
        """Applies Search text query and Filter tabs to refresh game widgets list."""
        search_query = self.search_var.get().strip().lower()
        
        # Empty existing layout inside the scrollable container
        for widget in self.library_frame.winfo_children():
            if widget != getattr(self, 'empty_label', None):
                widget.destroy()
            
        filtered_list = []
        for game in self.games_data:
            # Search Filter match
            name_match = search_query in game["name"].lower() or search_query in game["appid"]
            if not name_match:
                continue
                
            # Tab selection filter match
            if self.active_tab == "ssd" and game["is_symlink"]:
                continue
            elif self.active_tab == "sd" and not game["is_symlink"]:
                continue
                
            filtered_list.append(game)
            
        # Draw game list items
        if not filtered_list:
            self.empty_label.pack(pady=50)
            return
            
        self.empty_label.pack_forget()
        
        # Render rows dynamically
        for game in filtered_list:
            row_frame = ctk.CTkFrame(self.library_frame, fg_color=CARD_COLOR, height=60, border_color=ACCENT_MUTED, border_width=1, corner_radius=8)
            row_frame.pack(fill="x", pady=4, padx=5)
            row_frame.pack_propagate(False)
            
            # Left: Game details (Name, Badge)
            info_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            info_frame.pack(side="left", padx=15, fill="y")
            
            # Title & AppID side by side
            title_container = ctk.CTkFrame(info_frame, fg_color="transparent")
            title_container.pack(anchor="w", pady=(8, 0))
            
            game_title = ctk.CTkLabel(title_container, text=game["name"], font=("Inter", 13, "bold"), text_color=TEXT_PRIMARY)
            game_title.pack(side="left")
            
            badge = ctk.CTkLabel(title_container, text=f"ID: {game['appid']}", font=("Courier", 10), fg_color="#12141a", text_color=TEXT_SECONDARY, corner_radius=4, height=18)
            badge.pack(side="left", padx=10)
            
            # Subtext
            subtext_val = "Symlinked to SD Card" if game["is_symlink"] else "Stored on Internal SSD"
            subtext = ctk.CTkLabel(info_frame, text=subtext_val, font=("Inter", 10), text_color=TEXT_SECONDARY)
            subtext.pack(anchor="w")
            
            # Right Actions container
            actions_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
            actions_frame.pack(side="right", padx=15, fill="y")
            
            # Size metric
            size_lbl = ctk.CTkLabel(actions_frame, text=game["size"], font=("Inter", 12, "bold"), text_color=TEXT_PRIMARY, width=80)
            size_lbl.pack(side="left", padx=15, pady=15)
            game["size_widget"] = size_lbl # Keep a ref to update dynamically
            
            # Glowing Status Badge Pill
            status_pill = ctk.CTkLabel(
                actions_frame, 
                text="LINKED" if game["is_symlink"] else "SSD", 
                font=("Inter", 10, "bold"),
                fg_color=GREEN_COLOR if game["is_symlink"] else "#343a40",
                text_color=TEXT_DARK if game["is_symlink"] else TEXT_PRIMARY,
                width=65, 
                height=22, 
                corner_radius=11
            )
            status_pill.pack(side="left", padx=10, pady=19)
            
            # Primary operational button
            if game["is_symlink"]:
                btn = ctk.CTkButton(
                    actions_frame, 
                    text="Restore SSD", 
                    width=100, 
                    height=28,
                    font=("Inter", 11, "bold"), 
                    fg_color=ACCENT_COLOR, 
                    hover_color=ACCENT_HOVER_COLOR,
                    text_color=TEXT_DARK, 
                    corner_radius=6,
                    command=lambda g=game: self.execute_restore_prompt(g)
                )
                btn.pack(side="left", padx=5, pady=16)
                ToolTip(btn, "Deletes the link on SSD and moves the files back from the SD Card.")
            else:
                btn = ctk.CTkButton(
                    actions_frame, 
                    text="Move to SD", 
                    width=100, 
                    height=28,
                    font=("Inter", 11, "bold"), 
                    fg_color=ACCENT_COLOR, 
                    hover_color=ACCENT_HOVER_COLOR,
                    text_color=TEXT_DARK, 
                    corner_radius=6,
                    command=lambda g=game: self.execute_move_prompt(g)
                )
                btn.pack(side="left", padx=5, pady=16)
                ToolTip(btn, "Moves compatibility files to the SD Card and creates a symlink in its place.")
                
            # Secondary Delete Button (Safely free up space)
            btn_del = ctk.CTkButton(
                actions_frame,
                text="X",
                width=24,
                height=28,
                font=("Inter", 12, "bold"),
                fg_color="transparent",
                hover_color="#3a1e20",
                text_color=RED_COLOR,
                corner_radius=6,
                command=lambda g=game: self.execute_delete_prompt(g)
            )
            btn_del.pack(side="left", padx=(5, 0), pady=16)
            ToolTip(btn_del, "Deletes this game prefix to free up space (destroys saves unless backed up).")

    def refresh_single_row_size(self, game_info):
        """Updates the size display widget text once async size calculations return."""
        if "size_widget" in game_info and game_info["size_widget"].winfo_exists():
            game_info["size_widget"].configure(text=game_info["size"])

    def refresh_game_display_names(self):
        """Loops and matches scanned AppIDs with resolved names once VDF/ACF parsers complete."""
        resolved_count = 0
        for game in self.games_data:
            resolved = self.resolved_names.get(game["appid"])
            if resolved:
                game["name"] = resolved
                resolved_count += 1
        self.log_message(f"Refresh completed: {resolved_count} / {len(self.games_data)} game folder IDs resolved.")
        self.filter_games()

    def set_active_filter(self, tab):
        """Updates tab button colors and list rendering when tabs are toggled."""
        self.active_tab = tab
        
        # Reset colors
        self.btn_tab_all.configure(fg_color="transparent", text_color=TEXT_SECONDARY)
        self.btn_tab_ssd.configure(fg_color="transparent", text_color=TEXT_SECONDARY)
        self.btn_tab_sd.configure(fg_color="transparent", text_color=TEXT_SECONDARY)
        
        if tab == "all":
            self.btn_tab_all.configure(fg_color=ACCENT_COLOR, text_color=TEXT_DARK)
        elif tab == "ssd":
            self.btn_tab_ssd.configure(fg_color=ACCENT_COLOR, text_color=TEXT_DARK)
        elif tab == "sd":
            self.btn_tab_sd.configure(fg_color=ACCENT_COLOR, text_color=TEXT_DARK)
            
        self.filter_games()

    def update_storage_summary(self):
        """Computes summary stats and updates the SSD Space Reclaimed badge."""
        total_symlinked_size = 0
        for game in self.games_data:
            if game["is_symlink"]:
                total_symlinked_size += game["size_bytes"]
        self.stats_value.configure(text=self.format_size(total_symlinked_size))

    # --- Actions Dialogs & File Handlers ---

    def browse_steam_path(self):
        init_dir = self.steam_path_var.get()
        if not init_dir and sys.platform.startswith("linux"):
            flatpak_path = "/home/deck/.var/app/com.valvesoftware.Steam/.local/share/Steam"
            native_path = "/home/deck/.local/share/Steam"
            init_dir = native_path if os.path.exists(native_path) else flatpak_path
            
        directory = filedialog.askdirectory(title="Select Internal Steam Folder", initialdir=init_dir)
        if directory:
            self.steam_path_var.set(directory)
            self.scan_compatdata()

    def browse_sd_path(self):
        init_dir = self.sd_path_var.get()
        if not init_dir and sys.platform.startswith("linux"):
            init_dir = "/run/media"
            
        directory = filedialog.askdirectory(title="Select SD Card Destination Folder", initialdir=init_dir)
        if directory:
            self.sd_path_var.set(directory)

    def log_message(self, message):
        """Thread-safe logging utility that updates the console log textbox."""
        self.after(0, self._log_message_thread_safe, message)

    def _log_message_thread_safe(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # --- Operations Dialog Workflows ---

    def execute_move_prompt(self, game):
        """Displays confirmation, runs safety audits, and starts background file move thread."""
        sd_base = self.sd_path_var.get()
        if not sd_base:
            messagebox.showerror("Configuration Error", "Please specify a valid SD Card destination folder first!")
            return
            
        # Target path inside SD card compatdata folder
        dest_path = Path(sd_base) / game["appid"]
        src_path = Path(game["path"])
        
        # Basic Validation checks
        if not src_path.exists():
            messagebox.showerror("Error", f"Internal folder does not exist at: {src_path}")
            return
            
        if dest_path.exists():
            # If folder already exists on destination, prompt warning
            if not messagebox.askyesno("Overwrite Alert", f"Destination folder already exists at: {dest_path}\nOverwrite existing destination folder?"):
                return

        # Pre-flight Disk Space Audit
        try:
            # Determine free space on SD card
            sd_drive = Path(sd_base)
            # Create SD card directory if it doesn't exist to evaluate drive properties
            sd_drive.mkdir(parents=True, exist_ok=True)
            free_bytes = shutil.disk_usage(sd_drive).free
            needed_bytes = game["size_bytes"]
            
            # Margin buffer: 100 MB
            if free_bytes < needed_bytes + (100 * 1024 * 1024):
                needed_str = self.format_size(needed_bytes)
                free_str = self.format_size(free_bytes)
                messagebox.showerror("Insufficient Space", f"Cannot initiate move! This game requires {needed_str} of space, but your SD card only has {free_str} free!")
                return
        except Exception as e:
            self.log_message(f"Warning: Failed to run pre-flight disk check: {e}")
            if not messagebox.askyesno("Space Check Warning", "Could not verify remaining space on the SD card. Continue anyway?"):
                return

        # Action Confirmation Dialog
        confirm_msg = f"Move '{game['name']}' compatdata to the SD Card?\n\nFiles will be relocated to:\n{dest_path}\n\nA symbolic link will be established inside your internal storage to keep the game fully functional."
        if not messagebox.askyesno("Confirm Relocation", confirm_msg):
            return
            
        # UI Locking: Prevent overlapping tasks
        self.lock_ui(f"Moving '{game['name']}'...")
        
        # Start worker thread
        threading.Thread(target=self._move_worker, args=(game, src_path, dest_path), daemon=True).start()

    def _move_worker(self, game, src, dest):
        """Worker thread executing filesystem moves and symlinking."""
        self.log_message(f"--- Relocating Game Prefix: {game['name']} (ID: {game['appid']}) ---")
        
        try:
            # 1. Clean existing target destination safely if overwriting
            if dest.exists():
                self.log_message("Removing pre-existing destination folder...")
                shutil.rmtree(dest, ignore_errors=True)
                
            # 2. Re-create parent folders
            dest.parent.mkdir(parents=True, exist_ok=True)
            
            # 3. Copy files recursively (atomic backup copy)
            self.log_message(f"Copying files to SD Card: {dest}")
            self.op_queue.put(("progress", 0.3))
            
            # Custom copy routine to log directory components
            shutil.copytree(src, dest, symlinks=True)
            
            # 4. Verify size compatibility before deleting source
            self.op_queue.put(("progress", 0.7))
            self.log_message("Verifying copy integrity...")
            
            # 5. Delete source files
            self.log_message("Deleting internal source files...")
            shutil.rmtree(src)
            
            # 6. Establish symbolic link
            self.log_message("Creating symbolic link...")
            os.symlink(dest, src)
            
            self.op_queue.put(("progress", 1.0))
            self.log_message("Success! Relocation transaction successfully finalized.")
            self.op_queue.put(("done", "Relocation completed successfully!"))
        except Exception as e:
            self.log_message(f"CRITICAL ERROR during relocation transaction: {e}")
            self.log_message("Performing safety transaction rollback...")
            
            # Rollback: Clean target and attempt source restoration if half-copied
            shutil.rmtree(dest, ignore_errors=True)
            
            # Check if source got deleted. If so, reconstruct it from partial copy
            if not src.exists() and dest.exists():
                try:
                    shutil.copytree(dest, src, symlinks=True)
                except Exception as rollback_err:
                    self.log_message(f"Rollback failure: Source files could not be restored! {rollback_err}")
                    
            self.op_queue.put(("progress", 0.0))
            self.op_queue.put(("error", f"Transaction aborted: {e}"))

    def execute_restore_prompt(self, game):
        """Prompts user confirmation and launches the worker thread to restore prefix to internal SSD."""
        src_path = Path(game["path"])
        
        if not src_path.is_symlink():
            messagebox.showerror("Error", f"Internal path is not a symlink: {src_path}")
            return
            
        try:
            dest_path = Path(os.readlink(src_path))
        except Exception as e:
            messagebox.showerror("Link Resolution Failure", f"Could not resolve symlink target: {e}")
            return
            
        confirm_msg = f"Restore '{game['name']}' compatibility files back to internal SSD?\n\nThis will delete the symbolic link and move all files from your SD card back to your primary SSD storage."
        if not messagebox.askyesno("Confirm SSD Restoration", confirm_msg):
            return
            
        # UI Locking
        self.lock_ui(f"Restoring '{game['name']}'...")
        
        # Start worker thread
        threading.Thread(target=self._restore_worker, args=(game, src_path, dest_path), daemon=True).start()

    def _restore_worker(self, game, link_path, sd_path):
        """Worker thread handling safe unlinking and moving folders back to SSD."""
        self.log_message(f"--- Restoring Game Prefix: {game['name']} (ID: {game['appid']}) ---")
        
        try:
            if not sd_path.exists():
                raise FileNotFoundError(f"SD Card source directory not found at: {sd_path}")
                
            self.op_queue.put(("progress", 0.2))
            
            # 1. Unlink the symbolic link
            self.log_message("Removing symbolic link...")
            link_path.unlink() # Delete link file
            
            # 2. Copy folder contents back to internal SSD
            self.log_message("Moving files back to internal SSD...")
            self.op_queue.put(("progress", 0.5))
            shutil.copytree(sd_path, link_path, symlinks=True)
            
            # 3. Clean up the SD card folder
            self.log_message("Cleaning up SD Card files...")
            self.op_queue.put(("progress", 0.8))
            shutil.rmtree(sd_path)
            
            self.op_queue.put(("progress", 1.0))
            self.log_message("Success! Game prefix safely restored to internal SSD.")
            self.op_queue.put(("done", "SSD Restoration finalized successfully!"))
        except Exception as e:
            self.log_message(f"CRITICAL ERROR during SSD Restoration transaction: {e}")
            self.log_message("Re-establishing symbolic link to safeguard files...")
            
            # Rollback: Make sure we restore the symbolic link back to SD folder
            if not link_path.exists() and sd_path.exists():
                try:
                    os.symlink(sd_path, link_path)
                except Exception as rollback_err:
                    self.log_message(f"Rollback failed to establish symlink: {rollback_err}")
                    
            self.op_queue.put(("progress", 0.0))
            self.op_queue.put(("error", f"Restoration transaction failed: {e}"))

    def execute_delete_prompt(self, game):
        """Asks double-confirmation and removes a compatdata prefix folder completely."""
        confirm_msg = f"WARNING! Are you absolutely sure you want to delete the compatibility data folder for '{game['name']}'?\n\nThis will completely erase all configuration registries and game save files stored inside this Proton prefix! This action is non-reversible!"
        
        if not messagebox.askyesno("CRITICAL CONFIRMATION", confirm_msg):
            return
            
        double_confirm = f"Type 'DELETE' to confirm deletion of compatibility files for App ID {game['appid']}:"
        dialog = ctk.CTkInputDialog(text=double_confirm, title="Safety Verification Check")
        user_input = dialog.get_input()
        
        if not user_input or user_input.strip().upper() != "DELETE":
            messagebox.showinfo("Aborted", "Safety check failed. Operation aborted.")
            return
            
        self.lock_ui(f"Deleting prefix {game['appid']}...")
        threading.Thread(target=self._delete_worker, args=(game,), daemon=True).start()

    def _delete_worker(self, game):
        self.log_message(f"--- Erasing Game Prefix: {game['name']} (ID: {game['appid']}) ---")
        path_to_delete = Path(game["path"])
        
        try:
            if path_to_delete.is_symlink():
                # Get the link destination folder on the SD card to delete
                sd_path = Path(os.readlink(path_to_delete))
                self.log_message(f"Unlinking internal symbolic link: {path_to_delete}")
                path_to_delete.unlink()
                
                if sd_path.exists():
                    self.log_message(f"Erasing target SD Card compatibility folder: {sd_path}")
                    shutil.rmtree(sd_path)
            else:
                self.log_message(f"Erasing internal SSD compatibility folder: {path_to_delete}")
                shutil.rmtree(path_to_delete)
                
            self.log_message("Success! Folder completely erased.")
            self.op_queue.put(("done", "Game prefix erased successfully."))
        except Exception as e:
            self.log_message(f"Error during deletion transaction: {e}")
            self.op_queue.put(("error", f"Deletion aborted: {e}"))

    # --- UI Locking & Poll Background Worker Thread Manager ---

    def lock_ui(self, status_text):
        """Locks action components of the app during filesystem transactions."""
        self.status_lbl.configure(text=status_text, text_color=ACCENT_COLOR)
        self.progress_bar.set(0.1)
        
        # Disable inputs
        self.btn_refresh.configure(state="disabled")
        self.search_entry.configure(state="disabled")
        
        # Re-draw the entire row frames without button click captures
        for row in self.library_frame.winfo_children():
            for actions in row.winfo_children():
                if isinstance(actions, ctk.CTkFrame):
                    for btn in actions.winfo_children():
                        if isinstance(btn, ctk.CTkButton):
                            btn.configure(state="disabled")

    def unlock_ui(self):
        """Re-enables user inputs once operations complete successfully."""
        self.status_lbl.configure(text="Idle", text_color=TEXT_SECONDARY)
        self.progress_bar.set(0)
        
        self.btn_refresh.configure(state="normal")
        self.search_entry.configure(state="normal")
        
        # Re-scan filesystem and dynamically draw updated rows
        self.scan_compatdata()

    def poll_queue(self):
        """Check queue for updates from background worker thread (main thread listener loop)."""
        try:
            while True:
                msg_type, data = self.op_queue.get_nowait()
                if msg_type == "progress":
                    self.progress_bar.set(data)
                elif msg_type == "done":
                    messagebox.showinfo("Operation Completed", data)
                    self.unlock_ui()
                elif msg_type == "error":
                    messagebox.showerror("Operation Failed", data)
                    self.unlock_ui()
        except queue.Empty:
            pass
        self.after(100, self.poll_queue)

if __name__ == "__main__":
    app = SymlinkManagerApp()
    app.mainloop()
