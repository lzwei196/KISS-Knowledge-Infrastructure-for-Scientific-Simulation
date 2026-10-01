# 3 GeoForge Database

In this chapter you will connect GeoForge Desktop to the GeoForge Database, check that the connection works, browse what the database holds, and follow approved data from the plan into your project folder.

## 3.1 What the GeoForge Database is

The GeoForge Database is a curated online catalogue of about 1,100 datasets for environmental modelling. It holds gauge and station observations, meteorological forcing and reanalysis, gridded products, soil maps, terrain data and similar inputs.

When the database is connected, the agent can search it while it plans your study. It writes the exact dataset IDs into the plan. The agent never downloads anything itself: after you approve the plan, GeoForge fetches the approved data (or gives you a download link for very large files), checks it, and records it in your project.

The database is optional. It is separate from any GeoForge web account and needs its own activation token.

| You need the database when… | You can work without it when… |
|---|---|
| you want GeoForge to find and fetch observation, forcing or soil data for your study area | your plan uses a public source the KI already knows (for example NASA POWER) |
| you want a large gridded product cut to your study area on the server instead of downloading the whole file | you provide your own files |
| you want every downloaded file checked and recorded in the project | you run a KI's bundled example case (the FSM2 Alptal example needs no database) |

## 3.2 Get an activation token

Each person gets their own token from the GeoForge Database owner. You cannot sign up for one inside the app.

- The token is a long text that starts with `gfd_`.
- It is valid for 6 months. After that, ask for a new one.
- The owner can revoke one person's token without affecting anyone else.
- Each token has a daily limit of 20 GB or 2,000 requests. The limit resets at midnight server time.

> **[To be completed by the GeoForge team]** how to request a token (contact, form, expected time)

> **Caution:** Treat the token like a password. Do not paste it into a chat message, an e-mail to a colleague, or a file in your project. Every Baidu Pan link GeoForge shows you is logged against your token, so a shared token means shared responsibility.

## 3.3 Enter the token in Settings

1. Click **Settings** at the bottom of the left sidebar.
2. In the Settings menu on the left, click **GeoForge Database**.

![GeoForge Database page before a token is saved](../../images/en/03-settings-db.png)

Check: the pill at the top reads **Not configured**, the line beside it reads "No token: the Agent cannot search GeoForge Database.", and **What the database holds** shows "Paste your activation token in Settings." in red. This is the normal starting point.

3. Click in the **Activation token** box (it shows "Paste activation token").
4. Paste your token. The characters appear as dots.
5. Leave **Database access for Agents** on **Direct through GeoForge Desktop (recommended)**.
6. Click **Save & test database**. The note under the token box changes to "Saving and testing data access…".
7. Wait for the result. On success the note reads "Connected: N catalogue records available.", where N is about 1,100.
8. Click **Close**.
9. Click **Settings** again.
10. Click **GeoForge Database**. The pill and the dataset list refresh only when you open this page again.

> **[Screenshot to add]** Settings → GeoForge Database with a valid token, reopened after a successful **Save & test database**: green **Connected** pill; status line "local catalogue: N records (M direct download) · synced N min ago" and, below it, "Agent access: API providers call the search_catalogue tool, CLI agents run geoforge-db; both read this same local copy and never see the token."; token box showing dots; note "Token is stored privately on this computer, readable only by your user account; the Agent and chat cannot read it."; **What the database holds** list loaded underneath.

Check: the pill reads **Connected** in green, and the status line shows a record count and a recent sync time ("synced just now" or "synced N min ago").

**What Save & test database does.** It saves every Settings page, not only this one. It then sends one test request to the database. If the test passes, GeoForge starts downloading a local copy of the catalogue in the background. The copy holds descriptions only: no data files, links or passwords.

The background download normally finishes within a minute. If you reopen the page before it finishes, the pill may show **Not synced** (or, on a computer where GeoForge has already run without a token, **Unavailable**), and the list may say "The catalogue is being fetched; try again in a moment." Wait a minute, close Settings and open the page again.

