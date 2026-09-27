"""Проверка работающего сервера: health, openapi, вход админа."""
import httpx

BASE = "http://127.0.0.1:8000"

r = httpx.get(f"{BASE}/health", timeout=5)
print("health:", r.status_code, r.json())

r = httpx.get(f"{BASE}/openapi.json", timeout=5)
print("openapi paths:", len(r.json()["paths"]))

r = httpx.post(
    f"{BASE}/api/v1/auth/login",
    json={"username": "admin", "password": "admin123"},
    timeout=5,
)
print("login:", r.status_code)
if r.status_code == 200:
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = httpx.get(f"{BASE}/api/v1/auth/me", headers=headers, timeout=5)
    body = r.json()
    print("me:", r.status_code, body["username"], [x["code"] for x in body["roles"]])
else:
    print("login failed:", r.text)