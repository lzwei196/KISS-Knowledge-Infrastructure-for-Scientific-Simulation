# 1 Install and first launch

In this chapter you will download GeoForge Desktop 0.6.55 for Windows (macOS notes describe 0.6.54), check the file, install it on Windows or macOS, start it for the first time, and find your way around the main screen. You will also learn where GeoForge keeps your files, and how to upgrade or uninstall it.

## What you need

| | Windows | macOS |
|---|---|---|
| Computer | 64-bit (x64) Windows PC. This build was tested on Windows 11. | Mac with Apple Silicon (M-series). Intel Macs are not supported by this release. |
| Release to use | `windows-v0.6.55` | `v0.6.54` |
| Download size | See the current release Assets for exact bytes | See the macOS release Assets |
| Disk space for the program | About 400 MB | A few hundred MB |
| Administrator rights | Not needed | Not needed; macOS may ask for your password when you allow the app to open |
| Included | The app, its own Python, and all 127 KIs | The app and all 127 KIs |

A KI (Knowledge Infrastructure) is GeoForge's packaged knowledge about one scientific model: how to install, prepare, run and check it. Having the KI does not mean the model software is on your computer.

Installing GeoForge does **not** install any scientific model, and it does not give you an AI. You connect an AI in Chapter 2 and install model software in Chapter 4. Each model you install later needs its own disk space, often several GB.

## Choose the right download

GeoForge is published on GitHub. Windows and macOS use **different release pages**, and this Windows manual documents 0.6.55; the macOS notes retain their earlier version.

1. Open the release page for your system:

    - **Windows:** <https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.55> (title "GeoForge Desktop 0.6.55 for Windows").
    - **macOS:** <https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/v0.6.54> (title "GeoForge Desktop v0.6.54 — macOS Apple Silicon").

2. Scroll down to **Assets**. If the list is collapsed, click **Assets** to open it.
3. Click the program file for your system (see the tables below). Your browser downloads it.
4. Click the checksum file to download it too: `SHA256SUMS-Windows.txt` on Windows, `SHA256SUMS.txt` on macOS.

Check that the page title reads "GeoForge Desktop 0.6.55 for Windows" and that the file names contain `v0.6.55-Windows-x64`.

**Windows files (`windows-v0.6.55`)**

| File | What it is | Do you need it? |
|---|---|---|
| `GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe` | Installer | Yes, recommended for most people |
| `GeoForge-Desktop-v0.6.55-Windows-x64.zip` | Portable copy, no installation | Only if you cannot or do not want to install software |
| `SHA256SUMS-Windows.txt` | Checksums for the two files above | Yes, to check your download |
| `Windows-release-validation.json`, `release-manifest.json`, `DESKTOP_CHANGELOG.md` | Test record and release notes | No |

**macOS files (`v0.6.54`)**

| File | What it is | Do you need it? |
|---|---|---|
| `GeoForge-Desktop-macos-arm64.app.zip` | The app | Yes |
| `SHA256SUMS.txt` | Checksums | Yes, to check your download |
| `kiss-macos-arm64.tar.gz` | Optional command-line tool | No |
| `kiss-ki-packages.tar.gz` | The KIs on their own | No, the app already contains them |
| `release-manifest.json`, `DESKTOP_CHANGELOG.md` | Release notes | No |

> **Caution:** On Windows, use only the files from `windows-v0.6.55`. The macOS page `v0.6.54` has no Windows files. Some older release pages also list Windows files (for example `v0.6.52`, whose title says macOS); those are older Windows builds, not 0.6.55.

The macOS app on `v0.6.54` was built on 19 September 2026. Windows 0.6.55 contains later planning, native-model and calibration fixes. This manual follows the Windows build, so a few planning screens in later chapters can look different on a Mac.

## Check the download (SHA-256)

GeoForge is not signed by a publisher that Windows or Apple recognises, so your computer cannot vouch for the file. A checksum (SHA-256) is a 64-character fingerprint of a file: if even one byte changes, the fingerprint changes. Comparing it with the published value confirms that the file arrived complete and unchanged. Do this before you run anything.

### On Windows

1. Open File Explorer and go to the folder with the downloaded file (usually **Downloads**).
2. In the File Explorer address bar, type `powershell` and press Enter. PowerShell opens in that folder.
3. Type the command for your file and press Enter:

    ```powershell
    Get-FileHash .\GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe -Algorithm SHA256
    ```

    For the portable copy, use `.\GeoForge-Desktop-v0.6.55-Windows-x64.zip` instead.