> **Tip:** **Save** at the bottom of the window also stores the token, but it does not test it or download the catalogue. Use **Save & test database** whenever you paste a new token.

### Replace or remove the token

Once a token is saved, the box shows only dots. GeoForge never shows the saved token again; the dots only mean "a token is stored". If you leave the dots as they are, the saved token is kept.

To replace the token:

1. Click in the **Activation token** box.
2. Select everything in it (Windows: Ctrl+A; macOS: Cmd+A).
3. Press Delete.
4. Paste the new token.
5. Click **Save & test database**.

> **Caution:** Delete the dots before you paste. If you paste after the dots, GeoForge treats the whole box as "unchanged" and keeps the old token.

To remove the token:

1. Click in the **Activation token** box.
2. Select everything in it (Windows: Ctrl+A; macOS: Cmd+A).
3. Press Delete, so the box is completely empty.
4. Click **Save**.

GeoForge deletes the stored token. When you next open the page, the pill reads **Not configured**.

> **Tip:** The **KI Library** page has its own small settings dialog (⚙) with the same token field. Both save to the same place. This manual uses the main **Settings** window.

## 3.4 Read the database status

The pill at the top of **Settings → GeoForge Database** shows one of five states. **Connected** has two colours.

| Pill | What it means | What to do |
|---|---|---|
| **Not configured** | No token is stored, or GeoForge could not read it from the system password store (section 3.10). | Enter a token (section 3.3). |
| **Off** | You set **Database access for Agents** to **Do not provide database access**. | If you want the database, switch back to **Direct through GeoForge Desktop (recommended)** and click **Save**. |
| **Unavailable** | A token is stored, but the server rejected it (wrong, expired or revoked). It can also show for a few seconds right after you first save a token. | Read the line beside the pill, then see section 3.10. |
| **Connected** (green) | The token works and the local catalogue copy is up to date. | Nothing. |
| **Connected** (amber) | The token works, but the last refresh failed, usually because you were offline. GeoForge keeps using the older copy. | Check your network (section 3.10). |
| **Not synced** | The token works, but the catalogue copy has not been downloaded yet. | Wait a minute, then reopen the page. |

The line beside the pill gives details:

- With a working token: "local catalogue: N records (M direct download) · synced N min ago". If the last refresh failed, the line ends with "· stale:" and the reason.
- Before the copy exists: "catalogue not downloaded", sometimes followed by the reason.
- With a rejected token: "Access unavailable: the token is not authorized, so the Agent cannot search GeoForge Database.", followed by the server's message.
- With access switched off: "Disabled: the Agent will not search the database."

GeoForge refreshes the catalogue copy when it starts and then every 6 hours.

The **GeoForge Database** card inside **Project status → Details** has its own pill with different words:

| Project status pill | Matches the Settings state |
|---|---|
| **Not set up** | **Not configured** |
| **Off** | **Off** |
| **Unavailable** | **Unavailable** |
| **Stale** | **Connected** (amber) |
| **Local copy** | **Connected** (green) or **Not synced** |

### When the database counts as "activated"

GeoForge uses the database for a project only when all three conditions hold:

1. **Database access for Agents** is not set to **Do not provide database access**.
2. A token is stored.
3. The server has not rejected that token.

A network outage does not deactivate the database. Searches keep working from the local copy, which is marked stale.

When the database is not activated:

- The agent gets no database tools and is told that database access is disabled.
- GeoForge does not suggest database datasets for your study.
- A plan that still names a database dataset is sent back to the agent to fix.
- The approval card shows no **Data sources, your pick** list.
- Plans that use only public sources or your own files still work.

If you approve a plan that needs the database after access was switched off or the token was rejected, nothing is approved or downloaded. The chat says: "GeoForge Database access is off or not activated, but this plan still needs it for … Nothing was approved or downloaded. Activate the Database in Settings and approve again, or choose "Modify the plan" to use public sources or your own files. Your saved choices are retained."

## 3.5 Browse the catalogue

