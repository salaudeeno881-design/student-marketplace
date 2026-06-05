import os
import json
import urllib.request
import urllib.error

# Try python-dotenv first
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # Fallback: attempt to read .env in project root
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

key = os.environ.get('PAYSTACK_SECRET_KEY')
print('Loaded PAYSTACK_SECRET_KEY:', 'SET' if key else 'NOT SET')

payload = {
    'email': 'test@example.com',
    'amount': 100,
    'callback_url': 'http://127.0.0.1:5000/success',
}

req = urllib.request.Request(
    'https://api.paystack.co/transaction/initialize',
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Authorization': f'Bearer {key}' if key else '',
        'Content-Type': 'application/json',
    },
    method='POST',
)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode('utf-8')
        print('HTTP', resp.status)
        try:
            print(json.dumps(json.loads(body), indent=2))
        except Exception:
            print(body)
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='ignore')
    print('HTTPError', e.code)
    print(body)
except Exception as e:
    print('Error:', e)
