import os
import hmac
import hashlib
import secrets
import sqlite3
import time
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

load_dotenv()

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_USERNAME = os.getenv("BOT_USERNAME")

WAYFORPAY_MERCHANT = os.getenv("WAYFORPAY_MERCHANT")
WAYFORPAY_SECRET = os.getenv("WAYFORPAY_SECRET")

COURSE_PRICE = os.getenv("COURSE_PRICE", "500")
COURSE_CURRENCY = os.getenv("COURSE_CURRENCY", "UAH")

PUBLIC_URL = os.getenv("PUBLIC_URL")

DB_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "course.db"
)

WAYFORPAY_URL = "https://secure.wayforpay.com/pay"


# ============================================================
# ПРОВЕРКА НАСТРОЕК
# ============================================================

required_settings = {
    "BOT_USERNAME": BOT_USERNAME,
    "WAYFORPAY_MERCHANT": WAYFORPAY_MERCHANT,
    "WAYFORPAY_SECRET": WAYFORPAY_SECRET,
    "PUBLIC_URL": PUBLIC_URL,
}

for name, value in required_settings.items():
    if not value:
        raise ValueError(
            f"Не найдена настройка {name}. "
            f"Проверь файл .env"
        )


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Telegram Course Server"
)


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            order_reference TEXT UNIQUE NOT NULL,

            amount TEXT NOT NULL,

            currency TEXT NOT NULL,

            email TEXT,

            access_code TEXT UNIQUE,

            payment_status TEXT DEFAULT 'pending',

            telegram_id INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            paid_at TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# HELPERS
# ============================================================

def generate_order_reference():
    """
    Создаёт уникальный номер заказа.
    """

    timestamp = int(time.time())

    random_part = secrets.token_hex(5).upper()

    return f"COURSE-{timestamp}-{random_part}"


def generate_access_code():
    """
    Создаёт уникальный код доступа.
    """

    return secrets.token_urlsafe(18)


def create_hmac_md5(message: str):
    """
    HMAC-MD5 по SecretKey WayForPay.
    """

    return hmac.new(
        WAYFORPAY_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.md5
    ).hexdigest()


# ============================================================
# WAYFORPAY REQUEST SIGNATURE
# ============================================================

def create_payment_signature(
    merchant_account,
    merchant_domain,
    order_reference,
    order_date,
    amount,
    currency,
    product_name,
    product_count,
    product_price
):
    """
    Подпись запроса на оплату.

    WayForPay требует строку:

    merchantAccount;
    merchantDomainName;
    orderReference;
    orderDate;
    amount;
    currency;
    productName[];
    productCount[];
    productPrice[]
    """

    parts = [
        merchant_account,
        merchant_domain,
        order_reference,
        str(order_date),
        str(amount),
        currency,
    ]

    # productName[]
    parts.extend(product_name)

    # productCount[]
    parts.extend(str(x) for x in product_count)

    # productPrice[]
    parts.extend(str(x) for x in product_price)

    message = ";".join(parts)

    return create_hmac_md5(message)


# ============================================================
# WAYFORPAY CALLBACK SIGNATURE
# ============================================================

def create_callback_signature(data: dict):
    """
    Подпись уведомления от WayForPay.

    merchantAccount;
    orderReference;
    amount;
    currency;
    authCode;
    cardPan;
    transactionStatus;
    reasonCode
    """

    parts = [
        str(data.get("merchantAccount", "")),
        str(data.get("orderReference", "")),
        str(data.get("amount", "")),
        str(data.get("currency", "")),
        str(data.get("authCode", "")),
        str(data.get("cardPan", "")),
        str(data.get("transactionStatus", "")),
        str(data.get("reasonCode", "")),
    ]

    message = ";".join(parts)

    return create_hmac_md5(message)


def verify_wayforpay_signature(data: dict):
    received_signature = str(
        data.get("merchantSignature", "")
    ).lower()

    expected_signature = create_callback_signature(data)

    return hmac.compare_digest(
        received_signature,
        expected_signature
    )


# ============================================================
# CREATE PAYMENT
# ============================================================

