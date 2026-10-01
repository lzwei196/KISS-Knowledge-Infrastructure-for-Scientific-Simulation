# 1 Set up the agent

**Goal:** connect an AI before starting a scientific project. This Windows guide uses DeepSeek API, the provider used in the verified example on page 3.

## Connect DeepSeek

1. Open GeoForge Desktop. Click **Settings → AI services**.
2. In **DeepSeek (API)**, click **Get a key**. Create a key in your own provider account; return to GeoForge and paste it into **Paste API key**.
3. Select **Use by default**, then **Save**. Click **Test AI & GitHub**. A saved key alone does not prove that the connection works.
4. When the AI test succeeds, close Settings. The sidebar should show **AI ready**. If it fails, read the test error and check the provider account and **Network & proxy** settings.

> **Keep credentials private.** Enter API keys only in Settings. Never put an API key or GeoForge Database token in chat, a screenshot, or a project file. The Database is optional and is not needed for this example.

## Start the project

1. Click **＋ New chat**. Name it `SHAW official Trial` and choose a project parent folder, for example `D:\GeoForge\projects`. In Windows browser mode, paste the folder path.
2. Before the first message, select **API → DeepSeek (API) → deepseek-chat** in the chat header.
3. Click **Auto KI**, search `SHAW`, select it and click **Apply**. Continue with page 2.

The project folder holds this chat's inputs, results and run records. Model software has a separate installation folder and can be reused by other projects.

## Prefer a local CLI?

Install and sign in to a supported CLI such as Claude Code or OpenAI Codex using its own instructions. In **Settings → AI services**, click **Recheck local CLIs**; select **Local** and that agent before the first chat message. This is an alternative connection path; the worked example was tested with DeepSeek API.

**Checkpoint:** AI test passed; the new chat shows the intended AI and SHAW. Once the first message is sent, start a new chat to change its AI or KI.