4. Open `SHA256SUMS-Windows.txt` in Notepad.
5. Compare the **Hash** that PowerShell printed with the line for the same file name. Capital and small letters do not matter; every character must match.

Check that the two 64-character values are identical.

### On macOS

1. Open **Terminal** (Applications → Utilities → Terminal).
2. Type this command and press Return:

    ```bash
    shasum -a 256 ~/Downloads/GeoForge-Desktop-macos-arm64.app.zip
    ```

3. Open `SHA256SUMS.txt` and compare the printed value with the line for `GeoForge-Desktop-macos-arm64.app.zip`. Every character must match.

### Get the checksum for this release

Use `SHA256SUMS-Windows.txt` from the **same `windows-v0.6.55` release** as the installer or portable archive. Release artifacts have different hashes; do not compare a current download with an older edition's checksum. The Windows checksum file is available at:

<https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/download/windows-v0.6.55/SHA256SUMS-Windows.txt>

For the separate macOS 0.6.54 release, use that release's `SHA256SUMS.txt`.

If the values differ, delete the file and download it again. Do not run a file whose checksum does not match.

## Install on Windows with the installer

The installer puts GeoForge in your own user folder, so it needs no administrator rights. The installer wizard is in English only.

1. Double-click `GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe`. Windows usually shows a blue box, **Windows protected your PC**. This is Microsoft Defender SmartScreen, Windows' check for downloaded programs. It appears because the installer carries no publisher signature; continue only if the checksum matched.
2. Click **More info**.
3. Check that the app is `GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe` and the publisher is **Unknown publisher**.
4. Click **Run anyway**.

5. On **Select Destination Location**, click **Next** to keep the suggested folder. The default is `C:\Users\you\AppData\Local\Programs\GeoForge Desktop` (written `%LOCALAPPDATA%\Programs\GeoForge Desktop`). To use another folder you can write to, type it in the box before you click **Next**.

    Check that the path is inside your own user folder (`C:\Users\you\…`).

6. On **Select Additional Tasks**, tick **Create a desktop shortcut** if you want a desktop icon. It is not ticked by default.
7. Click **Next**.

