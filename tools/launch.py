"""PyInstaller entry point; frozen workers must divert before importing Qt."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from bongo_chat.__main__ import main
    raise SystemExit(main())
