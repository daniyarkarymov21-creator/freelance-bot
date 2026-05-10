#!/usr/bin/env python3
"""
freelance.ru → Telegram бот
Мониторит новые заказы, фильтрует по ключевым словам,
генерирует черновик отклика через Groq AI и шлёт в Telegram.
"""

import feedparser
import requests
import sqlite3
import time
import re
from datetime import datetime

# ─── НАСТРОЙКИ ────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN  = "8313581959:AAHeGEHYMA6LW_ao2B9V9DbmqyETEBosauY"
TELEGRAM_CHAT   = "8618412497"
GROQ_KEY        = "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"

# RSS-ленты freelance.ru (можно добавить несколько категорий)
RSS_FEEDS = [
    "https://freelance.ru/rss/projects.xml",                    # все заказы
    # "https://freelance.ru/rss/projects.xml?category=42",      # раскомментируй нужные
]

# Ключевые слова — заказ будет подхвачен если хотя бы одно совпадёт (без учёта регистра)
KEYWORDS = [
    # JavaScript / Node
    "javascript", "typescript", "node.js", "nodejs", "nest", "nestjs", "express",
    # Frontend
    "react", "next.js", "nextjs", "vue", "frontend", "фронтенд", "лендинг", "landing",
    # Python
    "python", "aiogram", "fastapi", "django",
    # Telegram
    "telegram", "бот", "bot", "aiogram",
    # AI
    "ai", "openai", "chatgpt", "gpt", "llm", "искусственный интеллект", "нейросеть",
    # Web3 / Crypto
    "web3", "solana", "блокчейн", "blockchain", "defi", "крипто", "crypto", "nft",
    # Backend / DB
    "postgresql", "postgres", "mongodb", "redis", "api", "backend", "бэкенд",
    # Общее
    "fullstack", "фуллстек", "full stack", "веб-приложение", "webapp", "saas",
    "автоматизация", "парсинг", "парсер",
]

# О твоём товарище — используется для генерации отклика
DEVELOPER_BIO = """
Меня зовут Дмитрий Бушин — fullstack-разработчик с 4+ годами опыта (известен как Trah1ch).
Создаю веб-приложения, Telegram-ботов, AI-интеграции и Web3-инструменты — от идеи до продакшена.

Стек:
- Backend: Node.js, NestJS, Express, Python, REST API, WebSockets
- Frontend: React, Next.js, TypeScript, Tailwind CSS
- Базы данных: PostgreSQL, MongoDB, Redis, SQLite
- Telegram-боты: Aiogram (Python), Node Telegram API — продакшен с тысячами пользователей
- AI: OpenAI, Ollama, Gemini, RAG-системы, интеграции LLM
- Web3: Solana, SPL-токены, кошельки, dApps

Последние проекты: LegalSifter (AI SaaS для юридических документов), Oryon.Finance (DeFi/RWA), 
Smetchik (enterprise Telegram-бот с RAG и PDF-генерацией), казино-бот, крипто-свап и др.
Портфолио: https://trah1ch.dev/ | GitHub: github.com/DiDeRMad
Telegram: @DmBusha | Открыт для удалёнки и фриланса.
"""

CHECK_INTERVAL  = 300   # секунд между проверками (5 минут)
DB_FILE         = "seen_jobs.db"

# ──────────────────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            id TEXT PRIMARY KEY,
            seen_at TEXT
        )
    """)
    conn.commit()
    return conn


def is_seen(conn, job_id: str) -> bool:
    return conn.execute("SELECT 1 FROM seen WHERE id=?", (job_id,)).fetchone() is not None


def mark_seen(conn, job_id: str):
    conn.execute("INSERT OR IGNORE INTO seen VALUES (?,?)", (job_id, datetime.now().isoformat()))
    conn.commit()


def matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def generate_cover_letter(title: str, description: str) -> str:
    """Генерирует черновик отклика через Groq API (бесплатно)."""
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 600,
                "messages": [
                    {
                        "role": "system",
                        "content": f"Ты помогаешь писать отклики на фриланс-заказы. Информация о разработчике:\n{DEVELOPER_BIO}"
                    },
                    {
                        "role": "user",
                        "content": f"""Напиши короткий (5-7 предложений) профессиональный отклик на фриланс-заказ.
Будь конкретным — упомяни детали из описания заказа.
Не используй шаблонные фразы вроде "готов взяться". Заканчивай предложением обсудить детали.

=== Заказ ===
Название: {title}
Описание: {description[:1000]}

Напиши только текст отклика, без заголовков и пояснений."""
                    }
                ]
            },
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[Не удалось сгенерировать отклик: {e}]"


def send_telegram(text: str):
    """Отправляет сообщение в Telegram (с разбивкой если > 4096 символов)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        resp.raise_for_status()
        time.sleep(0.5)


def process_feeds(conn):
    new_count = 0
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"[RSS] Ошибка: {e}")
            continue

        for entry in feed.entries:
            job_id = entry.get("id") or entry.get("link", "")
            if not job_id or is_seen(conn, job_id):
                continue

            title = entry.get("title", "Без названия")
            link  = entry.get("link", "")
            desc  = re.sub(r"<[^>]+>", "", entry.get("summary", ""))  # убираем HTML-теги

            if not matches_keywords(title + " " + desc):
                mark_seen(conn, job_id)  # запомним, чтоб не проверять снова
                continue

            print(f"[+] Новый заказ: {title}")

            # Генерируем отклик
            cover = generate_cover_letter(title, desc)

            # Формируем сообщение
            msg = (
                f"🆕 <b>Новый заказ на freelance.ru</b>\n\n"
                f"📌 <b>{title}</b>\n"
                f"🔗 {link}\n\n"
                f"📝 <b>Описание:</b>\n{desc[:600]}{'...' if len(desc) > 600 else ''}\n\n"
                f"─────────────────────\n"
                f"✍️ <b>Черновик отклика:</b>\n\n{cover}"
            )

            try:
                send_telegram(msg)
                print(f"    ✅ Отправлено в Telegram")
            except Exception as e:
                print(f"    ❌ Telegram ошибка: {e}")

            mark_seen(conn, job_id)
            new_count += 1
            time.sleep(1)  # пауза между заказами

    return new_count


def main():
    print("🤖 Freelance.ru бот запущен")
    print(f"   Ключевые слова: {', '.join(KEYWORDS)}")
    print(f"   Интервал: {CHECK_INTERVAL} сек\n")

    conn = init_db()

    # Тестовое сообщение при старте
    try:
        send_telegram("✅ <b>Freelance-бот запущен!</b>\nЖду новые заказы на freelance.ru...")
    except Exception as e:
        print(f"[!] Не удалось отправить тест в Telegram: {e}")
        print("    Проверь токен и Chat ID")

    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Проверяю RSS...")
        try:
            count = process_feeds(conn)
            print(f"    Новых подходящих заказов: {count}")
        except Exception as e:
            print(f"    Ошибка: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
