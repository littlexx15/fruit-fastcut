"""Source and packaged entry point, including worker dispatch."""
import importlib
import os
from pathlib import Path
import sys


def main():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    os.environ['PATH'] = str(root / 'bin') + os.pathsep + os.environ.get('PATH', '')
    if len(sys.argv) > 2 and sys.argv[1] == '--worker':
        worker = sys.argv[2]
        sys.argv = [sys.argv[0]] + sys.argv[3:]
        if worker == 'prep_clips':
            import prep_clips
            prep_clips.main()
        elif worker == 'batch_cut':
            import batch_cut
            batch_cut.main()
        else:
            raise SystemExit('Unknown worker')
        return
    if getattr(sys, 'frozen', False) and os.name == 'nt':
        import ctypes
        window = ctypes.windll.kernel32.GetConsoleWindow()
        if window:
            ctypes.windll.user32.ShowWindow(window, 0)
    app = importlib.import_module('混剪工具')
    app.App().mainloop()


if __name__ == '__main__':
    main()
