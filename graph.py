import os
import asyncio
import json
import threading
import socketserver
import http.server
import functools
import socket
import base64
import subprocess
import shutil
from typing import TypedDict, Literal, List

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from config import get_llm, get_vision_llm


class AgentState(TypedDict):
    task: str
    plan: str
    feedback: str
    iterations: int
    game_folder: str
    generated_code: str
    best_code: str
    test_sequence: List[str]
    test_expected_key: str


class CodeFiles(BaseModel):
    html: str = Field(description="Полный код index.html")
    css: str = Field(description="Полный код style.css")
    js: str = Field(description="Полный код game.js")
    tutorial: str = Field(description="Текст правил игры для экрана обучения (1-2 предложения)")
    test_sequence: List[str] = Field(description="Массив из 3-5 разных валидных JS-действий для теста. Например: ['window.game.clickCell(0,0)', 'window.game.clickCell(1,1)']")
    test_expected_key: str = Field(description="ВСЕГДА строка 'actions'")


llm = get_llm(max_tokens=16000)


# ---------- Planner ----------

def planner_node(state: AgentState):
    print("\n👷 [Planner] Придумываю концепт головоломки...")
    prompt = [
        SystemMessage(content=(
            "Ты — креативный гейм-дизайнер. Придумай УНИКАЛЬНУЮ логическую головоломку. "
            "ЗАПРЕЩЕНО предлагать клише:\n"
            "1. Просто 2048, Сапер, Пятнашки, Судоку или Memory.\n"
            "2. Соединение цветов (Flow), сортировка жидкостей, поиск пар.\n"
            "3. Сюжеты про космос, древние храмы, лаборатории или спасение мира.\n"
            "Придумай что-то свежее. Опиши правила, цель, механику кликов и условие победы."
        )),
        HumanMessage(content=f"Задача: {state['task']}"),
    ]
    try:
        response = llm.invoke(prompt)
        print("  Концепт готов.")
        return {"plan": response.content}
    except Exception as e:
        print(f"  [!] Ошибка APInex ({e}). Переключаюсь на локальную Ollama...")
        from langchain_ollama import ChatOllama
        fallback = ChatOllama(model="qwen2.5:3b", temperature=0)
        response = fallback.invoke(prompt)
        print("  Концепт готов (Ollama).")
        return {"plan": response.content}


# ---------- Coder ----------