You can look through the catalogue yourself before or during a project. This helps you check what exists for your region before you write a request.

### In Settings

1. Open **Settings → GeoForge Database**.
2. Scroll to **What the database holds**. The list loads from the local copy on your computer, so it works offline once the copy exists.
3. To filter, click a chip under **By domain**, **By delivery** or **By kind**. Each chip shows how many datasets it covers. Click the same chip again to clear it.
4. To search, type in **Search datasets…**. The text is matched against the dataset ID, name, type and variable names.
5. Click a row to open its details.
6. Click **Hide** to close the details.

> **[Screenshot to add]** Settings → GeoForge Database, **What the database holds** with a valid token: chip rows **By domain**, **By delivery** (**direct download**, **manual (Baidu Pan)**) and **By kind**, each chip with its count; the line "N of M datasets"; dataset rows showing name, type, years, format, a delivery tag and a size.

Check: the line above the rows reads "N of M datasets". The list shows at most 120 rows; when there are more, the line adds "showing the first 120 — narrow with search".

The **By delivery** chips tell you how a dataset reaches you:

| Delivery tag | What it means |
|---|---|
| **direct download** | GeoForge can download the file itself (files up to 100 MB). |
| **manual (Baidu Pan)** | The file is larger. GeoForge either asks the server to clip it to your study area, or gives you a Baidu Pan link to download it yourself (section 3.7). |

The details panel lists **Variables**, **Period**, **Extent**, **Resolution**, **Format**, **Size**, **Delivery** and **Domains**. A field is left out when the catalogue has no value for it.

> **[Screenshot to add]** Settings → GeoForge Database with one dataset row clicked (for example `cmfd_huai_daily_025` or `bengbu_51080`): the details panel above the list with the dataset name, its ID, the fields Variables, Period, Extent, Resolution, Format, Size, Delivery and Domains, and the **Hide** button.

Check: the panel names the dataset you clicked and shows its ID under the name.

Things to know when browsing:

- **Search in English.** Catalogue text is English. Use English names, station numbers or dataset IDs, for example `huai`, `cmfd` or `51080`. Chinese place names do not match.
- **Search one word at a time here.** The Settings search box looks for the text exactly as you type it, so `huai prec` finds only records containing that exact phrase.
- **Sizes are whole-product sizes.** The size in the list is the size of the entire product, not what your project will download. Section 3.6 explains where to find the real download size.
- **Only main products are listed.** Per-variable and per-year sub-files are hidden, so the total here can be smaller than the record count in the status line.

### From inside a project

1. In an open project chat, click **◇ Project status** at the top right.

![Project status panel with Details collapsed](../../images/en/13-project-status-new.png)

Check: **Details** is the last card, with the hint "acquisition log, folders, catalogue search, data sources, calibration".

2. Click **Details** to expand it.
3. Scroll to the **GeoForge Database** card inside **Details**.
4. Type in the search box ("variable, place, period, or dataset ID"). Here every word you type must appear in a record, so `huai prec` works.
5. Click **Search** (or press Enter).

Check: the card shows "N found; showing M." and one entry per dataset with its delivery tag (**direct** or **manual Baidu**), ID, kind, format, period, variables, coverage, domains and size.

6. To ask the agent about a dataset, click **Check with Agent** under it.

**Check with Agent** closes **Project status** and sends the agent a prepared message. The message asks it to compare the dataset with the KI's input requirements and, during planning, only to write the exact ID into the plan. If the chat is still working, the message waits in the message box for you to send.

If no token is stored or the token was rejected, a search shows the error and an **Open AI settings** button. That button opens the **Settings** window; click **GeoForge Database** in its menu. (The hint on this card still says "AI settings"; it means **Settings → GeoForge Database**.)

## 3.6 How planning uses the database

You do not need to search the catalogue yourself. When the database is activated, the agent does it during planning.

