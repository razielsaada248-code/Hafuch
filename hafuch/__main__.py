"""Run: python -m hafuch [--dry-run] [--no-tray]"""
import argparse
import sys
import threading


def main():
    ap = argparse.ArgumentParser(prog='hafuch')
    ap.add_argument('--dry-run', action='store_true', help='print decisions, type nothing')
    ap.add_argument('--no-tray', action='store_true', help='run without tray icon (Ctrl+C to quit)')
    args = ap.parse_args()

    if sys.platform == 'win32':
        from . import platform_win as pm
        platform = pm.WindowsPlatform()
    elif sys.platform == 'darwin':
        from . import platform_mac as pm
        platform = pm.MacPlatform()
    else:
        sys.exit('Hafuch runs on Windows and macOS only.')

    if not pm.single_instance():
        sys.exit('Hafuch is already running.')

    from . import config
    from .app import Controller
    cfg = config.load()
    controller = Controller(platform, cfg, dry_run=args.dry_run)

    if args.no_tray:
        platform.start(controller)
        print('Hafuch running' + (' (dry-run)' if args.dry_run else '') + ' - Ctrl+C to quit')
        try:
            if hasattr(platform, 'run_without_tray'):
                platform.run_without_tray()        # macOS needs the main run loop
            else:
                threading.Event().wait()
        except KeyboardInterrupt:
            pass
        platform.stop()
        return

    from . import tray
    platform.start(controller)
    tray.run(controller, pm, platform.stop)     # blocks on the main thread (required on macOS)


if __name__ == '__main__':
    main()
