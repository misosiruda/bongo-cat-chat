# Bongo Cat Chat

The October 28, 2026 source separates **in-game cat visibility from chat blocking**. Chat from hidden cats remains visible. Block or unblock by Steam ID in the participant list or **Settings → Chat blocking**. Blocks persist across lobbies and restarts for the current Steam account on this device. New messages from blocked users are not saved; existing history is hidden until unblocked. This source change has not been released or accepted in a live lobby. Earlier game-visibility descriptions below are historical.

[English](README.en.md) · [한국어](README.md)

A third-party Windows messenger for **Bongo Cat's existing lobby chat**. Read and write lobby messages in a separate window, and search the messages the app has received and saved on your PC. Other players do not need this app to chat with you.

**This is an experimental development build, not an official or developer-approved Bongo Cat integration.** Testing has primarily been on one PC. Clean game installations, other PCs and extended sessions still need acceptance testing. See [what has been verified](#verification-and-limitations) before trying it.

## Features

- Send and receive text through the game's existing Steam lobby chat.
- View your outgoing messages in the messenger, with separate sending, accepted, failed and unknown states.
- Keep received messages and drafts locally for 30 days, with conversation search and manual deletion.
- Show the current lobby's player names and static cat profiles using locally installed game resources.
- Respect the game's individual hidden-player settings. Messages from players whose hidden status is unknown are withheld.
- Open a verified participant's Steam profile. Friend requests are handled by you in Steam.
- Show temporary cat, meow and game-emote reactions, with an on/off preference. Reactions do not become chat history or message notifications.
- Choose light, dark or system appearance, and collapse the sidebar.
- Independently enable taskbar flashes and Windows notifications for new messages while the app is inactive. Notifications contain no player names or message text.
- Allow or disable GitHub update checks and downloads. Supported installed versions prepare verified updates and restart after a notice, once typing and sending finish and drafts are saved.

The `0.1.0.dev16` source includes **English and Korean UI**. In **Settings → Language**, choose **English**, **한국어**, or **System default**. System default selects Korean for a Korean Windows display language and English otherwise. Changes apply immediately and persist on this device. Message text, drafts, player names and lobby names are not translated. See the [dev16 release notes](docs/releases/0.1.0.dev16.md).

**Source changes do not update an installed app by themselves.** The latest published installer may not yet contain the bilingual UI or every feature described here. Check the release notes for the build you download.

## Install and start

1. Open [the latest published release](https://github.com/misosiruda/bongo-cat-chat/releases/latest).
2. Download `BongoCatChat-<version>-windows-x64-Setup.exe`. The source-code archives are not installers; `bongo-cat-chat-windows-x64.zip` is the update payload.
3. Close any running Bongo Cat Chat window, then run the installer. It installs for the current Windows user without requiring Python, Git or administrator privileges.
4. Start Steam and Bongo Cat, join a lobby in the game, then launch **Bongo Cat Chat** from the Start menu.
5. Wait for the connection status to confirm the lobby. Use **Settings → Language** if your installed build includes language selection.

The app targets **64-bit Windows 10 or later**. Some published installers use Korean: **다음** means **Next**, **설치** means **Install**, and **마침** means **Finish**. The development installers documented in this repository do not yet have Windows publisher code signing; update-signature verification is a separate mechanism and does not establish Windows publisher trust.

## Using the messenger

| Action | Control |
| --- | --- |
| Send a message | Enter or the Send button |
| Insert a line break | Shift + Enter |
| Search the selected conversation | Ctrl + K |
| Return to recent messages | Latest messages / Scroll to bottom |
| Open a player's Steam profile | Their name or cat, or the participant list, when available |
| Change language or appearance | Settings |
| Delete saved history | Settings → selected lobby or current account history; confirm deletion |

Development builds limit outgoing messages to **50 UTF-16 code units**. This is a conservative app limit, not a verified official game limit. “Sent · Accepted by Steam” means the API accepted the message; it is not a read receipt. Messages with uncertain delivery are not automatically resent.

Your own messages appear in this app. The app does not add a speech bubble above your own character in the game or resend messages to create one.

## Local data and network access

Messages, drafts, display names, account/lobby identifiers and preferences are kept locally. The database is normally `%LOCALAPPDATA%/BongoCatChat/history.sqlite3`, in **unencrypted SQLite**. Anyone with access to that file may be able to read it.

Messages and drafts expire after 30 days, with cleanup while the app is running. Uninstalling preserves local data. Use the app's deletion controls before uninstalling if you want to remove history. The app cannot recover messages sent before it connected, while it was closed, or while a player's messages were withheld.

User-authored chat travels through Steam lobby chat. Optional update checks contact GitHub without uploading chat contents, the local database or game identifiers. This project has no developer-operated chat collection, cloud synchronization or telemetry service. See the [English privacy policy](docs/privacy-policy.en.md) for details and update controls.

## How it connects

The app runs as a separate Python/PySide6 process. It uses the locally installed game's Steam API DLL for lobby chat and reads supported game structures, process memory and installed resources to verify the lobby, hidden-player state and cat appearance.

The product does not modify game files, inject DLLs, patch the game or write to game memory. Game updates can still break compatibility. If the required structures cannot be verified, the app pauses the relevant integration rather than assuming it is safe to proceed. It does not automatically join, leave or move game lobbies.

## Verification and limitations

| Area | Evidence and remaining limits |
| --- | --- |
| Steam connection and lobby messages | Real receive/send paths have been exercised on one PC. The user confirmed delivery to lobby participants; remote screens were not automatically verified. |
| Clean game installations | Not yet accepted. The original test PC had an existing Auto Chest Opener patch; that tool is not an app prerequisite. |
| UI, storage and filtering | Automated tests use synthetic data and an offline Qt renderer. These do not prove live-game behavior. |
| English and Korean UI | Source implementation; language, layout and persistence checks are recorded in [localization notes](docs/localization.md). Public release and installed-copy acceptance are separate. |
| Profiles and reactions | Supported static skins/hats and available local resources are used. Not all game appearances or effects are guaranteed. |
| Notifications | Windows notification preferences and Do Not Disturb can affect delivery. API submission does not prove a visible banner or that it was read. |
| Lobby changes, reconnects and long sessions | Additional live-game and other-PC acceptance remains. |

Detailed historical evidence is in the [product validation record (Korean)](docs/product-validation.md), [game compatibility notes (Korean)](docs/game-update-compatibility.md) and [decision log (Korean)](docs/decisions.md). Their dates and test conditions matter; an older successful check does not certify a newer game build.

## Run from source

Use Python 3.13 on Windows. From the repository root:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
.venv/Scripts/python.exe -m bongo_chat --offline --data-dir ./artifacts/english-offline
```

Offline mode opens the real UI without initializing Steam or connecting to the game. Use a separate data directory for experiments. Live connection requires the additional compatibility preparation described in [Windows development instructions (Korean)](docs/windows-app.md).

```powershell
.venv/Scripts/python.exe -m pytest tests/test_localization.py -q
```

## Feedback and licensing

Feedback is welcome through [GitHub Issues](https://github.com/misosiruda/bongo-cat-chat/issues). Include the app version, Windows version, what you expected and what happened. Do not post other players' messages, Steam IDs, lobby IDs, join codes, private logs or game binaries.

The project's own source and documentation use the [MIT License](LICENSE). Third-party components, game names and artwork remain subject to their respective rights. MIT licensing does not imply approval from the game developers or settle all distribution conditions. See [third-party notices and corresponding sources](docs/licensing/SOURCES.md).