1. **Your request is matched to the catalogue.** GeoForge compares the words in your request (place names, station numbers, dataset names) with the local copy and gives the agent a short list of candidates. Station numbers, basin names and river names help most. Some major Chinese place names, such as 淮河 and 蚌埠, are recognised here.
2. **The agent checks candidates.** While it works, the activity line above the message box may read **Searching GeoForge Database**. The work details show steps such as **Searched GeoForge Database**, **Read dataset schema** (the real variable names and units in the files) and **Estimated a server clip**. The agent may request a few clip estimates while it is understanding the task. These are read-only and download nothing.
3. **The plan records exact IDs.** Each input in the plan's data list names one dataset ID. Nothing is downloaded before you approve.
4. **GeoForge checks the plan.** When the agent submits the plan, GeoForge looks up every ID in the catalogue and fills in delivery, size, coverage and period. Unknown IDs go back to the agent. A whole national or global product of hundreds of gigabytes is never accepted as one download; the plan must use a server clip, a regional subset or smaller per-variable or per-year files.

A catalogue match only shows that the data exists. It does not prove that the data suits your model. The agent must still check units, resolution and coverage, and so should you.

### What the approval card shows

The **Data** section of the approval card ("Approve the plan?") sorts every input into groups. Database inputs appear in two of them:

| Group on the card | Tag on the row | What happens after you approve |
|---|---|---|
| **GeoForge fetches after approval** | **direct download** | GeoForge downloads the file. |
| **GeoForge fetches after approval** | **server clip** | GeoForge asks the server to cut the product to your study area, period and variables, then downloads the clip. |
| **You** | **Baidu download, link shown after approval** | You download the files from Baidu Pan yourself (section 3.7). |

Each row reads `input ← dataset ID · size`. If the agent found more than one suitable dataset for an input, the card also shows **Data sources, your pick**: one radio button per candidate, with the recommended one already selected. If you pick another one and approve, GeoForge switches the plan to it and shows the updated card for you to approve once more.

> **[Screenshot to add]** Approval card ("Approve the plan?") for a plan with a server clip of a large gridded product over a small study area (for example a CMFD or HWSD dataset): the **Data** section with the group **GeoForge fetches after approval** and one row `input ← dataset ID · size` tagged **server clip**, where the size is the small clip size (kilobytes or megabytes); if present, the **Data sources, your pick** list below it.

Check: the row tagged **server clip** shows a size in kilobytes or megabytes, not the whole-product size.

### Which size counts

There are two different sizes, and only one of them is your download:

- **Whole-product size**: shown in the catalogue browser, in search results, and sometimes quoted by the agent in chat. A national forcing product can be hundreds of gigabytes.
- **Clip size**: shown on the approval card row tagged **server clip**. This is what your project will download. In one test, a soil map that was 1.7 GB as a Baidu download became a 14 KB server clip.

Trust the approval card, not sizes quoted in chat. GeoForge estimates the clip size again just before it shows the card and once more when you click **Approve and start**. If the clip has grown noticeably, the source version changed or the estimate failed, the card is shown again with the reason, and you approve again. Approving the plan also approves its server clips; there is no separate data approval.

> **Caution:** Known issue in 0.6.54. The **Data sources, your pick** list can disagree with the dataset in the **Data** section, and sources outside the catalogue (for example NASA POWER) are left out of the list. A line under **Waiting on you** may still say "defaults to NASA POWER unless you pick another". Before you approve, compare the dataset ID after the ← in the **Data** section with what you expect. If they disagree, choose **Modify the plan** and name the source you want.

## 3.7 How approved data arrives

After you approve the plan, GeoForge gathers every approved input before any model step runs. There are three kinds of delivery.

| Delivery | Who does it | Size limit | How it is checked |
|---|---|---|---|
| **Direct download** | GeoForge | up to 100 MB per file | The file is compared with the server's SHA-256 checksum (a fingerprint of the file's exact contents) and downloaded again once if it does not match. ZIP files are unpacked safely; archives with unsafe paths are refused. |
| **Server clip** | GeoForge | up to 2 GB per clip, and enough free disk space | Every part is checked against the job's list of sizes and checksums. A clip much larger than its estimate is refused. |
| **Baidu Pan manual delivery** | You | none | GeoForge records the files you placed and their fingerprints. Baidu files have no server checksum. |

