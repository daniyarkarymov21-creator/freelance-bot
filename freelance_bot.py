#!/usr/bin/env python3
import requests
import sqlite3
import time
import json
from bs4 import BeautifulSoup
from datetime import datetime

TELEGRAM_TOKEN = "8313581959:AAHeGEHYMA6LW_ao2B9V9DbmqyETEBosauY"
TELEGRAM_CHAT  = "8618412497"
GROQ_KEY       = "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"

URLS = [
    "https://freelance.ru/project/search?q=&a=0&a=1&v=0&v=1&c=&c%5B%5D=116&c%5B%5D=4",
]

COOKIES = {
    "_ym_uid": "176313075684127283",
    "_ym_d": "1763130756",
    "_ga": "GA1.2.1009870395.1763130756",
    "__upin": "g8Drf+ZD5HIaawm6Ub9dVA",
    "ma_id_api": "U4MBCs5tNgMpQWpQOLHoUcfX4MBaENzBpAnuvdMeiVI88ONBGYWxh4a2x6py8u1EFSrnm2Ez/q2UFbHyRxhA6MFIFcyVXZq2aPp6poV1Al4NcT84H59jkvt5mTMnUTorbP0LfLooRby1DILyw/kHAsqUViaLjsK1acBpo4krMY4E5hfbihysjTKtkCN/C7tB8wx5TVq7AvwtK5vCc8aNmWUZ+rYQ5X9c3gO8BFOgQ8hQjE3TKcdd4GPlbseilgunThapslX9T27MfjDtTa812bM3PV/1HxkjuTIqLcaFw+b/CiS3oYxGSXh/UgvvIZBZ+XVjWSVmZf752Wpr0rGjBA==",
    "ma_id": "9719737151771604762534",
    "user_id": "H8BpTWm35kyX/AHECpg6Ag==",
    "__ddg9_": "89.204.89.218",
    "_ym_visorc": "w",
    "__ddg8_": "D18GVmQNpc7rOB1r",
    "__ddg10_": "1778406767",
}

DEVELOPER_BIO = """
Меня зовут Дмитрий Бушин — fullstack-разработчик с 4+ годами опыта (известен как Trah1ch).
Создаю веб-приложения, Telegram-ботов, AI-интеграции и Web3-инструменты — от идеи до продакшена.
Стек: Node.js, NestJS, React, Next.js, TypeScript, Python, PostgreSQL, MongoDB, Redis, Aiogram, OpenAI, Solana.
Портфолио: https://trah1ch.dev/ | GitHub: github.com/DiDeRMad | Telegram: @DmBusha
"""

CHECK_INTERVAL = 120
DB_FILE        = "seen_jobs.db"
STATS_FILE     = "stats.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://freelance.ru/",
}

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
                    {"role": "user", "content": f"Напиши короткий (5-7 предложений) профессиональный отклик. Будь конкретным. Не используй шаблонные фразы. Заканчивай предложением обсудить детали.\n\nЗаказ: {title}\nОписание: {description[:1000]}\n\nНапиши только текст отклика."}
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
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10).raise_for_status()
        time.sleep(0.5)

def scrape_page(url):
    jobs = []
    try:
        resp = requests.get(url, headers=HEADERS, cookies=COOKIES, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        print(f"    Страница: {soup.title.string if soup.title else 'нет заголовка'}")

        items = (soup.select("div.b-post") or
                 soup.select("article.project") or
                 soup.select(".task-item") or
                 soup.select(".project"))
        print(f"    Блоков найдено: {len(items)}")

        for item in items:
            title_tag = (item.select_one("h2 a") or item.select_one("h3 a") or
                        item.select_one(".title a") or item.select_one("a.b-post__title"))
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link  = title_tag.get("href", "")
            if link and not link.startswith("http"):
                link = "https://freelance.ru" + link
            desc_tag = (item.select_one(".b-post__body") or item.select_one(".description") or item.select_one("p"))
            desc = desc_tag.get_text(strip=True) if desc_tag else ""
            budget_tag = item.select_one(".b-post__price") or item.select_one(".price")
            budget = budget_tag.get_text(strip=True) if budget_tag else ""
            jobs.append({"id": link, "title": title, "link": link, "desc": desc, "budget": budget})
    except Exception as e:
        print(f"[!] Ошибка: {e}")
    return jobs

def process_all(conn, stats):
    new_count = 0
    for url in URLS:
        print(f"  Парсю: {url}")
        jobs = scrape_page(url)
        for job in jobs:
            if is_seen(conn, job["id"]):
                continue
            print(f"[+] Новый: {job['title']}")
            cover = generate_cover_letter(job["title"], job["desc"])
            budget_str = f"\n💰 <b>Бюджет:</b> {job['budget']}" if job["budget"] else ""
            msg = (
                f"🆕 <b>Новый заказ на freelance.ru</b>\n\n"
                f"📌 <b>{job['title']}</b>\n"
                f"🔗 {job['link']}{budget_str}\n\n"
                f"📝 <b>Описание:</b>\n{job['desc'][:600]}{'...' if len(job['desc']) > 600 else ''}\n\n"
                f"─────────────────────\n"
                f"✍️ <b>Черновик отклика:</b>\n\n{cover}"
            )
            try:
                send_telegram(msg)
                print(f"    ✅ Отправлено")
                stats["total_responses"] += 1
            except Exception as e:
                print(f"    ❌ Ошибка: {e}")
            stats["total_jobs"] += 1
            stats["jobs"].insert(0, {"title": job["title"], "link": job["link"], "time": datetime.now().strftime("%d.%m.%Y %H:%M"), "cover": cover[:200]})
            stats["jobs"] = stats["jobs"][:50]
            save_stats(stats)
            mark_seen(conn, job["id"])
            new_count += 1
            time.sleep(2)
    return new_count

def main():
    print("🤖 Freelance.ru бот запущен")
    conn = init_db()
    stats = load_stats()
    try:
        send_telegram("✅ <b>Бот перезапущен!</b> Парсю заказы каждые 2 минуты...")
    except Exception as e:
        print(f"[!] Telegram: {e}")
    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Проверяю...")
        stats["last_check"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        save_stats(stats)
        try:
            count = process_all(conn, stats)
            print(f"    Новых: {count}")
        except Exception as e:
            print(f"    Ошибка: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
