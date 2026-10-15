"""Process status shared by the app and the Qt-free installed launcher."""

# Another copy owns this data profile. Retrying after it closes is safe and
# must not mark the selected release as broken or change the active version.
PROFILE_IN_USE = 20

# A normal, fully saved app shutdown asking the installed launcher to apply the
# staged update and open the app again. Older launchers must never receive it.
RESTART_FOR_UPDATE = 21
RESTART_CAPABILITY = 'BONGO_CHAT_RESTART_SUPPORTED'
UPDATE_DIAGNOSTIC_FAILED = 22  # Network/permission diagnostics are not app crashes.