async def coder_node(state: AgentState):
    print(f"\n💻 [Coder] Пишу код (Попытка {state['iterations'] + 1})...")

    folder_path = os.path.join("workspace", state["game_folder"])
    os.makedirs(folder_path, exist_ok=True)

    feedback_text = (
        f"\n\n⚠️ Tester нашел проблемы:\n{state['feedback']}\n"
        if state.get("feedback")
        else ""
    )

    previous_code = state.get("best_code") or state.get("generated_code") or ""
    previous_block = (
        f"\n\nВОТ ТВОЙ ТЕКУЩИЙ КОД. НАЙДИ ОШИБКУ И ИСПРАВЬ ТОЛЬКО ЕЁ. НЕ ПЕРЕПИСЫВАЙ ИГРУ С НУЛЯ:\n{previous_code}"
        if previous_code
        else ""
    )

    prompt = [
        SystemMessage(content=(
            "Ты — опытный Frontend-разработчик. Напиши или доработай браузерную головоломку.\n"
            "ЖЁСТКИЕ ПРАВИЛА:\n"
            "1. Ответ СТРОГО в формате JSON (html, css, js, tutorial, test_sequence, test_expected_key).\n"
            "2. 🔥 ЕСЛИ ТЫ ИСПРАВЛЯЕШЬ КОД: не переписывай рабочие функции. Измени только ту часть, на которую указал Tester.\n"
            "3. Добавь элемент с id='tutorial' или модальное окно при старте, где выводится текст обучения (правила игры).\n"
            "4. 🔥 ЭКСПОРТИРУЙ window.game. В конструкторе строка `window.game = this;` должна быть ПЕРВОЙ.\n"
            "5. В КАЖДОМ публичном методе (клик, движение) ПЕРВОЙ строкой делай: `this.actions = (this.actions || 0) + 1;`\n"
            "6. 🔥 test_sequence: массив из 3-5 разных валидных действий под твою игру. Если игра на кликах — "
            "['window.game.clickCell(0,0)', 'window.game.clickCell(1,1)']. Если на стрелках — "
            "['window.game.move(\"left\")', 'window.game.move(\"up\")']. Tester выполнит их по очереди.\n"
            "7. test_expected_key ВСЕГДА строка \"actions\".\n"
            "8. Обновляй DOM/Canvas в методах сразу же — не только в requestAnimationFrame.\n"
            "9. Добавь console.log('GAME_START') при старте.\n"
            "10. Обрабатывай невалидные клики/ходы (защита от NaN, выход за границы)."
        )),
        HumanMessage(content=(
            f"Концепт:\n{state['plan']}\n\n"
            f"Задача: {state['task']}"
            f"{feedback_text}"
            f"{previous_block}"
        )),
    ]

    try:
        structured_coder = llm.with_structured_output(CodeFiles)
        result = await asyncio.wait_for(structured_coder.ainvoke(prompt), timeout=600.0)
        print("  [Structured] Код и тестовый сценарий получены.")
    except Exception as e:
        print(f"  ❌ [Coder] Ошибка: {e}")
        return {
            "iterations": state["iterations"] + 1,
            "feedback": f"FAIL: Ошибка генерации ({e})",
        }

    if len(result.js.strip()) < 50 or len(result.html.strip()) < 50:
        print("  ❌ [Coder] LLM вернула пустые файлы. Повторяю...")
        return {
            "iterations": state["iterations"] + 1,
            "feedback": "FAIL: Файлы пустые или обрезаны. Сгенерируй полноценный код.",
        }

    # Сохраняем файлы
    files = {"index.html": result.html, "style.css": result.css, "game.js": result.js}
    generated_content = ""
    for filename, content in files.items():
        filepath = os.path.join(folder_path, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [Файл] {filename} сохранен ({len(content)} символов).")
        generated_content += f"\n\n--- {filename} ---\n{content}"

    return {
        "iterations": state["iterations"] + 1,
        "feedback": "",
        "generated_code": generated_content,
        "test_sequence": result.test_sequence,  # Теперь это массив!
        "test_expected_key": result.test_expected_key.strip(),
    }


# ---------- Reviewer (детерминированный) ----------
def _balance_check(text: str, open_ch: str, close_ch: str) -> str:
    # (код проверки скобок остается прежним)
    depth = 0
    in_str = None
    in_line = False
    in_block = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_line:
            if ch == "\n": in_line = False
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_str:
            if ch == "\\": i += 1
            elif ch == in_str: in_str = None
        else:
            if ch == "/" and nxt == "/":
                in_line = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block = True
                i += 1
            elif ch in ("'", '"', "`"): in_str = ch
            elif ch == open_ch: depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth < 0: return f"лишняя закрывающая '{close_ch}'"
        i += 1
    if depth != 0: return f"дисбаланс '{open_ch}''{close_ch}': остаток {depth}"
    return ""


def _check_js_with_node(path: str) -> str | None:
    node = shutil.which("node")
    if not node: return None
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=30)
        if r.returncode != 0: return (r.stderr or r.stdout or "node --check failed")[:800]
        return ""
    except Exception:
        return None


async def reviewer_node(state: AgentState):
    print("\n🧐 [Reviewer] Детерминированная проверка синтаксиса...")
    folder = os.path.join("workspace", state["game_folder"])
    js_path = os.path.join(folder, "game.js")
    html_path = os.path.join(folder, "index.html")
    css_path = os.path.join(folder, "style.css")

    if not os.path.exists(js_path):
        return {"feedback": "FAIL: game.js не найден"}

    js = open(js_path, encoding="utf-8").read()
    html = open(html_path, encoding="utf-8").read() if os.path.exists(html_path) else ""
    css = open(css_path, encoding="utf-8").read() if os.path.exists(css_path) else ""

    for name, txt in [("game.js", js), ("index.html", html), ("style.css", css)]:
        t = txt.rstrip()
        if t and (t[-1].isalnum() or t[-1] in ".,+-*/=("):
            return {"feedback": f"FAIL: {name} обрезан. Последний символ: '{t[-1]}'."}

    if "window.game" not in js: return {"feedback": "FAIL: game.js не определяет window.game"}
    if "GAME_START" not in js: return {"feedback": "FAIL: game.js не содержит console.log('GAME_START')"}
    if "actions" not in js: return {"feedback": "FAIL: game.js не содержит счётчик actions."}

    for o, c in [("{", "}"), ("(", ")"), ("[", "]")]:
        err = _balance_check(js, o, c)
        if err: return {"feedback": f"FAIL: game.js — {err}"}

    node_err = _check_js_with_node(js_path)
    if node_err: return {"feedback": f"FAIL: node --check: {node_err}"}

    lower_html = html.lower()
    for tag in ("html", "head", "body", "script"):
        if lower_html.count(f"<{tag}") != lower_html.count(f"</{tag}>"):
            return {"feedback": f"FAIL: index.html — дисбаланс <{tag}>"}

    css_err = _balance_check(css, "{", "}")
    if css_err: return {"feedback": f"FAIL: style.css — {css_err}"}

    print("  ✅ PASS (синтаксис и обязательные требования)")
    return {"feedback": "PASS", "best_code": state["generated_code"]}