8. On **Ready to Install**, click **Install**.
9. On **Completing the GeoForge Desktop Setup Wizard**, click **Finish**. Leave **Launch GeoForge Desktop** ticked so that GeoForge starts, then continue with [First launch on Windows](#first-launch-on-windows).

To start GeoForge later, open the Start menu, type `GeoForge`, and click **GeoForge Desktop**. You can also find it under **All apps**, in the **GeoForge Desktop** folder. If you ticked the option in step 6, you can use the desktop shortcut.

## Use the portable zip on Windows

The portable copy runs without installation. Use it when you cannot install software, or want to try GeoForge without changing anything on the PC.

1. In File Explorer, right-click `GeoForge-Desktop-v0.6.55-Windows-x64.zip` and choose **Extract All…**.
2. In the destination box, type a short folder, for example `D:\GeoForge-Manual\App`.
3. Click **Extract**.
4. Open the extracted folder `GeoForge Desktop 0.6.55 Windows` (inside `D:\GeoForge-Manual\App`). It contains `GeoForge Desktop.exe`, `geoforge-agent-bridge.exe` and the folder `_internal`.
5. Double-click `GeoForge Desktop.exe`. If SmartScreen warns you, click **More info**, then **Run anyway**, as for the installer.

Check that `GeoForge Desktop.exe` and `_internal` are in the same folder.

> **Caution:** Extract the whole zip first. Do not start the app from inside the zip window, and never move `GeoForge Desktop.exe` away from `_internal`; the program needs every file in that folder. For a desktop icon, right-click `GeoForge Desktop.exe` → **Send to** → **Desktop (create shortcut)** (Windows 11: **Show more options** first).

The portable copy uses the same settings and project folders as an installed copy (see [Where GeoForge keeps things](#where-geoforge-keeps-things)). Do not run both at the same time.

## Install on macOS

1. In **Downloads**, double-click `GeoForge-Desktop-macos-arm64.app.zip`. Finder unpacks `GeoForge Desktop.app`.
2. Drag `GeoForge Desktop.app` into **Applications**.

The app is not notarised by Apple (Apple has not checked and approved it), so macOS blocks its first launch. Allow it once, in one of the two ways below.

### Allow the app to open with Terminal

This is the method in the release notes.

1. Open **Terminal** (Applications → Utilities → Terminal).
2. Run this command:

    ```bash
    xattr -dr com.apple.quarantine "/Applications/GeoForge Desktop.app"
    ```

3. Open **GeoForge Desktop** from **Applications**. Continue with [First launch on macOS](#first-launch-on-macos).

### Allow the app to open without Terminal

1. Double-click **GeoForge Desktop** in **Applications**. macOS says it could not verify the app.
2. Click **Done** (on older macOS, **OK**). Do not click **Move to Trash**.

3. Open **System Settings** → **Privacy & Security**.
4. Scroll down to the Security message saying that "GeoForge Desktop" was blocked.

5. Click **Open Anyway**.
6. Confirm with **Open Anyway** and your password when macOS asks. GeoForge opens. Continue with [First launch on macOS](#first-launch-on-macos).

You must allow the app again after every update, because each new build is a new download. macOS may also ask again for access to **Documents**, **Desktop** or **Downloads**. Keeping projects outside those folders and outside iCloud reduces these prompts.

## First launch on Windows

On Windows, GeoForge has no window of its own. When it starts, it runs a small local server (a program that serves pages only to your own computer) and shows its pages in your **default web browser**. A GeoForge icon also appears in the notification area (system tray) at the bottom right of the screen.

1. Start GeoForge (installer finish page, Start menu, desktop shortcut, or `GeoForge Desktop.exe` in the portable folder).
2. Wait a few seconds. A browser tab titled **GeoForge Desktop** opens at an address like `http://127.0.0.1:52814/`. This tab **is** the app.
3. Find the tray icon. If you do not see it, click the **^** arrow next to the clock. Hovering over the icon shows "GeoForge Desktop — double-click to open".
4. Optional: drag the icon from the **^** area onto the taskbar so it stays visible.

Check that the menu shows exactly two items, **Open GeoForge** and **Exit GeoForge**.

Check that the address starts with `http://127.0.0.1:` and that the sidebar reads **AI setup needed**. Both banners are normal at this point (see [What the first screen tells you](#what-the-first-screen-tells-you)).

### Open, close and quit

| You do this | What happens |
|---|---|
| Close the browser tab or the browser | GeoForge keeps running in the tray. Work in progress (an agent, a download, a model run) continues. |
| Double-click the tray icon, or right-click it → **Open GeoForge** | The GeoForge page opens again in your browser. |
| Right-click the tray icon → **Exit GeoForge** | GeoForge first stops everything it started (agents, downloads, calibration, and the models or compilers they launched), then quits. A model run in progress is interrupted. |
| Start GeoForge again from the Start menu while it is running | A **second copy** starts, with a second tray icon and a different address. Avoid this: both copies share the same settings and projects. Use the tray icon to reopen the page instead. |

Always quit with **Exit GeoForge**, not with Task Manager, so that running work is stopped cleanly. The tray menu is in English only.

> **Caution:** Known issue in 0.6.54: a long job that an AI agent started in the background through Git Bash (the command window some agents, such as Claude Code, use on Windows) can keep running after **Exit GeoForge**. If your computer stays busy after you quit during a long run, open Task Manager (Ctrl+Shift+Esc) and end the leftover model or compiler program.

### What changes at every launch

- **The address changes.** The number after `127.0.0.1:` is new each time. Do not bookmark it; use the tray icon. Old tabs from an earlier launch stop working, so close them.
- **Some preferences reset.** Your browser treats each new address as a new site. The interface language goes back to your browser's language, the theme (**◐**) to your system's light or dark setting, and the **Local** | **API** switch to **Local**. If you use only an API key (for example DeepSeek), click **API** under **AI CONNECTION** before you send the first message in a new chat. See Chapter 8, Language, appearance and keyboard.

Your chats, projects, API keys and **Settings** are stored by GeoForge itself, so they are kept.

## First launch on macOS

- GeoForge opens in its own window, titled **GeoForge Desktop**, with an icon in the Dock. The main screen is laid out the same way as on Windows.
- **Closing the window quits GeoForge**, as **Quit** (Command-Q) does. Any running agent, software setup or model run stops. During long installs and runs, keep the window open or minimise it.
- At each launch the Mac app checks the official KI library and may show a small notice at the bottom right (for example **KI library checked**). Click **Dismiss** to close it. Chapter 7 explains KI updates.
- As on Windows, the language, theme and **Local** | **API** choices can reset at each start (Chapter 8).

## What the first screen tells you

Until you connect an AI, the start screen shows two signs. Both are normal on a new installation:

- Next to **GeoForge** at the top of the sidebar: **AI setup needed**.
- Above the start screen, the banner **Connect an AI to begin.** "Open AI Settings to add a key or configure a local agent." The banner says "AI Settings"; the button you need is **Settings** at the bottom of the sidebar.

You may also see a second message above the start screen. It depends on the **Local** | **API** switch under **AI CONNECTION**. **Local** means a local agent: an AI command-line program, such as Claude Code or Codex, installed and signed in on this computer. **API** means a key from an AI provider, such as DeepSeek.

| Message | Meaning |
|---|---|
| "No local agent CLI is installed. Open AI Settings for setup details." with **Recheck** | **Local** is selected and no local agent program is installed. |
| "Local CLIs are installed but not ready — …" with **Recheck** | **Local** is selected. An agent program is installed but not signed in, or needs an update. The message names it. |
| "No API connection yet. Open AI Settings and add a key." | **API** is selected and no API key is saved. |

These messages go away when the selected side has an AI that is ready. If you use only an API key, add it (Chapter 2), then click **API**.

Once an AI is connected, the sidebar shows, for example, **1 AI ready**, and the **Connect an AI to begin.** banner disappears. Chapter 2, Connect an AI, shows how.

## A tour of the main screen

This is the screen you will use most. Here it is with four AIs already connected and no chat open.

![GeoForge main screen with no chat open: sidebar on the left, header with Auto KI and AI CONNECTION, five starter cards in the centre, message box at the bottom](../../images/en/01-home.png)

Check that the sidebar shows **N AI ready** (here **4 AI ready**), and that **AI CONNECTION** shows the provider and model you expect (here **API**, **DeepSeek (API)** and **deepseek-chat**).

### Sidebar (left)

| Control | What it does |
|---|---|
| **GeoForge** and **N AI ready** / **AI setup needed** | How many AI connections are ready to use. |
| **＋ New chat** | Starts a new project chat. A dialog, **New project chat**, asks for the project name and folder (Chapter 6). |
| Chat list | Your chats, below **＋ New chat** (empty at first). Each chat is one project with its own folder. Hovering over a chat shows **✕**. It archives the chat after you confirm: the project folder is moved into an `_archived` folder beside it, and nothing is deleted. |
| **KI Observatory**, **KI Library**, **KI Studio** | Open other GeoForge pages (Chapter 7). To return, use the arrow at the top left of the page or the browser's Back button. In **KI Studio** the arrow leads to **KI Library**. |
| **Guide** | Opens **How GeoForge works**, a three-step summary with an **Open KI Library** button. This manual covers much more. |
| **Settings** | Opens the Settings window: **AI services**, **GeoForge Database**, **Network & proxy**, **Permissions** (Chapters 2 and 3). |
| **简体中文** | Switches the interface to Chinese and reloads the page. In Chinese mode the same button reads **English**. |
| **◐** | Switches between light and dark. |

### Header (top)

| Control | What it does |
|---|---|
| Title | The chat's name; **GeoForge Desktop** when no chat is open. |
| **Auto KI** (with the **KI** badge) | Chooses the KI (the model) for this chat. **Auto KI** lets GeoForge choose for each task (Chapter 4). It is fixed after the chat's first message. |
| Status pill | **Chooses for each task** with Auto KI. With a chosen KI, it shows whether that model's software is verified on this computer. |
| **▣ Folder** | Opens this chat's project folder in File Explorer (Finder on macOS). |
| **◇ Project status** | Shows what GeoForge is doing in this project and what it needs from you (Chapter 6). |
| **▤ Project view** | Opens this chat's result panels (Chapter 6). |
| **AI CONNECTION**: **Local** \| **API**, provider list, model list | Chooses the AI for a new chat: a local agent program or an API key, then the provider and model. They are fixed after the chat's first message (Chapter 2). |

**▣ Folder**, **◇ Project status** and **▤ Project view** stay grey until a chat is open.

### Centre

With no chat open, the centre shows **What would you like to model?** and five starter cards:

| Card | Opens |
|---|---|
| **Start chatting** | Puts the cursor in the message box. |
| **Choose a KI** | The KI picker, to pin a model to the chat. |
| **Browse & verify** | **KI Library**. |
| **Observe KIs** | **KI Observatory**. |
| **Create a KI** | **KI Studio**. |

When a chat is open, the centre shows the conversation instead.

### Message area (bottom)

| Control | What it does |
|---|---|
| **＋ Files** | Attaches files to your next message. |
| **✦ Skills** | Chooses extra skills for this chat. |
| Message box ("Ask a scientific question or describe a modelling task…") | Where you type. Enter sends; Shift+Enter starts a new line. |
| **Send** | Sends the message. It stays grey until the selected AI is ready. |

> **Tip:** If you send a message that contains Chinese characters, the interface switches to Chinese automatically. Click **English** in the sidebar to switch back.

## Where GeoForge keeps things

By default, GeoForge keeps your projects outside the program folder. Updating or uninstalling the program therefore does not touch your work.

| What | Windows | macOS |
|---|---|---|
| Program | `%LOCALAPPDATA%\Programs\GeoForge Desktop` (or the folder where you extracted the portable zip) | `/Applications/GeoForge Desktop.app` |
| Settings: API keys, proxy, default AI | `%APPDATA%\KISS\settings.json` | `~/Library/Application Support/KISS/settings.json` |
| Other app data: KI updates (`ki-updates`), KIs you import (`user_models`), Database catalogue copy (`database`), KI Studio work (`ki-studio`) | `%APPDATA%\KISS\` | `~/Library/Application Support/KISS/` |
| GeoForge Database activation token | Windows Credential Manager → **Windows Credentials** → Generic Credentials → `com.geoforge.desktop:observation-activation-token` | A private file under `~/Library/Application Support/KISS/secrets/` |
| Work folder: projects and model installs | `C:\Users\you\kiss` | `~/kiss` |

`%APPDATA%` is `C:\Users\you\AppData\Roaming`, and `%LOCALAPPDATA%` is `C:\Users\you\AppData\Local`. You can type either into the File Explorer address bar.

Inside the work folder (`C:\Users\you\kiss` or `~/kiss`):

| Item | What it holds |
|---|---|
| `projects\` | One folder per chat, named `<date>-<project name>--<id>`, for example `2026-10-01-Alptal-snow-example--<id>`. Archived chats are in `projects\_archived\`. |
| One folder per installed model, in lower case | The default install place for each model, for example `C:\Users\you\kiss\fsm2`. |
| `_install-locations.json` | A record of any model you installed in another folder. |
| `sessions\` and other small folders | GeoForge's own bookkeeping, including where to find projects you created elsewhere. Leave them alone. |

You can create a project somewhere else (in the **New project chat** dialog) and install a model in another folder (on the **Agent setup** page). GeoForge records those places and finds them again later. On Windows, choose short paths without spaces, for example `D:\GeoForge-Manual\models\fsm2`, on a drive with several GB free. Avoid OneDrive and iCloud folders.

> **Caution:** `settings.json` holds your API keys as plain, unencrypted text. It sits in your own user folder, but other programs running under your account, and administrators of the computer, can read it. Do not share, sync or attach this file, or the folder that contains it.

> **Tip:** For advanced users only: the app has no setting to move the whole work folder. You can make a shortcut whose target is `"C:\Users\you\AppData\Local\Programs\GeoForge Desktop\GeoForge Desktop.exe" app --workroot D:\GeoForge-Manual\work`. While you use that shortcut, chats from the default work folder do not appear in the sidebar; their files stay on disk.

## Upgrade GeoForge

Your projects, chats, model installs, API keys, proxy settings, default AI and Database token are kept when you upgrade. Nothing needs to be moved.

> **Tip:** If you used an older Windows build on Chinese-language Windows and saw missing planning cards, run records that failed to save, or AI agents that would not start under a Chinese user name, upgrade to 0.6.54. These problems are fixed in this build.

### Windows, installed copy

1. Wait for running work to finish, or accept that it will be stopped.
2. Right-click the tray icon → **Exit GeoForge**.
3. Download the new installer and check its SHA-256 (see [Check the download](#check-the-download-sha-256)).
4. Run the new installer. It installs into the same folder, so it may skip the folder page.
5. Click **Finish** with **Launch GeoForge Desktop** ticked.

If the installer shows **Preparing to Install** and lists GeoForge among the applications using files, GeoForge is still running. Exit it from the tray, then click **Next**.

### Windows, portable copy

1. Right-click the tray icon → **Exit GeoForge**.
2. Extract the new zip into a **new** folder.
3. Start the new `GeoForge Desktop.exe`.
4. When the new copy works, delete the old folder. Your data is not in it.

### macOS

1. Close the GeoForge window to quit.
2. Unzip the new download.
3. Drag the new `GeoForge Desktop.app` into **Applications**.
4. When Finder asks, click **Replace**.
5. Allow the new app to open again, as in [Install on macOS](#install-on-macos).

## Uninstall GeoForge

### Windows, installed copy

1. Right-click the tray icon → **Exit GeoForge**.
2. Open Windows **Settings** → **Apps** → **Installed apps** (Windows 10: **Apps & features**).
3. Find **GeoForge Desktop 0.6.54** in the list.
4. Click **…** next to it (Windows 10: click the entry).
5. Choose **Uninstall**.
6. Confirm the uninstall in the dialogs that follow.

### Windows, portable copy

1. Right-click the tray icon → **Exit GeoForge**.
2. Delete the extracted folder.

### macOS

1. Close the GeoForge window to quit.
2. Drag `GeoForge Desktop.app` from **Applications** to the Trash.

### What uninstalling keeps

Uninstalling removes only the program. Everything below stays on your computer until you delete it yourself.

| Kept | Windows | macOS | Delete it if… |
|---|---|---|---|
| Settings and API keys | `%APPDATA%\KISS` | `~/Library/Application Support/KISS` | you want to remove your keys and settings |
| All projects and installed models | `C:\Users\you\kiss` | `~/kiss` | you no longer need any result or model install |
| Projects and models in folders you chose | Where you put them | Where you put them | as above |
| Database token | Credential Manager entry `com.geoforge.desktop:observation-activation-token` | Inside `~/Library/Application Support/KISS` | you want to remove the token |

> **Caution:** Deleting the work folder (`C:\Users\you\kiss` or `~/kiss`) permanently removes every project, result and installed model in it. Copy the results you need first. This cannot be undone.

On macOS, open the `Library` folder with Finder → **Go** → **Go to Folder…** (Shift-Command-G) and type `~/Library/Application Support/KISS`.

## If something goes wrong

| What you see | What to do |
|---|---|
| The browser says the download "isn't commonly downloaded" or holds it back | This is the browser's check for unsigned files. Choose to keep the file (in Edge: **…** → **Keep**, then **Show more** → **Keep anyway**). Then check the SHA-256. |
| The SHA-256 does not match | Delete the file and download it again from the release page. Do not run it. |
| SmartScreen shows no **Run anyway** button | Click **More info** first. If the button is still missing, your organisation blocks unknown apps; ask your IT support. |
| Windows says **Smart App Control** blocked the app | Windows offers no override for this. Turning Smart App Control off is a security decision for you or your IT support. |
| Nothing seems to happen after you start GeoForge (Windows) | Wait 10–20 seconds. Look for the tray icon (click **^**) and double-click it. Do not start GeoForge again until you have checked the tray, or you get a second copy. |
| The page says the site cannot be reached | The tab belongs to an earlier launch, or GeoForge has quit. Close the tab. Start GeoForge, or double-click its tray icon, and use the new tab. |
| **GeoForge could not start.** with a **Reload** button | Click **Reload**. If it appears again, quit with tray → **Exit GeoForge** and start GeoForge once more. |
| Two GeoForge icons in the tray | GeoForge was started twice. Right-click each icon → **Exit GeoForge**, then start it once. |
| The language, theme or **Local** \| **API** choice changed back | Expected after a restart, because the local address changes. Set it again. See Chapter 8. |
| **Connect an AI to begin.** | Normal until an AI is connected. See Chapter 2. |
| "No local agent CLI is installed." although you use an API key | Click **API** under **AI CONNECTION**. |
| On a Mac, the `.zip` is gone from **Downloads** and only `GeoForge Desktop.app` is there | Safari unpacked it for you, so the zip cannot be checked. Download it again with another browser, or turn off **Open "safe" files after downloading** in Safari's settings first. |
| macOS says the app cannot be opened, or that it is damaged | Run the `xattr` command from [Allow the app to open with Terminal](#allow-the-app-to-open-with-terminal), then open the app again. |
| On macOS, a running setup or model run stopped | Closing the GeoForge window quits the app and stops its work. Open GeoForge again and continue in the same chat. |
| After uninstalling, the program folder is still there | Delete `%LOCALAPPDATA%\Programs\GeoForge Desktop` by hand. Your projects are not in it. |

For other problems, see Chapter 9, Troubleshooting and known issues.
