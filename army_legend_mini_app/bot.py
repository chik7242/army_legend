import os, json, hmac, hashlib, sqlite3, secrets, time, asyncio
from urllib.parse import parse_qsl
from contextlib import closing
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, PreCheckoutQuery, LabeledPrice
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
import secrets as pysecrets

load_dotenv()
BOT_TOKEN=os.getenv("BOT_TOKEN","")
WEBAPP_URL=os.getenv("WEBAPP_URL","https://YOUR-FRONTEND.vercel.app")
BOT_USERNAME=os.getenv("BOT_USERNAME","")
SUPPORT_USERNAME=os.getenv("SUPPORT_USERNAME","YOUR_SUPPORT")
DB_PATH=os.getenv("DB_PATH","store.db")
ADMIN_USERNAME=os.getenv("ADMIN_USERNAME","admin")
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","CHANGE_THIS_PASSWORD")
FRONTEND_ORIGIN=os.getenv("FRONTEND_ORIGIN","*")
if not BOT_TOKEN: raise RuntimeError("Укажите BOT_TOKEN в .env")
if ADMIN_PASSWORD=="CHANGE_THIS_PASSWORD":
    print("WARNING: смените ADMIN_PASSWORD в .env перед публикацией!")

bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp=Dispatcher()
api=FastAPI(title="ARMY LEGEND Store API")
security=HTTPBasic()
api.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in FRONTEND_ORIGIN.split(",")],
                   allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["*"])

# Цены указаны в Telegram Stars (XTR), не в рублях.
PRODUCTS={
 "cry4me":{"name":"CRY4ME","plans":[("1 День",200),("7 Дней",750),("30 Дней",2100),("Навсегда",7500)]},
 "jarvis":{"name":"JARVIS","plans":[("1 День",210),("7 Дней",790),("30 Дней",2200),("Навсегда",7900)]},
 "deadnight":{"name":"DeadNight","plans":[("1 День",150),("7 Дней",550),("30 Дней",1500),("Навсегда",5900)]},
 "ios-pack":{"name":"iPhone CHEAT","plans":[("1 День",250),("7 Дней",900),("30 Дней",2500),("Навсегда",8500)]},
 "android-pack":{"name":"ANDROID CHEAT","plans":[("1 День",150),("7 Дней",600),("30 Дней",1700),("Навсегда",6500)]},
}

