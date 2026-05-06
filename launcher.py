"""
Zava Insurance – Windows Store Launcher
Starts the Flask server and opens a native app window via pywebview.
"""
import sys
import os
import threading
import time
import socket
import tempfile

# Ensure we can find our bundled files when running as PyInstaller exe
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    os.chdir(BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    os.chdir(BASE_DIR)

# Add base dir to path so imports work
sys.path.insert(0, BASE_DIR)


def find_free_port():
    """Find a free port to avoid conflicts."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_for_server(port, timeout=30):
    """Wait until the Flask server is responding."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.2)
    return False


def start_flask(port):
    """Start Flask in a background thread."""
    log_file = os.path.join(tempfile.gettempdir(), 'zava_insurance_log.txt')
    try:
        with open(log_file, 'a') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] Importing app...\n")
            f.write(f"  CWD: {os.getcwd()}\n")
            f.write(f"  BASE_DIR: {BASE_DIR}\n")
        from app import app
        with open(log_file, 'a') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] App imported, starting Flask on port {port}\n")
        app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
    except Exception as e:
        with open(log_file, 'a') as f:
            import traceback
            f.write(f"[{time.strftime('%H:%M:%S')}] ERROR: {e}\n")
            f.write(traceback.format_exc())


def main():
    port = find_free_port()

    # Write port to temp file for diagnostics
    port_file = os.path.join(tempfile.gettempdir(), 'zava_insurance_port.txt')
    with open(port_file, 'w') as f:
        f.write(str(port))

    # Start Flask server in background
    server_thread = threading.Thread(target=start_flask, args=(port,))
    server_thread.daemon = False
    server_thread.start()

    # Wait for server to be ready
    if not wait_for_server(port, timeout=30):
        sys.exit(1)

    url = f'http://127.0.0.1:{port}'
    log_file = os.path.join(tempfile.gettempdir(), 'zava_insurance_log.txt')

    # Try pywebview first (native window), fall back to Edge --app mode
    try:
        import webview
        with open(log_file, 'a') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] Starting pywebview...\n")
        webview.create_window(
            'Zava Insurance \u2013 On-Device AI Demo',
            url,
            width=1400,
            height=900,
            min_size=(1024, 700),
        )
        webview.start()
    except Exception as e:
        with open(log_file, 'a') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] pywebview failed ({e}), using Edge --app\n")
        # Edge --app mode: opens as a chromeless standalone window (looks like native app)
        import subprocess
        edge_paths = [
            os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
            os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
            os.path.expandvars(r'%LocalAppData%\Microsoft\Edge\Application\msedge.exe'),
        ]
        edge = next((p for p in edge_paths if os.path.exists(p)), None)
        if edge:
            subprocess.Popen([
                edge, f'--app={url}',
                '--window-size=1400,900',
                '--disable-extensions',
            ])
        else:
            import webbrowser
            webbrowser.open(url)

        # Keep process alive so Flask keeps serving
        # The app exits when the user closes it via Task Manager or system
        server_thread.join()


if __name__ == '__main__':
    main()
