import os, sys, importlib

# Use Streamlit's CLI entrypoint (works across versions)
try:
    from streamlit.web import cli as stcli  # type: ignore[reportMissingImports]
except Exception:
    stcli = importlib.import_module("streamlit.cli")  # type: ignore[attr-defined]

def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel)

APP_FILE = resource_path("app.py")

if __name__ == "__main__":
    # Force non-dev mode so we can set server.port explicitly
    sys.argv = [
        "streamlit", "run", APP_FILE,
        "--global.developmentMode=false",
        "--server.headless=false",
        "--server.address=localhost",
        "--server.port=8501",
        "--browser.serverAddress=localhost",
        "--browser.gatherUsageStats=false",
    ]
    stcli.main()
 