# ---------- Tester ----------

async def tester_node(state: AgentState):
    print("\n🎮 [Tester] Запускаю E2E-тестирование...")

    folder_path = os.path.join(os.getcwd(), "workspace", state["game_folder"])
    screenshot_path = os.path.join(folder_path, "screenshot.png")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=folder_path)
    httpd = socketserver.TCPServer(("", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    console_logs: list[str] = []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

                await page.goto(f"http://localhost:{port}/index.html", timeout=15000)
                await page.wait_for_timeout(500)

                logs_str = "\n".join(console_logs)
                if "[error]" in logs_str or "Uncaught" in logs_str:
                    return {"feedback": f"FAIL: JS-ошибки при загрузке. {logs_str[:400]}"}

                game_exists = await page.evaluate("() => typeof window.game !== 'undefined'")
                if not game_exists:
                    return {"feedback": "FAIL: window.game не инициализирован. Проверь конструктор Game()."}

                screenshot_before = await page.screenshot()
                initial_raw = await page.evaluate("() => JSON.stringify(window.game || {})")
                initial_data = json.loads(initial_raw or "{}")

                # 🔥 Выполняем МАССИВ действий, которые придумал Coder
                test_sequence = state.get("test_sequence", [])
                if not test_sequence:
                    return {"feedback": "FAIL: Coder вернул пустой test_sequence"}

                for action in test_sequence:
                    print(f"  [Tester] Выполняю: {action}")
                    await page.evaluate(
                        "() => { try { " + action + " } catch(e) { console.error('TestAction Error:', e); } }"
                    )
                    await page.wait_for_timeout(200)

                # Проверяем ошибки после выполнения всей последовательности
                logs_str = "\n".join(console_logs)
                if "[error]" in logs_str or "Uncaught" in logs_str:
                    return {"feedback": f"FAIL: JS-ошибки во время игры. {logs_str[:400]}"}

                after_raw = await page.evaluate("() => JSON.stringify(window.game || {})")
                after_data = json.loads(after_raw or "{}")

                expected_key = state.get("test_expected_key", "actions")
                before_val = initial_data.get(expected_key)
                after_val = after_data.get(expected_key)
                print(f"  [Tester] Изменение '{expected_key}': {before_val} -> {after_val}")

                if before_val == after_val:
                    return {"feedback": f"FAIL: действия не изменили '{expected_key}'."}

                screenshot_after = await page.screenshot()
                if screenshot_before == screenshot_after:
                    return {"feedback": "FAIL: состояние изменилось, но экран не обновился."}

                await page.screenshot(path=screenshot_path, full_page=False)
                print("  ✅ Состояние и визуал изменились.")
            finally:
                await browser.close()
    except Exception as e:
        return {"feedback": f"FAIL: Ошибка браузера ({e})"}
    finally:
        httpd.shutdown()
        thread.join(timeout=2)

    # Vision-проверка
    if os.path.exists(screenshot_path):
        print("  👁️ Анализирую скриншот через APInex (Gemini 3.8 Flash)...")
        try:
            with open(screenshot_path, "rb") as img_file:
                b64 = base64.b64encode(img_file.read()).decode("utf-8")

            vision = get_vision_llm()
            vision_prompt = [
                SystemMessage(content="Посмотри на скриншот игры. Если видна сетка, элементы и UI — ответь 'PASS'. Если пустой экран — 'FAIL: причина'."),
                HumanMessage(content=[
                    {"type": "text", "text": "Оцени скриншот."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]),
            ]
            vision_resp = await asyncio.wait_for(vision.ainvoke(vision_prompt), timeout=60.0)
            if "FAIL" in vision_resp.content.upper():
                return {"feedback": f"FAIL: Vision-проверка. {vision_resp.content[:300]}"}
            print("  ✅ Vision PASS.")
        except Exception as e:
            print(f"  [!] Vision-модель недоступна: {e}. Пропускаю.")

    print("  ✅ Головоломка прошла все проверки.")
    return {"feedback": "PASS"}


# ---------- Routes ----------

def route_review(state: AgentState) -> Literal["end", "tester", "coder"]:
    if "PASS" in state.get("feedback", ""): return "tester"
    if state["iterations"] >= 15: return "end"
    return "coder"


def route_tester(state: AgentState) -> Literal["end", "coder"]:
    if "PASS" in state.get("feedback", ""): return "end"
    if state["iterations"] >= 15: return "end"
    return "coder"


async def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("tester", tester_node)

    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "coder")
    workflow.add_edge("coder", "reviewer")
    workflow.add_conditional_edges("reviewer", route_review, {"coder": "coder", "tester": "tester", "end": END})
    workflow.add_conditional_edges("tester", route_tester, {"coder": "coder", "end": END})

    return workflow.compile()