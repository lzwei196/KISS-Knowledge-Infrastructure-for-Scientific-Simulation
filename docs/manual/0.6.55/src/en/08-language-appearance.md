# 8 Language, appearance and keyboard

In this chapter you will switch GeoForge between English and Simplified Chinese, choose a light or dark look, and learn the few keys GeoForge responds to.

## Switch the interface language

GeoForge has two interface languages: English and Simplified Chinese. The language button is at the bottom of the sidebar, to the right of **Settings**. It always shows the language you will switch *to*: **简体中文** while the interface is in English, **English** while it is in Chinese.

1. Send or copy anything you have typed in the message box but not sent. The next step reloads the page, and the reload clears unsent text and the list of files attached to that message. Files you already added stay in the project folder.
2. At the bottom of the sidebar, click **简体中文**.

    ![Main window in English, with the 简体中文 button at the bottom of the sidebar](../../images/en/11-chat-empty.png)

    Check that **简体中文** sits to the right of **Settings**, with the **◐** button on the row below **Settings**.

3. Wait for the page to reload. Buttons, panel titles and hints are now in Chinese.

    ![The same window after switching to Chinese](../../images/zh-CN/11-chat-empty.png)

    Check that the sidebar button now reads **English** and that **Send** has become **发送**. The chat name, the provider *DeepSeek (API)* and the model *deepseek-chat* do not change.

4. To return to English, click **English** in the same place. The page reloads in English.

After either reload, GeoForge opens the chat at the top of the chat list. If you were working in another chat, click it in the list.

The language button is on every GeoForge page: the main window, **KI Library**, **KI Studio**, **KI Observatory** and **Agent setup**. One choice applies to all of them. A page that is already open in another tab picks up the change when you reload it.

### The language at first start

When GeoForge has no saved choice, it uses the language that the browser reports. On Windows this is your default browser's language setting. Any Chinese setting, including Traditional Chinese, opens the Simplified Chinese interface. Every other language opens English.

On macOS the GeoForge window can open in English even on a Chinese system. If it does, click **简体中文**.

### Writing in Chinese switches the interface

When you send a message that contains any Chinese character, the interface switches to Chinese at once, without a reload. This happens even for a single Chinese place name in an English sentence, such as "Run FSM2 for 淮河".

The AI gets a matching instruction. GeoForge asks it to reply in the language of your latest message. When that message contains any Chinese character, GeoForge asks for a reply entirely in Simplified Chinese, including plot titles, captions and axis labels. It also asks the AI to keep commands, code, file paths, KI names and exact scientific identifiers unchanged.

To go back to English:

1. Click **English** at the bottom of the sidebar. The page reloads in English.
2. Write your next message without any Chinese characters. GeoForge then asks the AI to reply in English.

> **Tip:** To stay in English, write place names in English or pinyin (for example *Huai River*, *Bengbu*). The GeoForge Database search boxes match words in the catalogue's English text, so English names and dataset IDs also find data that Chinese names miss. See Chapter 3, GeoForge Database.

## What stays in English in Chinese mode

The Chinese interface translates most of GeoForge's own buttons, menus, panel titles, dialogs and hints. GeoForge never translates these:

- model names, KI names, file and folder paths, commands and units;
- chat and project names, which stay as you typed them;
- the AI's messages, which follow the language of your latest message;
- raw technical output, such as logs and reports in grey boxes.

Some screens show English text even in Chinese mode. Expect these:

| Where | English text you will see |
|---|---|
| Plan approval card | The title **Approve the plan?** and the options **Approve and start** and **Modify the plan** |
| Data cards in the chat | **Download N datasets from Baidu Pan**, **Some approved data could not be fetched**, **Retry the missing data** |
| **Project status** summary and data labels | "Completed — every step has a verified receipt", "Stopped by you — send a message to continue", "Data needs attention" |
| Chat messages from GeoForge | "Software verified. Starting your approved plan in a new session…" |
| Banners above the chat | "Connect an AI to begin." and "… is not verified on this machine" |
| Chat list | The line under each chat name, for example "Auto KI · 0 messages" |
| Right-click menu in a text box | **Cut**, **Paste** and **Select All** (**Copy** is translated) |
| **Settings → AI services** | The report shown by **Test AI & GitHub** (the button itself is translated) |
| **Settings → GeoForge Database** | Error messages about the token, quota or network |
| Windows installer | Every page of the setup wizard |
| Windows system tray menu | **Open GeoForge** and **Exit GeoForge** |

The approval card and data cards work the same way in both languages. Chapter 5, Your first project, explains each option.

## Choose light or dark

1. At the bottom of the sidebar, click **◐**. The window switches between light and dark at once, with no reload.
2. To switch back, click **◐** again.

Check that the sidebar, chat area and message box all turn dark. The theme changes only screen colours; plots and files in your project folder are not affected.

Until you click **◐**, each page follows the light or dark setting of your computer, or of your browser if you set one there. Your choice applies to the main window, **KI Library**, **KI Observatory** and **Agent setup**.

