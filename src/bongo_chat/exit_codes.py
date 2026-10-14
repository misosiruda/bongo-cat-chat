"""Process status shared by the app and the Qt-free installed launcher."""

# Another copy owns this data profile. Retrying after it closes is safe and
# must not mark the selected release as broken or change the active version.
PROFILE_IN_USE = 20