Automatic downloads keep running when **Project status** is closed or you switch to another chat, as long as GeoForge stays open. Waiting for a Baidu file does not hold them up.

> **Caution:** Known limit of the Windows 0.6.54 release: real GeoForge Database downloads (direct, server clip and Baidu Pan) had not been tested end to end on Windows when it was published. If something in this section behaves differently on Windows, report it.

### Follow progress in the chat

While data is being gathered, a banner appears above the message box. Its title tells you what kind of delivery is running:

| Banner title | Meaning |
|---|---|
| **Data preparation · fetching approved data** | Only automatic downloads are running. |
| **Data preparation · manual download needed** | Only Baidu Pan downloads are waiting for you. |
| **Data preparation · automatic and manual downloads are independent** | Both kinds are running side by side. |
| **Approved data acquired · run not started** | Everything is in. The model has not started. |
| **Approved data acquired · software setup needed** | Everything is in, but the model software must be set up first. |

Each automatic input has its own line, for example "Automatic: `dataset ID` — Server subsetting". Typical states are **Server queued**, **Server subsetting**, **Subset ready to download**, **Downloading and checking files**, **Files acquired** and **Acquisition failed**. Each Baidu input has a line "Manual download needed: `dataset ID`".

The banner's **Project status** button opens the panel.

When the last input arrives during a chat turn (for example after you click **Files are in place, continue**), the run continues in that turn. When it arrives in the background, the title changes to **Approved data acquired · run not started** or **Approved data acquired · software setup needed**. The model then waits until you click **Start the approved run**.

> **[Screenshot to add]** Chat footer during acquisition of an approved plan with one server clip and one Baidu Pan dataset: banner titled **Data preparation · automatic and manual downloads are independent**, one line "Automatic: … — Server subsetting", one line "Manual download needed: …", and the **Project status** button.

Check: the banner shows one line per input, and the automatic line changes state while the manual line waits.

Server clip jobs are also listed under **Project status → Details → GeoForge Database acquisitions**, with states such as **Server queued**, **Server processing**, **Ready to download**, **Downloading and verifying** and **Files acquired; scientific checks pending**. GeoForge downloads a ready clip by itself. If a job shows **Download failed; retry available**, click **Download and check all files** under it.

### Download from Baidu Pan yourself

Some datasets are too large to serve directly and cannot be clipped for your study. For these, **Project status** shows a card headed **One thing needs you**, titled "Download 1 dataset from Baidu Pan" (or "Download N datasets from Baidu Pan"). The chat only points you to **Project status**: the link and code are never shown in the chat.

Each row of the card shows:

- the dataset name and its size;
- **Extraction code**: the code Baidu Pan asks for;
- **Inside the share, download only**: shown when you need just one file or folder from a larger share;
- **Place at**: the exact project folder for the files, with a **Copy path** button;
- **Open download link**: opens the Baidu Pan share.

> **[Screenshot to add]** Project status with the Baidu Pan card after approving a plan with one manual-delivery dataset: heading **One thing needs you**, title "Download 1 dataset from Baidu Pan", one row with the dataset name and size, **Extraction code** (blur the code), **Inside the share, download only**, **Place at** with a path ending in `inputs\observations\<dataset ID>` and the **Copy path** button, **Open download link**, and the buttons **Files are in place, continue** and **Change the plan**.

Check: the **Place at** path ends in your dataset's ID.

1. Click **Open download link**. The share opens in your web browser.
2. Enter the code shown after **Extraction code**.
3. If the card shows **Inside the share, download only**, download only that file or folder. Otherwise download the whole share.
4. Wait until the download has completely finished.
5. Click **Copy path** next to **Place at**. The button changes to **Copied**.
6. Open the **Place at** folder:

    - **Windows:** paste the path into the File Explorer address bar and press Enter.
    - **macOS:** in Finder, choose **Go → Go to Folder…**, paste the path and press Return.

