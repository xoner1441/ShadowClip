# Keep tkinter discoverable for the bundled Codex Python runtime. The stock
# PyInstaller pre-hook incorrectly marks this runtime's Tk install as broken.
def pre_find_module_path(hook_api):
    return
