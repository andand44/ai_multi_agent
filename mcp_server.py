import os
import sys
from mcp.server.fastmcp import FastMCP

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

mcp = FastMCP("FileSystem")
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

@mcp.tool()
def save_file(filename: str, content: str) -> str:
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(WORKSPACE_DIR, safe_filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Файл {safe_filename} сохранен."

@mcp.tool()
def read_file(filename: str) -> str:
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(WORKSPACE_DIR, safe_filename)
    if not os.path.exists(filepath):
        return f"Ошибка: Файл {safe_filename} не найден."
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    mcp.run(transport="stdio")