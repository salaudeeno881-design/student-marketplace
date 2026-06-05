import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()
key = os.getenv("PAYSTACK_SECRET_KEY")
print("KEY=" + ("SET" if key else "NONE"))

payload = {
    "email": "test@example.com",
    "amount": 100,
    "callback_url": "http://127.0.0.1:5000/success",
    "metadata": {"listing_id": "1", "buyer_id": "1"},
}

req = urllib.request.Request(
    "https://api.paystack.co/transaction/initialize",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req) as resp:
        print("SUCCESS", resp.status)
        print(json.load(resp))
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="ignore")
    print("HTTPERR", exc.code)
    print(body)
except Exception as e:
    print("ERR", e)
