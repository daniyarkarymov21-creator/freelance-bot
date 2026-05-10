#!/usr/bin/env python3
"""
freelance.ru → Telegram бот
Мониторит новые заказы, фильтрует по категориям,
генерирует черновик отклика через Groq AI и шлёт в Telegram.
"""

import feedparser
import requests
import sqlite3
import time
import re
import json
from datetime import datetime

TELEGRAM_TOKEN  = "8313581959:AAHeGEHYMA6LW_ao2B9V9DbmqyETEBosauY"
TELEGRAM_CHAT   = "8618412497"
GROQ_KEY        = "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"

RSS_FEEDS = [
    "https://freelance.ru/rss/projects.xml",
]

CATEGORIES = [
    "веб-разработка",
    "продуктовый дизайн",
    "ит и разработка",
]

DEVELOPER_BIO = """
Меня зовут Дмитрий Бушин — fullstack-разработчик с 4+ годами опыта (известен как Trah1ch).
Создаю веб-приложения, Telegram-ботов, AI-интеграции и Web3-инструменты — от идеи до продакшена.
Стек: Node.js, NestJS, React, Next.js, TypeScript, Python, PostgreSQL, MongoDB, Redis, Aiogram, OpenAI, Solana.
Портфолио: https://trah1ch.dev/ | GitHub: github.com/DiDeRMad | Telegram: @DmBusha
"""

CHECK_INTERVAL = 300
DB_FILE        = "seen_jobs.db"
STATS_FILE     = "stats.json"

def load_stats():
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"total_jobs": 0, "total_responses": 0, "last_check": "", "jobs": []}

def save_stats(stats):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, seen_at TEXT)")
    conn.commit()
    return conn

def is_seen(conn, job_id):
    return conn.execute("SELECT 1 FROM seen WHERE id=?", (job_id,)).fetchone() is not None

def mark_seen(conn, job_id):
    conn.execute("INSERT OR IGNORE INTO seen VALUES (?,?)", (job_id, datetime.now().isoformat()))
    conn.commit()

def matches_category(text):
    t = text.lower()
    return any(c in t for c in CATEGORIES)

def generate_cover_letter(title, description):
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "max_tokens": 600,
                "messages": [
                    {"role": "system", "content": f"Ты помогаешь писать отклики на фриланс-заказы. Информация о разработчике:\n{DEVELOPER_BIO}"},
                    {"role": "user", "content": f"Напиши короткий (5-7 предложений) профессиональный отклик на заказ. Будь конкретным — упомяни детали из описания. Не используй шаблонные фразы. Заканчивай предложением обсудить детали.\n\nЗаказ: {title}\nОписание: {description[:1000]}\n\nНапиши только текст отклика."}
                ]
            },
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[Не удалось сгенерировать отклик: {e}]"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10).raise_for_status()
        time.sleep(0.5)

def process_feeds(conn, stats):
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
            desc  = re.sub(r"<[^>]+>", "", entry.get("summary", ""))

            if not matches_category(title + " " + desc):
                mark_seen(conn, job_id)
                continue

            print(f"[+] Новый заказ: {title}")
            cover = generate_cover_letter(title, desc)

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
                stats["total_responses"] += 1
            except Exception as e:
                print(f"    ❌ Telegram ошибка: {e}")

            stats["total_jobs"] += 1
            stats["jobs"].insert(0, {"title": title, "link": link, "time": datetime.now().strftime("%d.%m.%Y %H:%M"), "cover": cover[:200] + "..." if len(cover) > 200 else cover})
            stats["jobs"] = stats["jobs"][:50]
            save_stats(stats)
            mark_seen(conn, job_id)
            new_count += 1
            time.sleep(1)

    return new_count

def main():
    print("🤖 Freelance.ru бот запущен")
    print(f"   Категории: {', '.join(CATEGORIES)}")
    print(f"   Интервал: {CHECK_INTERVAL} сек\n")

    conn = init_db()
    stats = load_stats()

    try:
        send_telegram("✅ <b>Freelance-бот запущен!</b>\nЖду новые заказы на freelance.ru...")
    except Exception as e:
        print(f"[!] Не удалось отправить тест в Telegram: {e}")

    while True:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] Проверяю RSS...")
        stats["last_check"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        save_stats(stats)
        try:
            count = process_feeds(conn, stats)
            print(f"    Новых заказов: {count}")
        except Exception as e:
            print(f"    Ошибка: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
