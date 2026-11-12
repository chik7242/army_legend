import os, json, time, hmac, hashlib, secrets, asyncio, logging, sqlite3
from pathlib import Path
from urllib.parse import parse_qsl
from contextlib import asynccontextmanager
from typing import Optional
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, LabeledPrice
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
import uvicorn

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("army-legend")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
APP_URL = os.getenv("APP_URL", "").strip().rstrip("/")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
DB_PATH = os.getenv("DB_PATH", "store.db")
PORT = int(os.getenv("PORT", "10000"))
MAX_INIT_AGE = int(os.getenv("INIT_DATA_MAX_AGE", "86400"))
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it in Render Environment.")
if not ADMIN_PASSWORD or ADMIN_PASSWORD.lower() in {"admin", "password", "changeme", "replace_me"}:
    raise RuntimeError("Set a strong ADMIN_PASSWORD in Render Environment.")
if not APP_URL.startswith("https://"):
    log.warning("APP_URL must be an HTTPS URL for Telegram Mini App.")

bot, dp, basic = Bot(BOT_TOKEN), Dispatcher(), HTTPBasic()

def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init_db():
    Path(DB_PATH).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Другое', description TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL, image_url TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), secret TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'available', order_id INTEGER);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, username TEXT DEFAULT '', product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT NOT NULL, price INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', invoice_payload TEXT UNIQUE NOT NULL, charge_id TEXT, inventory_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, paid_at TEXT);
        CREATE INDEX IF NOT EXISTS inv_lookup ON inventory(product_id,status);
        CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id,id);
        """)
        c.commit()

def telegram_user(raw):
    if not raw: raise HTTPException(401, "Откройте магазин через Telegram")
    try:
        data = dict(parse_qsl(raw, keep_blank_values=True))
        received = data.pop("hash")
        auth_date = int(data.get("auth_date", "0"))
        user = json.loads(data["user"])
    except Exception:
        raise HTTPException(401, "Некорректные данные Telegram")
    if abs(int(time.time()) - auth_date) > MAX_INIT_AGE:
        raise HTTPException(401, "Сессия устарела. Перезапустите Mini App.")
    check = "\n".join(f"{k}={v}" for k,v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(401, "Проверка Telegram не пройдена")
    return {"id": int(user["id"]), "username": user.get("username",""), "first_name": user.get("first_name","")}

async def current_user(x_telegram_init_data: Optional[str] = Header(default=None)):
    return telegram_user(x_telegram_init_data or "")

def admin(credentials: HTTPBasicCredentials = Depends(basic)):
    if not (secrets.compare_digest(credentials.username, ADMIN_USERNAME) and secrets.compare_digest(credentials.password, ADMIN_PASSWORD)):
        raise HTTPException(401, "Неверный логин или пароль", headers={"WWW-Authenticate":"Basic"})
    return credentials.username

@dp.message(CommandStart())
async def start(m: Message):
    if APP_URL.startswith("https://"):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛍 Открыть ARMY LEGEND", web_app=WebAppInfo(url=APP_URL))]])
        await m.answer("Добро пожаловать в ARMY LEGEND!\n\nЦифровые товары, оплата Telegram Stars и автоматическая выдача.", reply_markup=kb)
    else:
        await m.answer("Магазин настраивается. Попробуйте позже.")

@dp.pre_checkout_query()
async def checkout(q: PreCheckoutQuery):
    try:
        oid = int(q.invoice_payload.split(":")[-1])
        with db() as c: o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        ok = bool(o and o["status"] == "pending" and o["user_id"] == q.from_user.id and o["price"] == q.total_amount and q.currency == "XTR")
        await q.answer(ok=ok, error_message=None if ok else "Заказ недействителен. Создайте новый.")
    except Exception:
        log.exception("pre-checkout error")
        await q.answer(ok=False, error_message="Не удалось проверить заказ")

def fulfill(oid, charge):
    with db() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o: return None
        if o["status"] == "delivered": return {"user_id":o["user_id"],"already":True}
        item = c.execute("SELECT * FROM inventory WHERE product_id=? AND status='available' ORDER BY id LIMIT 1", (o["product_id"],)).fetchone()
        if not item:
            c.execute("UPDATE orders SET status='paid_waiting_stock',charge_id=?,paid_at=CURRENT_TIMESTAMP WHERE id=?", (charge,oid))
            c.commit()
            return {"user_id":o["user_id"],"waiting":True}
        c.execute("UPDATE inventory SET status='assigned',order_id=? WHERE id=?", (oid,item["id"]))
        c.execute("UPDATE orders SET status='delivered',charge_id=?,inventory_id=?,paid_at=CURRENT_TIMESTAMP WHERE id=?", (charge,item["id"],oid))
        c.commit()
        return {"user_id":o["user_id"],"secret":item["secret"],"product":o["product_name"]}

@dp.message(F.successful_payment)
async def paid(m: Message):
    try:
        p = m.successful_payment
        oid = int(p.invoice_payload.split(":")[-1])
        r = fulfill(oid,p.telegram_payment_charge_id)
        if r and r.get("secret"):
            await m.answer(f"✅ Оплата получена!\nТовар: {r['product']}\n\nВаш ключ:\n<code>{r['secret']}</code>",parse_mode="HTML")
        elif r and r.get("waiting"):
            await m.answer("Оплата получена, но товар временно закончился. Обратитесь в поддержку.")
        elif r:
            await m.answer("Этот заказ уже обработан.")
        else:
            await m.answer("Оплата получена. Заказ не найден — обратитесь в поддержку.")
    except Exception:
        log.exception("delivery error")
        await m.answer("Оплата получена, но автоматическая выдача не удалась. Обратитесь в поддержку.")

class Product(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    category: str = Field(default="Другое",max_length=80)
    description: str = Field(default="",max_length=2000)
    price: int = Field(ge=1,le=1000000)
    image_url: str = Field(default="",max_length=1000)
    active: bool = True

class Stock(BaseModel):
    product_id: int
    keys: list[str] = Field(min_length=1,max_length=500)

@asynccontextmanager
async def lifespan(app):
    init_db()
    task = asyncio.create_task(dp.start_polling(bot,handle_signals=False,close_bot_session=False))
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    await bot.session.close()

api = FastAPI(title="ARMY LEGEND",lifespan=lifespan)
api.mount("/static",StaticFiles(directory=str(STATIC)),name="static")

@api.get("/")
async def home(): return FileResponse(STATIC/"index.html")
@api.get("/health")
async def health(): return {"ok":True,"service":"army-legend"}
@api.get("/admin")
async def admin_page(_=Depends(admin)): return FileResponse(STATIC/"admin.html")

@api.get("/api/bootstrap")
async def bootstrap(u=Depends(current_user)):
    with db() as c:
        ps=c.execute("SELECT p.*,(SELECT COUNT(*) FROM inventory i WHERE i.product_id=p.id AND i.status='available') stock FROM products p WHERE active=1 ORDER BY category,id DESC").fetchall()
        os_=c.execute("SELECT id,product_name,price,status,created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20",(u["id"],)).fetchall()
    return {"user":u,"products":[dict(x) for x in ps],"orders":[dict(x) for x in os_],"support":SUPPORT_USERNAME}

@api.post("/api/orders")
async def new_order(product_id:int,u=Depends(current_user)):
    with db() as c:
        p=c.execute("SELECT * FROM products WHERE id=? AND active=1",(product_id,)).fetchone()
        if not p: raise HTTPException(404,"Товар не найден")
        stock=c.execute("SELECT COUNT(*) n FROM inventory WHERE product_id=? AND status='available'",(product_id,)).fetchone()["n"]
        if stock<1: raise HTTPException(409,"Товар закончился")
        cur=c.execute("INSERT INTO orders(user_id,username,product_id,product_name,price,invoice_payload) VALUES(?,?,?,?,?,?)",(u["id"],u["username"],product_id,p["name"],p["price"],"pending-"+secrets.token_hex(8)))
        oid=cur.lastrowid
        payload=f"al:{oid}"
        c.execute("UPDATE orders SET invoice_payload=? WHERE id=?",(payload,oid)); c.commit()
    try:
        url=await bot.create_invoice_link(title=p["name"][:32],description=(p["description"] or "Цифровой товар ARMY LEGEND")[:255],payload=payload,provider_token="",currency="XTR",prices=[LabeledPrice(label=p["name"][:32],amount=p["price"])])
    except Exception:
        log.exception("invoice creation failed")
        with db() as c: c.execute("UPDATE orders SET status='invoice_error' WHERE id=?",(oid,)); c.commit()
        raise HTTPException(502,"Не удалось создать счёт Telegram Stars")
    return {"order_id":oid,"invoice_url":url}

@api.get("/admin/api/summary")
async def summary(_=Depends(admin)):
    with db() as c:
        stats={"products":c.execute("SELECT COUNT(*) n FROM products").fetchone()["n"],"orders":c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"],"paid":c.execute("SELECT COUNT(*) n FROM orders WHERE status IN ('delivered','paid_waiting_stock')").fetchone()["n"],"stock":c.execute("SELECT COUNT(*) n FROM inventory WHERE status='available'").fetchone()["n"],"revenue":c.execute("SELECT COALESCE(SUM(price),0) n FROM orders WHERE status IN ('delivered','paid_waiting_stock')").fetchone()["n"]}
        orders=c.execute("SELECT id,user_id,product_name,price,status,created_at FROM orders ORDER BY id DESC LIMIT 100").fetchall()
    return {"stats":stats,"orders":[dict(x) for x in orders]}

@api.get("/admin/api/products")
async def products_admin(_=Depends(admin)):
    with db() as c: rows=c.execute("SELECT p.*,(SELECT COUNT(*) FROM inventory i WHERE i.product_id=p.id AND i.status='available') stock FROM products p ORDER BY id DESC").fetchall()
    return {"products":[dict(x) for x in rows]}

@api.post("/admin/api/products")
async def add_product(p:Product,_=Depends(admin)):
    with db() as c:
        cur=c.execute("INSERT INTO products(name,category,description,price,image_url,active) VALUES(?,?,?,?,?,?)",(p.name,p.category,p.description,p.price,p.image_url,int(p.active))); c.commit()
    return {"ok":True,"id":cur.lastrowid}

@api.put("/admin/api/products/{pid}")
async def edit_product(pid:int,p:Product,_=Depends(admin)):
    with db() as c:
        cur=c.execute("UPDATE products SET name=?,category=?,description=?,price=?,image_url=?,active=? WHERE id=?",(p.name,p.category,p.description,p.price,p.image_url,int(p.active),pid)); c.commit()
        if not cur.rowcount: raise HTTPException(404,"Товар не найден")
    return {"ok":True}

@api.delete("/admin/api/products/{pid}")
async def remove_product(pid:int,_=Depends(admin)):
    with db() as c:
        used=c.execute("SELECT COUNT(*) n FROM orders WHERE product_id=?",(pid,)).fetchone()["n"]
        if used: c.execute("UPDATE products SET active=0 WHERE id=?",(pid,))
        else: c.execute("DELETE FROM products WHERE id=?",(pid,))
        c.commit()
    return {"ok":True}

@api.post("/admin/api/stock")
async def add_stock(s:Stock,_=Depends(admin)):
    keys=[x.strip() for x in s.keys if x.strip()]
    if not keys: raise HTTPException(400,"Введите ключи")
    with db() as c:
        if not c.execute("SELECT id FROM products WHERE id=?",(s.product_id,)).fetchone(): raise HTTPException(404,"Товар не найден")
        c.executemany("INSERT INTO inventory(product_id,secret) VALUES(?,?)",[(s.product_id,k) for k in keys]); c.commit()
    return {"ok":True,"added":len(keys)}

if __name__=="__main__": uvicorn.run(api,host="0.0.0.0",port=PORT,log_level="info")
