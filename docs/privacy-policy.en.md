# Privacy policy

[English](privacy-policy.en.md) · [한국어](privacy-policy.md)

Updated October 28, 2026 to describe the current source, including local language preferences. Bongo Cat Chat is an unofficial companion maintained by an independent developer. Questions can be raised in [project issues](https://github.com/misosiruda/bongo-cat-chat/issues). Do not post chat contents, account identifiers or lobby identifiers in public issues.

## Local history and game integration

The October 28, 2026 source also stores observed lobby join/leave events, including the display name at observation, player Steam ID, lobby ID and observation time, in the same local database for 30 days. The account-local app block list and history deletion apply. Notices are not sent as lobby chat or Windows notifications. Activity before connection or during connection gaps is not reconstructed. Published-build availability is separate.

The app stores received chat, messages you compose and send, drafts, display names, Steam account IDs, lobby IDs and app preferences on this PC. The default database is `%LOCALAPPDATA%/BongoCatChat/history.sqlite3`. It is an unencrypted SQLite file. There is no separate encryption or cloud backup, and anyone who can access the file may be able to read it.

History is separated by account. Messages and drafts are retained for 30 days and cleaned up at startup and while the app is running. Cleanup does not run while the app is closed. Settings let you delete the selected lobby's history or all history for the current account after confirmation. Deletion does not guarantee that data cannot be recovered from the storage device. Uninstalling preserves history and preferences; use the app's deletion controls before uninstalling to delete history.

To integrate with the existing lobby, the app loads the Steam API DLL from the locally installed game and reads compatibility information, the current lobby, cat appearance. It reads installed game resources to display cat images in memory. It does not modify game files, inject DLLs or write to game memory. It does not recover conversations from periods when it was not running.

Messages you send are delivered through Steam's existing lobby chat to other participants in that lobby. Steam's handling is covered by [Valve's privacy policy](https://store.steampowered.com/privacy_agreement/). Acceptance for sending does not mean another participant has read the message.

## Steam ID chat blocks

Hiding a cat in the game does not prevent chat receipt or storage. The app stores the current account ID, blocked Steam ID and any display name known when blocking in its local database. Blocks do not expire, persist across lobbies and restarts, and are not synchronized to other PCs or Steam. A manually entered ID can have no stored name. Unblocking in Settings or the participant list deletes the block entry. History deletion, retention cleanup and uninstalling do not remove blocks.

New messages from blocked users are not saved. Existing messages are excluded from chat, search, unread indicators, notifications and reactions. Unblocking restores retained history, but cannot recover messages discarded while blocked.

## Windows notifications

While the app is running but inactive, new messages from other players can trigger taskbar flashes and Windows notifications. These two preferences are saved locally and default to enabled. Windows receives only the app name and a fixed new-message notice in the selected app language. Chat text, sender names, Steam IDs and lobby information are not included in notification history. No external push service is used.

Toasts replace a single item in the `incoming` group for the app's own `BongoCatChat.Desktop` identity and expire after one day. The app clears its own group when it becomes active, notifications are disabled, connection/permission boundaries change, or the app closes or hands off an update. Uninstallation also clears that group. Windows errors or abnormal termination can leave a generic notice behind; it can be removed in Notification Center. Windows notification and Do Not Disturb settings may restrict display. Submission to Windows does not prove a banner appeared or was read.

## GitHub updates and your choice

With update checks enabled, installed copies contact GitHub for release metadata and downloads. Destinations include `api.github.com`, `github.com` and the GitHub hosts serving update assets. Requests do not upload chat contents, Steam account IDs, lobby IDs or the local database. GitHub may process ordinary connection metadata such as your IP address, request time and User-Agent.

You can disable GitHub update checks and downloads in the installer or app settings. Disabling them stops scheduled checks, compatibility-triggered checks and manual checks; Steam chat can still be used. Cancellation cannot retract a request already sent. An already verified and prepared update may still be applied locally on the next launch.

The preference is stored as `AllowUpdateChecks` under `HKEY_CURRENT_USER\Software\BongoCatChat` for the current Windows user, and persists through reinstall and uninstall. First installs and older installations with no saved choice default to enabled. Silent installation supports `/S /UPDATECHECKS=0` to disable or `/UPDATECHECKS=1` to enable requests; omission preserves an existing choice. Privacy, open-source and corresponding-source notices are available in app settings without a network request.

The installer creates the current user's app files, Start menu shortcut, Windows uninstall entry and update preference. It does not require administrator access or register automatic startup.

## Language preferences and other transfers

The selected language is stored locally with the other app settings. System default uses the Windows display language, choosing Korean for Korean and English otherwise. Translation is entirely local: messages, drafts, player names and lobby names are not sent to a translation service or automatically translated.

The current implementation has no developer-operated chat upload service, cloud synchronization, advertising/analytics telemetry or automatic crash reporting. If data handling or connection destinations change, this policy and the related user controls must be updated together.
