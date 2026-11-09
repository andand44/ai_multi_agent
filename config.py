import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

load_dotenv()

APINEX_BOND_KEY = os.getenv("APINEX_BOND_KEY")


def get_llm(temperature=0, max_tokens=16000):
    """Для Planner и Coder (текстовые, крупные ответы)."""
    primary = ChatOpenAI(
        base_url="https://api.apinex.bond/v1",
        api_key=APINEX_BOND_KEY,
        model="free/deepseek-v4.1-flash",
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=600,
        max_retries=2,
    )
    fallback = ChatOllama(
        model="qwen2.5-coder:3b",
        temperature=temperature,
        timeout=600,
    )
    return primary.with_fallbacks([fallback])


def get_vision_llm(temperature=0):
    """Для анализа скриншотов в Tester'е."""
    return ChatOpenAI(
        base_url="https://api.apinex.bond/v1",
        api_key=APINEX_BOND_KEY,
        model="free/gemini-3.8-flash",
        temperature=temperature,
        max_tokens=1000,
        timeout=120,
    )