7. If the folder does not exist yet, create it with exactly the name at the end of the path (the dataset ID).
8. Move or copy the downloaded files into that folder. Do not leave them in the Baidu Pan download folder.
9. Wait until the copy has finished.
10. In **Project status**, click **Files are in place, continue**.

GeoForge closes **Project status** and sends "I placed … at … Please continue." in the chat. (If the chat is still working, the message waits in the message box for you to send.) GeoForge then fingerprints the files in the folder and signs a run record for them. If no usable files are there yet, the card stays open.

> **Caution:** GeoForge ignores files that are still being written (names ending in `.part`, `.crdownload`, `.tmp`, `.bc!` and similar), files whose names start with a dot, and symbolic links. Click **Files are in place, continue** only after the download and the copy have both finished.

If the download is not practical, click **Change the plan**. The message box fills with "Please change the plan: ". Finish the sentence, for example by asking for a public source or by offering your own file, and send it. The revised plan needs a new approval.

> **Tip:** Baidu Pan is often slow or unusable outside mainland China. If you cannot use it, ask the GeoForge Database owner for another way to receive the files, or click **Change the plan**.

### If an approved download fails

GeoForge stops and shows a card titled "Some approved data could not be fetched" that lists each failure. The chat says "Some approved data could not be fetched. Use the card in the chat to retry or modify the plan."

1. Choose one option on the card:

    - **Retry the missing data**: fetches only the failed items. Files already checked are kept.
    - **Modify the plan**: sends the plan back to the agent with your note.

2. Click **Continue with this choice**.

## 3.8 Where the data goes, and what the run record proves

Everything is saved inside your project folder. In these examples the project folder is `D:\GeoForge-Manual\projects\2026-10-01-huai-test--…`.

