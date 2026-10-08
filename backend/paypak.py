"""PayPak (paybost.com) - hosted checkout and IPN signature check.

Two functions, nothing else:

  initiate()  posts the payment to the gateway and returns the URL of PayPak's own hosted
              checkout page. The browser is sent there, so no card or wallet data ever
              touches this backend - the only thing we transmit is the public key.

  verify()    recomputes exactly the signature the docs specify -
                  HMAC_SHA256(secret_key, str(data.amount) + identifier).upper()
              - and compares it with the signature PayPak POSTed. main.py grants the pass
              only when this returns True, so a forged IPN can never unlock a hall.

Keys are read from the environment (.env):
    PAYPAK_PUBLIC_KEY   public API key from the merchant dashboard
    PAYPAK_SECRET_KEY   secret key - never logged, never returned, never sent to the browser
    PAYPAK_MODE         "sandbox" (test endpoint, no live money) or "live"
    APP_BASE_URL        optional, where PayPak sends the browser back to

Amounts are PKR integers (the only currency the pass prices use).
"""
import hashlib
import hmac
import json
import os
from urllib import error, parse, request

HOST = "https://paybost.com"
MODE = (os.environ.get("PAYPAK_MODE") or "sandbox").strip().lower()
PUBLIC_KEY = (os.environ.get("PAYPAK_PUBLIC_KEY") or "").strip()
SECRET_KEY = (os.environ.get("PAYPAK_SECRET_KEY") or "").strip()
ENDPOINT = f"{HOST}/payment/initiate" if MODE == "live" else f"{HOST}/sandbox/payment/initiate"
SITE_LOGO = os.environ.get("PAYPAK_LOGO") or f"{HOST}/assets/images/logoIcon/logo.png"


def configured():
    """True when the merchant keys are in .env - without them main.py falls back to DEV mode."""
    return bool(PUBLIC_KEY and SECRET_KEY)


def signature(amount, identifier) -> str:
    """HMAC-SHA256 over "amount" . identifier with the secret key, upper-cased, as the docs show."""
    if not SECRET_KEY:
        return ""
    key = f"{amount}{identifier}".encode()
    return hmac.new(SECRET_KEY.encode(), key, hashlib.sha256).hexdigest().upper()


def verify(status, identifier, sent, amount) -> bool:
    """The only thing that decides whether money moved. Constant-time compare."""
    if not configured() or not sent or not identifier:
        return False
    if str(status or "").strip().lower() != "success":
        return False
    try:
        return hmac.compare_digest(signature(amount, identifier), str(sent).strip().upper())
    except (TypeError, ValueError):
        return False


def initiate(*, identifier, amount, details, ipn_url, cancel_url, success_url,
             customer_name="", customer_email="", theme="light"):
    """-> {"url": <hosted checkout>, "message": ...}. Raises ValueError with the gateway's own
    wording when the key is wrong or the request is refused."""
    if not configured():
        raise ValueError("PayPak keys are not configured (PAYPAK_PUBLIC_KEY / PAYPAK_SECRET_KEY in .env)")
    form = {
        "public_key": PUBLIC_KEY,
        "identifier": str(identifier)[:20],
        "currency": "PKR",
        "amount": str(int(amount)),
        "details": str(details)[:100],
        "ipn_url": ipn_url,
        "cancel_url": cancel_url,
        "success_url": success_url,
        "site_logo": SITE_LOGO,
        "checkout_theme": "dark" if theme == "dark" else "light",
        # The gateway validates both as required and refuses an empty string outright,
        # so an account with no display name must still send something.
        "customer_name": (str(customer_name).strip() or str(customer_email).strip().split("@")[0]
                          or "Shaadi Planner")[:50],
        "customer_email": (str(customer_email).strip() or "customer@shaadiplanner.local")[:80],
    }
    req = request.Request(
        ENDPOINT,
        data=parse.urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
                 # paybost.com sits behind Cloudflare, which answers 403 (error 1010) to the
                 # default Python-urllib signature - the call must look like any other browser.
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8", "replace")
    except error.URLError as e:
        raise ValueError(f"Could not reach PayPak ({getattr(e, 'reason', e)})")
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        raise ValueError("PayPak returned a response this app could not read")
    # The gateway answers with "error": "yes" / "true" plus an "errors" array of field
    # messages - surface that wording instead of a generic refusal.
    failed = str(payload.get("error") or "").strip().lower() in ("true", "yes", "1") or not payload.get("url")
    if failed:
        problems = payload.get("errors")
        if isinstance(problems, list) and problems:
            raise ValueError(" ".join(str(p) for p in problems))
        raise ValueError(payload.get("message") or "PayPak refused this payment")
    return {"url": payload["url"], "message": payload.get("message") or "Payment initiated"}
