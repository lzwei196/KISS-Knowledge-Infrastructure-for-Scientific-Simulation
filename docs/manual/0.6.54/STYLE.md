# Manual style guide (0.6.54)

**Reader.** A scientist (hydrology, crops, snow, soil, climate…) who knows their model's science but is not a software developer. Many read Chinese first; many use Windows. They want to get a correct, trustworthy model run without learning internals.

**Voice.** Plain words, short sentences, second person ("Click **Save**."). Explain *why* in one clause when it prevents a mistake. No marketing tone, no hedging filler, no internal jargon (say "run record", not "receipt", except where the UI shows the word; say "the AI", "the agent" only when the UI does).

**Accuracy.** Describe the app exactly as it behaves in 0.6.54 (Windows build `windows-mac-sync-20260930`, mac 0.6.54). Name every button and panel with its exact on-screen label in **bold**. The English edition uses English labels only; the Chinese edition uses the Chinese labels, and where a screen shows English text even in Chinese mode, say so once ("此卡片标题为英文"). Never document controls that do not exist or cannot be reached.

**Chapter shape.**
1. One-sentence purpose ("In this chapter you will…").
2. Numbered steps for anything the reader does. One action per step.
3. A screenshot right after the step it illustrates: `![Short description](../../images/en/NN-name.png)` (Chinese: `images/zh-CN/`). Then one line saying what to check in it.
4. "If something goes wrong" with the real messages and fixes.
5. Warnings for known issues as `> **Caution:** …`; tips as `> **Tip:** …`.

**Formatting.** Markdown: `#` chapter title, `##` sections, `###` sub-sections; tables for comparisons; inline code for paths, commands and file names. Keep paragraphs under five lines. Windows and macOS differences go in a small table or in clearly labelled lines, not interleaved sentences.

**Privacy in examples.** Example paths use `D:\GeoForge-Manual\…` or `C:\Users\you\…`; never real user names, keys, tokens or Baidu links.

**Honesty about limits.** A finished run of an example is not a validation of the model. Downloaded data is not checked science. Say what GeoForge guarantees (every approved step has a signed run record before **Completed**) and what it does not.