**KI Studio** has its own **◐** button and its own setting. It starts in light mode, whatever the other pages use, until you click its **◐**.

## Keyboard

Besides the usual browser keys (Tab moves between controls; Enter or Space presses the focused button), GeoForge responds only to the keys below. There is no shortcut for a new chat, for switching chats or for stopping a run. The Command-K shortcut from older manuals does not exist.

| Key | Where | What it does |
|---|---|---|
| Enter | Message box | Sends the message, like **Send** |
| Shift+Enter | Message box | Starts a new line without sending |
| Enter | **Project name** in the **New project chat** dialog | Creates the chat, like **Create chat** |
| Enter | **GeoForge Database** search box in **Project status → Details** | Runs the search, like **Search** |
| Enter or Space | A domain or KI that you reached with Tab in **KI Observatory** | Opens it, like a click |
| Esc | A dialog in the main window (**Settings**, **New project chat**, **Knowledge Infrastructures for this chat**, **Skills for this chat**, **MCP connections**, **How GeoForge works**, a question card) or in **KI Library** | Closes it. Esc does not close the **Project status** or **Project view** panels. |
| Ctrl+C, Ctrl+X, Ctrl+V, Ctrl+A (macOS: Command) | Text boxes and selected text | Copy, cut, paste, select all |

To copy a whole chat message, click **Copy** on the line with the sender's name. Right-clicking in a text box opens a small menu with **Cut**, **Copy**, **Paste** and **Select All**. Right-clicking on selected text elsewhere shows only **Copy** and **Select All**.

> **Caution:** Pressing Esc, clicking ✕ or **Not now**, or clicking outside a question card closes it without answering. The plan approval card is a question card too. The card does not come back by itself on that page. To answer it, open **Project status** and click **Respond**, or reload the page and open that chat again.

> **Tip:** With a Chinese input method, the **Project name** field ignores the Enter that confirms a candidate, so the chat is not created half-named. The message box does not check for this, so with some input methods that Enter can send the message. Confirm candidates with Space or a number key there, and press Enter only to send.

## Preferences after a restart

GeoForge keeps three preferences in the browser's storage for the page's address: the interface language, the theme, and the **Local** | **API** switch under **AI CONNECTION**. Each time GeoForge starts, it uses a new local address, such as `http://127.0.0.1:52814/`. The browser treats the new address as a new site, so these preferences go back to their defaults.

| Preference | Default after a restart |
|---|---|
| Language | The language your browser reports |
| Theme | Your computer's or browser's light or dark setting (**KI Studio**: light) |
| **Local** \| **API** | The kind of AI used by the chat that opens; **Local** when that chat has no AI yet |

| Platform | What to expect |
|---|---|
| Windows | GeoForge opens in your default browser at a new address on every launch, so expect all three preferences to reset each time. Within one launch they are kept, including when you reload the page or reopen it with tray → **Open GeoForge**. |
| macOS | GeoForge opens in its own window, which also uses a new local address at each start. Expect the same reset. |

Your chats, projects, API keys and other **Settings** are stored by GeoForge itself, not by the browser. They are kept across restarts.

> **Tip:** If you use only an API key (for example DeepSeek), a new start may show "No local agent CLI is installed. Open AI Settings for setup details." ("AI Settings" is the old name of **Settings → AI services**.) Click **API** under **AI CONNECTION**, or open a chat that already uses your API provider. See Chapter 2, Connect an AI.

Because the address changes, a bookmark to GeoForge stops working after a restart. On Windows, while GeoForge is running, reopen the page with tray → **Open GeoForge**. After you have quit it, start it again from the Start menu. See Chapter 1, Install and first launch.

## If something goes wrong

| What you see | What to do |
|---|---|
| The interface switched to Chinese on its own. | You sent a message with a Chinese character, or your browser language is Chinese. Click **English** at the bottom of the sidebar. |
| The AI keeps replying in Chinese. | Your latest message contained Chinese characters. Write the next message without any, and GeoForge asks the AI for English. |
| A message you were typing disappeared after you switched language. | The language button reloads the page, which clears unsent text and the attachment list. Type it again. Files you had added are still in the project folder. Next time, send or copy the text before you switch. |
| After switching language, a different chat is shown. | The reload opens the chat at the top of the chat list. Click your chat in the list. |
| Language, theme or **Local** \| **API** went back to the default after a restart. | This is expected, because the address changes at each start. Set them again. |
| A question or approval card vanished after you pressed Esc. | Esc closes the card without answering. Open **Project status** and click **Respond**. |
| A Chinese-mode screen shows English text, such as **Approve the plan?** | This is expected. See the table in "What stays in English in Chinese mode". |
| **KI Studio** stays light while the other pages are dark. | **KI Studio** has its own setting. Click **◐** in **KI Studio**. |
| Enter sent a message before you finished. | Use Shift+Enter for new lines. With a Chinese input method, confirm candidates with Space or a number key. |