def db():
    c=sqlite3.connect(DB_PATH,timeout=30)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with closing(db()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS orders(
          id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,product_id TEXT NOT NULL,
          product TEXT NOT NULL,plan TEXT NOT NULL,price INTEGER NOT NULL,
          payload TEXT UNIQUE NOT NULL,status TEXT NOT NULL,created_at INTEGER NOT NULL,
          delivered_at INTEGER,telegram_charge_id TEXT);
        CREATE TABLE IF NOT EXISTS inventory(
          id INTEGER PRIMARY KEY AUTOINCREMENT,product_id TEXT NOT NULL,
          key_value TEXT NOT NULL UNIQUE,status TEXT NOT NULL DEFAULT 'available',
          order_id TEXT UNIQUE,created_at INTEGER NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id));
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status,created_at);
        CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id,status);
        """)
        # Upgrade an older database created by the previous project version.
        cols={r["name"] for r in c.execute("PRAGMA table_info(orders)").fetchall()}
        for col,definition in [("delivered_at","INTEGER"),("telegram_charge_id","TEXT")]:
            if col not in cols: c.execute(f"ALTER TABLE orders ADD COLUMN {col} {definition}")
        c.commit()

def validate_init_data(init_data:str):
    if not init_data: raise HTTPException(401,"Нет Telegram initData")
    values=dict(parse_qsl(init_data,keep_blank_values=True))
    received=values.pop("hash",None)
    if not received: raise HTTPException(401,"Некорректные Telegram данные")
    check="\n".join(f"{k}={v}" for k,v in sorted(values.items()))
    secret=hmac.new(b"WebAppData",BOT_TOKEN.encode(),hashlib.sha256).digest()
    calc=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc,received): raise HTTPException(401,"Подпись Telegram не прошла проверку")
    try:
        if time.time()-int(values.get("auth_date","0"))>86400: raise HTTPException(401,"Данные устарели. Перезапустите Mini App.")
        return json.loads(values["user"])
    except (ValueError,KeyError,json.JSONDecodeError): raise HTTPException(401,"Не удалось прочитать Telegram пользователя")

def admin_user(creds:HTTPBasicCredentials=Depends(security)):
    ok_user=pysecrets.compare_digest(creds.username,ADMIN_USERNAME)
    ok_pass=pysecrets.compare_digest(creds.password,ADMIN_PASSWORD)
    if not (ok_user and ok_pass): raise HTTPException(401,"Неверный логин или пароль",headers={"WWW-Authenticate":"Basic"})
    return creds.username

def reserve_key_for_order(conn, order):
    """Caller holds a write transaction. Returns key text or None."""
    item=conn.execute("SELECT id,key_value FROM inventory WHERE product_id=? AND status='available' ORDER BY id LIMIT 1",(order["product_id"],)).fetchone()
    if not item: return None
    changed=conn.execute("UPDATE inventory SET status='assigned',order_id=? WHERE id=? AND status='available'",(order["id"],item["id"])).rowcount
    if changed!=1: return None
    conn.execute("UPDATE orders SET status='delivered',delivered_at=? WHERE id=?",(int(time.time()),order["id"]))
    return item["key_value"]

async def deliver_waiting_orders(product_id=None):
    """After restocking, deliver paid orders in FIFO order."""
    deliveries=[]
    with closing(db()) as c:
        c.execute("BEGIN IMMEDIATE")
        query="SELECT * FROM orders WHERE status='paid_waiting_stock'"
        args=[]
        if product_id:
            query+=" AND product_id=?";args.append(product_id)
        query+=" ORDER BY created_at,id"
        rows=c.execute(query,args).fetchall()
        for order in rows:
            key=reserve_key_for_order(c,order)
            if key is not None: deliveries.append((order["user_id"],order["id"],order["product"],order["plan"],key))
        c.commit()
    for uid,oid,product,plan,key in deliveries:
        try:
            await bot.send_message(uid,
                f"✅ <b>Ваш заказ готов!</b>\n\nЗаказ: <code>{oid}</code>\n"
                f"Товар: <b>{product} — {plan}</b>\n\n"
                f"Ваш ключ:\n<code>{key}</code>\n\nСохраните его в надёжном месте.")
        except Exception as e:
            # The key remains assigned; admin can see the delivered state and resend manually.
            print(f"Could not notify user {uid} for {oid}: {e}")

class InvoiceRequest(BaseModel):
    initData:str
    productId:str
    planIndex:int
class InitRequest(BaseModel):
    initData:str
class KeyUpload(BaseModel):
    product_id:str
    keys:list[str]

@api.get("/health")
async def health(): return {"ok":True,"service":"army-legend"}

@api.post("/api/create-invoice")
async def create_invoice(req:InvoiceRequest):
    user=validate_init_data(req.initData)
    product=PRODUCTS.get(req.productId)
    if not product or req.planIndex<0 or req.planIndex>=len(product["plans"]): raise HTTPException(404,"Товар или тариф не найден")
    plan,price=product["plans"][req.planIndex]
    order_id="AL-"+secrets.token_hex(4).upper()
    payload=f"{order_id}:{user['id']}:{req.productId}:{req.planIndex}"
    with closing(db()) as c:
        c.execute("INSERT INTO orders(id,user_id,product_id,product,plan,price,payload,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (order_id,user["id"],req.productId,product["name"],plan,price,payload,"pending",int(time.time())))
        c.commit()
    try:
        link=await bot.create_invoice_link(title=f"{product['name']} — {plan}",description=f"Цифровой товар ARMY LEGEND. Заказ {order_id}",
            payload=payload,provider_token="",currency="XTR",prices=[LabeledPrice(label=f"{product['name']} / {plan}",amount=price)])
        return {"invoice_url":link,"order_id":order_id}
    except Exception as e:
        with closing(db()) as c:
            c.execute("UPDATE orders SET status='invoice_error' WHERE id=?",(order_id,));c.commit()
        raise HTTPException(502,f"Не удалось создать счёт: {str(e)}")

@api.post("/api/my-orders")
async def my_orders(req:InitRequest):
    user=validate_init_data(req.initData)
    with closing(db()) as c:
        rows=c.execute("SELECT id,product,plan,price,status,created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 30",(user["id"],)).fetchall()
    return {"orders":[dict(r) for r in rows]}

@api.post("/api/order-status")
async def order_status(req:InitRequest, order_id:str):
    user=validate_init_data(req.initData)
    with closing(db()) as c:
        row=c.execute("SELECT id,status FROM orders WHERE id=? AND user_id=?",(order_id,user["id"])).fetchone()
    if not row: raise HTTPException(404,"Заказ не найден")
    return dict(row)

@api.get("/admin",response_class=HTMLResponse)
async def admin_page(_=Depends(admin_user)):
    path=os.path.join(os.path.dirname(__file__),"admin.html")
    try:
        with open(path,encoding="utf-8") as f: return f.read()
    except FileNotFoundError: raise HTTPException(500,"Файл admin.html отсутствует")

@api.get("/admin/api/summary")
async def admin_summary(_=Depends(admin_user)):
    with closing(db()) as c:
        total=c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
        paid=c.execute("SELECT COUNT(*) n FROM orders WHERE status IN ('delivered','paid_waiting_stock')").fetchone()["n"]
        waiting=c.execute("SELECT COUNT(*) n FROM orders WHERE status='paid_waiting_stock'").fetchone()["n"]
        available=c.execute("SELECT COUNT(*) n FROM inventory WHERE status='available'").fetchone()["n"]
        sold=c.execute("SELECT COUNT(*) n FROM inventory WHERE status='assigned'").fetchone()["n"]
        revenue=c.execute("SELECT COALESCE(SUM(price),0) n FROM orders WHERE status IN ('delivered','paid_waiting_stock')").fetchone()["n"]
        stock=c.execute("SELECT product_id,COUNT(*) quantity FROM inventory WHERE status='available' GROUP BY product_id").fetchall()
        orders=c.execute("SELECT id,user_id,product_id,product,plan,price,status,created_at FROM orders ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"stats":{"orders":total,"paid":paid,"waiting":waiting,"available":available,"sold":sold,"revenue_stars":revenue},
            "stock":[dict(x) for x in stock],"orders":[dict(x) for x in orders]}

@api.post("/admin/api/keys")
async def upload_keys(data:KeyUpload,_=Depends(admin_user)):
    if data.product_id not in PRODUCTS: raise HTTPException(400,"Неизвестный product_id")
    clean=list(dict.fromkeys(x.strip() for x in data.keys if x.strip()))
    if not clean: raise HTTPException(400,"Вставьте хотя бы один ключ")
    inserted=0;duplicates=0
    with closing(db()) as c:
        c.execute("BEGIN IMMEDIATE")
        for key in clean:
            try:
                c.execute("INSERT INTO inventory(product_id,key_value,status,created_at) VALUES(?,?,?,?)",
                          (data.product_id,key,"available",int(time.time())))
                inserted+=1
            except sqlite3.IntegrityError: duplicates+=1
        c.commit()
    await deliver_waiting_orders(data.product_id)
    return {"inserted":inserted,"duplicates":duplicates,"received":len(clean)}

@api.get("/admin/api/products")
async def admin_products(_=Depends(admin_user)):
    return {"products":[{"id":k,"name":v["name"]} for k,v in PRODUCTS.items()]}

@dp.message(CommandStart())
async def start(message:Message):
    kb=InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="🛒 Открыть ARMY LEGEND",web_app=WebAppInfo(url=WEBAPP_URL))],
      [InlineKeyboardButton(text="🆘 Поддержка",url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}")]])
    await message.answer("⚔️ <b>ДОБРО ПОЖАЛОВАТЬ В ARMY LEGEND!</b>\n\n"
        "🎮 Цифровые товары и подписки.\n⚡ Быстрая выдача при наличии товара.\n"
        "⭐ Оплата цифровых товаров — Telegram Stars.\n\nНажимай кнопку ниже, чтобы открыть магазин.",reply_markup=kb)

@dp.pre_checkout_query()
async def pre_checkout(query:PreCheckoutQuery):
    with closing(db()) as c:
        row=c.execute("SELECT user_id,price,status FROM orders WHERE payload=?",(query.invoice_payload,)).fetchone()
    if not row or row["status"]!="pending" or row["user_id"]!=query.from_user.id or row["price"]!=query.total_amount:
        await query.answer(ok=False,error_message="Заказ не найден или данные счёта не совпадают.")
    else: await query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message:Message):
    payment=message.successful_payment
    deliveries=[]
    with closing(db()) as c:
        c.execute("BEGIN IMMEDIATE")
        order=c.execute("SELECT * FROM orders WHERE payload=?",(payment.invoice_payload,)).fetchone()
        if not order or order["user_id"]!=message.from_user.id or order["price"]!=payment.total_amount:
            c.rollback()
            await message.answer("Платёж получен, но заказ требует ручной проверки. Напишите в поддержку.")
            return
        if order["status"] in ("delivered","paid_waiting_stock"):
            c.commit()
            await message.answer(f"Этот платёж уже обработан. Номер заказа: <code>{order['id']}</code>")
            return
        c.execute("UPDATE orders SET status='paid_waiting_stock',telegram_charge_id=? WHERE id=?",
                  (payment.telegram_payment_charge_id,order["id"]))
        order=c.execute("SELECT * FROM orders WHERE id=?",(order["id"],)).fetchone()
        key=reserve_key_for_order(c,order)
        if key is not None:
            deliveries.append((order["id"],order["product"],order["plan"],key))
        c.commit()
    if deliveries:
        oid,product,plan,key=deliveries[0]
        await message.answer(f"✅ <b>Оплата подтверждена!</b>\n\nЗаказ: <code>{oid}</code>\n"
            f"Товар: <b>{product} — {plan}</b>\n\nВаш ключ:\n<code>{key}</code>\n\nСохраните его в надёжном месте.")
    else:
        await message.answer(f"✅ Оплата подтверждена. Заказ <code>{order['id']}</code> принят.\n"
            "Сейчас товар закончился. Мы уведомим вас автоматически, как только ключ появится на складе.")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    import uvicorn
    config=uvicorn.Config(api,host="0.0.0.0",port=int(os.getenv("PORT","8000")),log_level="info")
    await asyncio.gather(dp.start_polling(bot),uvicorn.Server(config).serve())

if __name__=="__main__": asyncio.run(main())