| What | Where in the project |
|---|---|
| Direct downloads | `inputs\observations\<dataset ID>\` |
| Baidu Pan files you placed | the **Place at** folder, normally `inputs\observations\<dataset ID>\` |
| Server clips | `inputs\geoforge_subsets\<acquisition ID>\` |
| Original ZIP archives of direct downloads | `.geoforge\downloads\` |
| Signed run records for data | `.geoforge\receipts\data-receipts\` |

The `.geoforge` folder belongs to GeoForge. On macOS Finder hides it; on Windows File Explorer shows it. Do not edit or delete anything in it.

Every input GeoForge brings in gets a signed run record (the app calls it a receipt). **Data in this plan** in **Project status** reads its states from these records and the files on disk, not from what the agent says:

| State | Meaning |
|---|---|
| **Pending** | Not fetched or prepared yet. |
| **Waiting for you** | A Baidu Pan download or a file you must provide is still missing. |
| **Acquired; scientific checks pending** | The data arrived and has a signed run record. |
| **Present; not verified** | Files are in the folder, but no run record covers them. |
| **Fetch failed** | GeoForge could not fetch the item. |
| **No step uses it** | The plan lists the item, but no step uses it, so nothing fetches it. |

> **[Screenshot to add]** Project status → **Data in this plan** after acquisition of a plan with one direct download, one server clip and one Baidu Pan dataset: group **GeoForge fetches** with rows `input ← dataset ID · size` in state **Acquired; scientific checks pending**, group **You** with the Baidu row in the same state after **Files are in place, continue**, and the hint "status comes from receipts and files on disk, not from the agent's words".

Check: every database input reads **Acquired; scientific checks pending**.

If you delete or replace a downloaded file, it stops counting as acquired. Checked downloads are reused when the plan is changed but the same dataset request is kept, so the same data is not fetched twice.

What a data run record proves, and what it does not:

| Delivery | The record proves | The record does not prove |
|---|---|---|
| Direct download | The file matches the server's checksum and came from the approved request. | That the values are correct or suit your model. |
| Server clip | Every part matches the server job's sizes and checksums. | That the clip covers your study area as intended; check the extent yourself. |
| Baidu Pan | Which files you placed, and their fingerprints. | That the files match the original; Baidu Pan files have no server checksum. |

Downloaded data is not checked science. The KI still prepares and checks the inputs (units, extent, values) before the model runs. What GeoForge guarantees is that every approved step has a signed run record before the project is marked **Completed**. **Completed** does not mean the results are scientifically validated; judging them is still your job.

## 3.9 Privacy

**Your token stays on your computer.** It is never written to the settings file, your project folders, chat transcripts or logs, and it is never sent to the agent. The Settings page only ever shows dots.

| | Windows | macOS |
|---|---|---|
| Where the token is stored | Credential Manager, generic credential `com.geoforge.desktop:observation-activation-token` | a private file readable only by your user account: `~/Library/Application Support/KISS/secrets/com.geoforge.desktop.observation-activation-token` |
| Where the catalogue copy is stored | `%APPDATA%\KISS\database\catalogue.json` | `~/Library/Application Support/KISS/database/catalogue.json` |

On Windows you can see or delete the stored token in **Control Panel → Credential Manager → Windows Credentials**, under **Generic Credentials**. If you delete it there, restart GeoForge (tray icon → **Exit GeoForge**, then start it again), because a running GeoForge keeps using the token it has already read.

**The agent sees search results, not the token.** API agents receive cleaned-up dataset descriptions. CLI agents (for example Claude Code, OpenAI Codex or Kimi Code) receive a temporary, read-only pass to GeoForge's own local service. It allows only catalogue search, schema reading and clip estimates, and it stops working when GeoForge closes.

**Baidu Pan links are for you only.**

- Links and extraction codes are shown only to you in **Project status**, never to the agent or in the chat.
- The server logs every link it reveals against your token. A revealed link cannot be withdrawn.
- So that the card survives a restart, GeoForge keeps the links in the project file `.geoforge\manual-download-details.json`.

> **Caution:** Do not share or publish a project folder that still contains `.geoforge\manual-download-details.json`. Remove that file from the copy you share.

## 3.10 If something goes wrong

Messages from the database server appear in English. Results of **Save & test database** appear in the note under the token box.

| What you see | What it means | What to do |
|---|---|---|
| "Paste your activation token in Settings." | No token is stored. | Enter your token (section 3.3). |
| "That token isn't right — check for a copy/paste miss." | The server does not recognise the token. | Copy the whole token again, with no spaces or line breaks. Replace it as in section 3.3 and click **Save & test database**. |
| "Your token expired — ask the group owner for a new one." | The token is older than 6 months. | Request a new token (section 3.2). |
| "This token was revoked — ask the group owner." | The owner withdrew the token. | Contact the owner (section 3.2). |
| Pill **Unavailable**, "Access unavailable: the token is not authorized…" | The server rejected the stored token at the last refresh. | Paste a valid token and click **Save & test database**. If you saved a token only seconds ago, wait a minute and reopen the page first. |
| "Daily download limit reached; resets at midnight server time." | Your token used 20 GB or 2,000 requests today. | Wait until after midnight server time, then click **Retry the missing data**. |
| "GeoForge could not reach GeoForge Database." or pill **Connected** in amber with "· stale: …" | GeoForge is offline, or the proxy route is wrong. | Searches still work from the local copy. Reading dataset schemas, clip estimates and downloads wait for a connection. Check your network and the proxy settings below, then click **Save & test database** to refresh. |
| A message starting "GeoForge Database server or gateway" (for example "…returned HTTP 502" or "…is unavailable") | The problem is on the server side. | Try again later. Do not switch the plan to a manual download because of it. |
| A message naming Credential Manager (Windows), for example "Credential Manager write failed (…)", or "the private token file" (macOS) | GeoForge could not read or save the token in the system password store. The pill may show **Not configured**. | Restart GeoForge and click **Save & test database** again. On Windows, check that Credential Manager opens from Control Panel. |
| "The catalogue is being fetched; try again in a moment." | The first catalogue download is still running. | Wait a minute and reopen **Settings → GeoForge Database**. |
| The note stays on "Saving and testing data access…" | Another Settings page has an invalid value, so nothing was saved. The error appears at the bottom of the window, next to **Save** (for example "proxy address is required in manual mode"). | Fix that page (for example, type a proxy address in **Network & proxy**), then click **Save & test database** again. |
| The pill or the dataset list does not change after a successful test | The page is not refreshed automatically. | Click **Close**, open **Settings** and click **GeoForge Database**. If the list is still empty, reload. Windows: press F5 in the GeoForge browser tab. macOS: quit and reopen GeoForge. |
| Search finds nothing you expected | Catalogue text is English, and the Settings box matches your text as typed. | Search for one English word, a station number or a dataset ID. |
| Approve is refused with "GeoForge Database access is off or not activated…" | The plan needs the database, but it is not activated. | Activate it (section 3.3) and approve again, or choose **Modify the plan** to use public sources or your own files. |
| The Baidu Pan card stays open after **Files are in place, continue** | GeoForge found no usable files in the **Place at** folder. | Check that the files are in exactly that folder, that the download and copy are finished, and that the names do not start with a dot. Then click the button again. |
| "… already holds files with no receipt …" | The target folder already contains files GeoForge cannot account for. Nothing was overwritten. | Move those files out of the folder and click **Retry the missing data**, or choose **Modify the plan** to use them as your own input. |
| "The downloaded file failed integrity verification twice." | The file did not match the server's checksum. | Click **Retry the missing data**. If it happens again, report it to the database owner. |
| "The downloaded archive contains an unsafe path." | GeoForge refused a ZIP file for safety. | Report it to the database owner and choose **Modify the plan**. |
| "Insufficient local disk space for the complete verified acquisition" | Not enough free space for a server clip. | Free disk space on the drive that holds the project, then click **Retry the missing data**. |
| An entry under **Clip estimates on file** (in **GeoForge Database acquisitions**) shows **Estimate failed; acquisition unverified** | The server could not estimate the clip. No job was created and nothing was downloaded. | Ask the agent in chat to estimate the clip again. If the message names an unknown source variable, ask it to read the dataset schema and estimate again with the exact variable names. Do not ask it to remove the variable filter. |
| The agent says a dataset is "unavailable" because it is a Baidu Pan download | Manual delivery is a normal path, not a missing dataset. | Tell the agent to keep the dataset if it suits the study, or choose another source. |

> **Caution:** If you replace a working token with a wrong one, the test shows an error, but the pill can stay **Connected** for up to 6 hours, until the next catalogue refresh. Trust the note under the token box, and paste the correct token again.

> **Tip:** The stale warning the agent may quote says "Refresh explicitly in Settings". There is no separate refresh button: **Save & test database** is the way to force a refresh.

### Proxy settings and the database

Database traffic follows **Settings → Network & proxy**.

1. Click **Settings** at the bottom of the left sidebar.
2. Click **Network & proxy**.

![Network & proxy page with Observation data ticked](../../images/en/04-settings-net.png)

Check: under **Use proxy for**, **Observation data** is ticked. It is ticked by default.

- **Observation data** ticked: database requests use the proxy chosen under **Proxy**.
- **Observation data** not ticked: database requests go out directly and ignore every proxy.
- **Enter proxy manually**: type the address, for example `http://127.0.0.1:7897`. Proxy passwords are not stored.
- **Do not use a proxy**: no request uses a proxy.

| | Windows | macOS |
|---|---|---|
| First proxy option | Reads **Use Mac system proxy (recommended)**, but uses the Windows system proxy. | **Use Mac system proxy (recommended)** uses the macOS system proxy. |

If the database works without your VPN but fails with it on:

1. On **Network & proxy**, untick **Observation data**.
2. Click **Save**.
3. Click **GeoForge Database** in the Settings menu.
4. Click **Save & test database**.

Baidu Pan downloads happen in your own browser or Baidu client, so GeoForge's proxy settings do not affect them.