@app.get("/buy", response_class=HTMLResponse)
async def buy():
    """
    Страница покупки курса.

    Открывается:
    https://твой-домен/buy
    """

    order_reference = generate_order_reference()

    order_date = int(time.time())

    amount = COURSE_PRICE
    currency = COURSE_CURRENCY

    product_name = ["Онлайн-курс"]

    product_count = [1]

    product_price = [amount]

    merchant_domain = (
        PUBLIC_URL
        .replace("https://", "")
        .replace("http://", "")
        .rstrip("/")
    )

    signature = create_payment_signature(
        merchant_account=WAYFORPAY_MERCHANT,
        merchant_domain=merchant_domain,
        order_reference=order_reference,
        order_date=order_date,
        amount=amount,
        currency=currency,
        product_name=product_name,
        product_count=product_count,
        product_price=product_price,
    )

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO orders
        (
            order_reference,
            amount,
            currency,
            payment_status
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            order_reference,
            amount,
            currency,
            "pending",
        )
    )

    conn.commit()
    conn.close()

    return f"""
<!DOCTYPE html>
<html lang="uk">

<head>
    <meta charset="UTF-8">
    <title>Оплата курса</title>

    <style>

        body {{
            font-family: Arial, sans-serif;
            background: #f8f2ea;

            display: flex;
            justify-content: center;
            align-items: center;

            min-height: 100vh;
            margin: 0;
        }}

        .box {{
            background: white;

            padding: 40px;

            border-radius: 16px;

            text-align: center;

            max-width: 400px;

            box-shadow:
                0 10px 30px rgba(0,0,0,0.08);
        }}

        h1 {{
            margin-bottom: 20px;
        }}

        .price {{
            font-size: 32px;
            font-weight: bold;
            margin: 20px 0;
        }}

        button {{
            border: none;

            background: #222;
            color: white;

            padding: 15px 30px;

            border-radius: 10px;

            font-size: 17px;

            cursor: pointer;
        }}

        button:hover {{
            opacity: 0.85;
        }}

    </style>
</head>

<body>

<div class="box">

    <h1>Онлайн-курс</h1>

    <p>
        Получите доступ ко всем видеоурокам.
    </p>

    <div class="price">
        {amount} {currency}
    </div>

    <form
        method="POST"
        action="{WAYFORPAY_URL}"
        accept-charset="utf-8"
    >

        <input
            type="hidden"
            name="merchantAccount"
            value="{WAYFORPAY_MERCHANT}"
        >

        <input
            type="hidden"
            name="merchantAuthType"
            value="SimpleSignature"
        >

        <input
            type="hidden"
            name="merchantDomainName"
            value="{merchant_domain}"
        >

        <input
            type="hidden"
            name="merchantTransactionType"
            value="AUTO"
        >

        <input
            type="hidden"
            name="merchantTransactionSecureType"
            value="AUTO"
        >

        <input
            type="hidden"
            name="apiVersion"
            value="1"
        >

        <input
            type="hidden"
            name="language"
            value="UA"
        >

        <input
            type="hidden"
            name="merchantSignature"
            value="{signature}"
        >

        <input
            type="hidden"
            name="orderReference"
            value="{order_reference}"
        >

        <input
            type="hidden"
            name="orderDate"
            value="{order_date}"
        >

        <input
            type="hidden"
            name="amount"
            value="{amount}"
        >

        <input
            type="hidden"
            name="currency"
            value="{currency}"
        >

        <input
            type="hidden"
            name="productName[]"
            value="Онлайн-курс"
        >

        <input
            type="hidden"
            name="productPrice[]"
            value="{amount}"
        >

        <input
            type="hidden"
            name="productCount[]"
            value="1"
        >

        <input
            type="hidden"
            name="serviceUrl"
            value="{PUBLIC_URL}/wayforpay"
        >

        <input
            type="hidden"
            name="returnUrl"
            value="{PUBLIC_URL}/payment-result?order={order_reference}"
        >

        <button type="submit">
            Оплатить курс
        </button>

    </form>

</div>

</body>
</html>
"""


# ============================================================
# WAYFORPAY WEBHOOK
# ============================================================

