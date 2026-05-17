<p align="center">
   # Steam Deck Symlink Manager
  <img src="assets\icon_large.png" alt="SDSMLogo" width="200">
</p>


Hey! So this is a neat little desktop tool made to solve one of the most annoying problems on the Steam Deck: running out of precious internal SSD space because of giant shader caches and compatibility prefix folders (`compatdata`). 

Steam leaves these folders behind even if you uninstall the game, and they can easily eat up dozens of gigabytes. This app lets you scan, inspect, and safely move those folders over to your SD card, then automatically links (symlinks) them back so Steam thinks they never left!

---

## ⚡ What it actually does:
* **Autodetects everything**: Finds your internal Steam install and mounted SD cards automatically so you don't have to keep pasting paths.
* **Resolves those annoying AppIDs**: Maps those raw numbered folder names (like `814380`) to actual readable game titles (like `Sekiro: Shadows Die Twice`) instantly. It uses a high-performance daily database mirror so it never gets rate-limited by Valve.
* **One-Click Relocation**: Safely moves folders between the SSD and SD Card and manages the symlinks for you under the hood.
* **Sleek Dark Mode GUI**: Built using a custom CustomTkinter theme styled in a gorgeous pastel teal (`#A3D9D4`) and loaded with helpful stats like exactly how much SSD space you've reclaimed.

---

## 🚀 How to compile it (Inside WSL)

Since SteamOS needs a Linux binary to run, you can build it directly on your Windows PC using your WSL terminal in about two minutes.

1. Open up your **WSL terminal** (like Ubuntu).
2. Go to this folder:
   ```bash
   cd "/mnt/c/Users/mario/OneDrive/Documents/Antigravity/Steam Deck Symlink Manager"
   ```
3. Run the compiler script:
   ```bash
   chmod +x build.sh
   ./build.sh
   ```
4. Once it finishes, your shiny new Linux binary will be waiting in the `dist` folder:
   `dist/Steam-Deck-Symlink-Manager`

---

## 🛠️ How to get it running on your Steam Deck

1. **Transfer the files**: Move the compiled `Steam-Deck-Symlink-Manager` file and the `Steam-Deck-Symlink-Manager.desktop` shortcut to your Steam Deck (using a USB drive, KDE Connect, SSH, or just downloading it from your cloud storage in the Deck's browser).
2. **Put them together**: Place both the binary and the `.desktop` file in the same folder on your Steam Deck (like your desktop or a dedicated folder).
3. **Make them executable**:
   * Right-click `Steam-Deck-Symlink-Manager` $\rightarrow$ **Properties** $\rightarrow$ **Permissions** tab $\rightarrow$ check **Is Executable**.
   * Do the same for the `Steam-Deck-Symlink-Manager.desktop` file.
4. **Double click and go!**: Run the desktop icon! If SteamOS asks you to confirm, just click **Execute** / **Trust**.

---

## 🎨 Branding & Customization
We added custom high-fidelity branding logos (`icon_small.png` and `icon_large.png`) directly into the compiler. PyInstaller will automatically bake them right into your executable, so the app will open up with the custom logo on the header bar and the desktop taskbar automatically!
