from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import urllib.request
import webbrowser


def configure_data_dir_env() -> None:
    # Regle: le dossier de persistance doit etre decide avant l'import de server.py.
    # Sinon, en mode PyInstaller onefile, state/deaths/log partent dans le dossier temporaire.
    if os.environ.get("OVERLAY_DATA_DIR"):
        return

    if getattr(sys, "frozen", False):
        os.environ["OVERLAY_DATA_DIR"] = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data")
        return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ["OVERLAY_DATA_DIR"] = os.path.join(project_root, "data")


configure_data_dir_env()

import server

PORT_CANDIDATES = (8787, 18080, 5500, 3000, 8888, 9000)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lanceur Terraria Overlay (settings + overlay).")
    parser.add_argument("--port", type=int, default=0, help="Port force (sinon detection auto).")
    parser.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir les pages automatiquement.")
    parser.add_argument("--ready-timeout", type=float, default=8.0, help="Timeout d'attente du serveur en secondes.")
    return parser.parse_args()


def try_create_server(port: int):
    try:
        return server.create_http_server(port)
    except OSError:
        return None


def pick_httpd(explicit_port: int):
    ports = [explicit_port] if explicit_port > 0 else list(PORT_CANDIDATES)
    for port in ports:
        httpd = try_create_server(port)
        if httpd:
            return httpd, port
    return None, 0


def wait_api_ready(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.time() + max(1.0, float(timeout_seconds))
    url = f"http://{host}:{port}/api/state"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.2) as resp:
                if 200 <= int(resp.status) < 500:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def serve_forever(httpd, stop_event: threading.Event) -> None:
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        stop_event.set()


def main() -> int:
    args = parse_args()

    os.chdir(server.APP_ROOT)
    server.perform_boot_sync()

    httpd, selected_port = pick_httpd(args.port)
    if not httpd:
        print("Erreur: impossible d'ouvrir un port pour l'overlay.")
        return 1

    server.PORT = selected_port
    os.environ["OVERLAY_PORT"] = str(selected_port)

    stop_event = threading.Event()
    thread = threading.Thread(target=serve_forever, args=(httpd, stop_event), daemon=True)
    thread.start()

    if not wait_api_ready(server.HOST, selected_port, args.ready_timeout):
        print("Erreur: le serveur ne repond pas a temps.")
        httpd.shutdown()
        httpd.server_close()
        return 1

    control_url = f"http://{server.HOST}:{selected_port}/control.html"
    overlay_url = f"http://{server.HOST}:{selected_port}/overlay.html"
    print(f"Serveur actif: http://{server.HOST}:{selected_port}")
    print(f"Settings: {control_url}")
    print(f"Overlay : {overlay_url}")

    if not args.no_browser:
        webbrowser.open(control_url)
        webbrowser.open(overlay_url)

    try:
        while not stop_event.is_set():
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        httpd.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