@app.post("/wayforpay")
async def wayforpay_webhook(request: Request):

    try:
        data = await request.json()

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON"
        )

    print("\n==============================")
    print("WAYFORPAY CALLBACK")
    print("==============================")
    print(data)

    # --------------------------------------------------------
    # Проверяем merchant
    # --------------------------------------------------------

    merchant_account = str(
        data.get("merchantAccount", "")
    )

    if merchant_account != WAYFORPAY_MERCHANT:

        print("❌ Неверный merchantAccount")

        raise HTTPException(
            status_code=403,
            detail="Invalid merchant"
        )

    # --------------------------------------------------------
    # Проверяем подпись
    # --------------------------------------------------------

    if not verify_wayforpay_signature(data):

        print("❌ Неверная merchantSignature")

        raise HTTPException(
            status_code=403,
            detail="Invalid signature"
        )

    print("✅ Signature OK")

    # --------------------------------------------------------
    # Получаем данные
    # --------------------------------------------------------

    order_reference = str(
        data.get("orderReference", "")
    )

    transaction_status = str(
        data.get("transactionStatus", "")
    )

    amount = str(
        data.get("amount", "")
    )

    currency = str(
        data.get("currency", "")
    )

    email = data.get("email")

    # --------------------------------------------------------
    # Ищем заказ
    # --------------------------------------------------------

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM orders
        WHERE order_reference = ?
        """,
        (order_reference,)
    )

    order = cursor.fetchone()

    if not order:

        conn.close()

        print(
            "❌ Заказ не найден:",
            order_reference
        )

        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    # --------------------------------------------------------
    # Проверяем сумму и валюту
    # --------------------------------------------------------

    if str(order["amount"]) != amount:

        conn.close()

        print("❌ Неверная сумма")

        raise HTTPException(
            status_code=400,
            detail="Invalid amount"
        )

    if str(order["currency"]) != currency:

        conn.close()

        print("❌ Неверная валюта")

        raise HTTPException(
            status_code=400,
            detail="Invalid currency"
        )

    # --------------------------------------------------------
    # Успешная оплата
    # --------------------------------------------------------

    if transaction_status.lower() == "approved":

        # Проверяем, не создавали ли код раньше

        if order["access_code"]:

            access_code = order["access_code"]

        else:

            access_code = generate_access_code()

            cursor.execute(
                """
                UPDATE orders

                SET
                    payment_status = ?,
                    access_code = ?,
                    email = ?,
                    paid_at = CURRENT_TIMESTAMP

                WHERE order_reference = ?
                """,
                (
                    "paid",
                    access_code,
                    email,
                    order_reference,
                )
            )

            conn.commit()

        print("✅ Оплата подтверждена")
        print("Order:", order_reference)
        print("Access code:", access_code)

    else:

        cursor.execute(
            """
            UPDATE orders

            SET payment_status = ?

            WHERE order_reference = ?
            """,
            (
                transaction_status,
                order_reference,
            )
        )

        conn.commit()

        print(
            "⚠️ Статус платежа:",
            transaction_status
        )

        access_code = None

    conn.close()

    # --------------------------------------------------------
    # Формируем правильный ответ WayForPay
    # --------------------------------------------------------

    response_time = int(time.time())

    response_status = "accept"

    response_string = (
        f"{order_reference};"
        f"{response_status};"
        f"{response_time}"
    )

    response_signature = create_hmac_md5(
        response_string
    )

    return JSONResponse({
        "orderReference": order_reference,
        "status": response_status,
        "time": response_time,
        "signature": response_signature,
    })


# ============================================================
# PAYMENT RESULT
# ============================================================

@app.get(
    "/payment-result",
    response_class=HTMLResponse
)
async def payment_result(order: str):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM orders
        WHERE order_reference = ?
        """,
        (order,)
    )

    result = cursor.fetchone()

    conn.close()

    if not result:

        return """
<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<title>Ошибка</title>
</head>

<body>

<h1>❌ Заказ не найден</h1>

<p>
Попробуйте обратиться в поддержку.
</p>

</body>
</html>
"""

    if result["payment_status"] != "paid":

        return """
<!DOCTYPE html>
<html lang="uk">

<head>
<meta charset="UTF-8">
<title>Оплата</title>
</head>

<body>

<h1>⏳ Платёж ещё обрабатывается</h1>

<p>
Если деньги уже списались,
подождите несколько секунд и обновите страницу.
</p>

</body>

</html>
"""

    access_code = result["access_code"]

    telegram_link = (
        f"https://t.me/"
        f"{BOT_USERNAME}"
        f"?start={access_code}"
    )

    return f"""
<!DOCTYPE html>
<html lang="uk">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Оплата успешна</title>

<style>

body {{
    font-family: Arial, sans-serif;

    background: #f8f2ea;

    min-height: 100vh;

    display: flex;

    justify-content: center;

    align-items: center;

    margin: 0;
}}

.box {{

    background: white;

    padding: 40px;

    border-radius: 20px;

    max-width: 450px;

    width: calc(100% - 40px);

    text-align: center;

    box-shadow:
        0 10px 30px rgba(0,0,0,0.08);
}}

.success {{

    font-size: 55px;

    margin-bottom: 10px;
}}

h1 {{
    margin-bottom: 15px;
}}

p {{
    color: #555;

    line-height: 1.5;
}}

.telegram-button {{

    display: inline-block;

    margin-top: 20px;

    padding: 15px 25px;

    background: #229ED9;

    color: white;

    text-decoration: none;

    border-radius: 10px;

    font-weight: bold;

}}

.code {{

    margin-top: 20px;

    padding: 10px;

    background: #f1f1f1;

    border-radius: 8px;

    word-break: break-all;

    font-family: monospace;
}}

</style>

</head>

<body>

<div class="box">

<div class="success">
    ✅
</div>

<h1>
    Оплата прошла успешно!
</h1>

<p>
    Спасибо за покупку.
</p>

<p>
    Нажмите кнопку ниже,
    чтобы открыть курс в Telegram.
</p>

<a
    class="telegram-button"
    href="{telegram_link}"
>
    Открыть курс в Telegram
</a>

<div class="code">
    Код доступа:<br>
    {access_code}
</div>

</div>

</body>

</html>
"""


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
async def home():

    return {
        "status": "ok",
        "service": "Telegram Course Server"
    }