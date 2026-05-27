import os
import json
import base64
from http.client import responses

import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

load_dotenv()

# Client Configuration pulled securely from .env
CLIENT_ID = os.getenv("QBO_CLIENT_ID")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8080/callback"

TOKEN_FILE = "qbo_token.json"

# Sandbox URLs (Production endpoints use quickbooks.api.intuit.com)
QBO_BASE_URL = "https://sandbox-quickbooks.api.intuit.com/v3/company"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

# Global volatile memory string to pass the intercepted code between threads
_intercepted_auth_code = None
_intercepted_realm_id = None

# ==========================================================================
# 1. OAUTH HANDSHAKE MECHANICS (The Middleware Layer)
# ==========================================================================
class CallbackHandler(BaseHTTPRequestHandler):
    """Temporary local web server handler designed to catch Intuit's redirect code."""
    def do_GET(self):
        global _intercepted_auth_code, _intercepted_realm_id
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        #Parse the 'code' parameter out of the http://localhost:8080/callback
        query_components = parse_qs(urlparse(self.path).query)
        if "code" in query_components:
            _intercepted_auth_code = query_components["code"][0]
            #Capture the critical Realm ID/Company ID from the URL string
            if "realmId" in query_components:
                _intercepted_realm_id = query_components["realmId"][0]
            self.wfile.write(b"<html><body><h1>QBO Authentication Successful!</h1><p>You can close this window.</p></body></html>")
        else:
            self.wfile.write(b"<html><body><h1>Authentication Failed</h1></body></html>")

    def log_message(self, format, *args):
        return # Silences standard server logs to keep terminal tracking clean

def run_local_callback_server():
    """Spins up an ephemeral web server on port 8080 to capture the incoming token."""
    try:
        server = HTTPServer(("localhost", 8080), CallbackHandler)
        print("[QBO] Listening locally on port 8080 for callback validation...")
        server.handle_request()
    except Exception as e:
        print(f"[WARNING] Local interception server couldn't bind to port 8080: {e}")

def get_qbo_tokens():
    """Manages stateful authorization. Loads tokens, runs silent refreshes, or fires full handshakes."""
    # Pattern 1: Session Token Exists Locally
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            tokens = json.load(f)
            # In a full deployment, check if tokens['expires_in'] is valid .
            # To keep our architecture lean, silently refresh the token on every pipeline initialization.
            return refresh_qbo_token(tokens["refresh_token"])

    # Pattern 2: Complete OAuth Loop Required

    # Safe Guard: Ensure environment variable loaded correctly
    if not CLIENT_ID or not CLIENT_SECRET:
        raise Exception("QBO_CLIENT_ID or QBO_CLIENT_SECRET is missing from your .env file!")

    encoded_redirect = "http%3A%2F%2Flocalhost%3A8080%2Fcallback"

    auth_url = (
        f"https://appcenter.intuit.com/connect/oauth2"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&scope=com.intuit.quickbooks.accounting"
        f"&redirect_uri={encoded_redirect}"
        f"&state=reconciliation_agent_state"
    )

    print("\n==================================================")
    print("ACTION REQUIRED: QuickBooks Authentication Requested")
    print("==================================================")
    print(f"Copy and paste this URL into your browser to authorize access:\n\n{auth_url}\n")

    run_local_callback_server()

    global _intercepted_auth_code, _intercepted_realm_id

    if not _intercepted_auth_code:
        raise Exception("OAuth intercept pipeline failed: Auth code not caught.")

    # Exchange the temporary code for functional OAuth tokens
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "grant_type": "authorization_code",
        "code": _intercepted_auth_code,
        "redirect_uri": REDIRECT_URI
    }

    response = requests.post(TOKEN_URL, headers=headers, data=payload)
    # --------------------------------------------------------------------------
    # DETAILED DIAGNOSTICS LOGGING
    # --------------------------------------------------------------------------
    if response.status_code != 200:
        print("\n==================================================")
        print("          QUICKBOOKS EXCHANGE DIAGNOSTICS         ")
        print("==================================================")
        print(f"HTTP Status Code: {response.status_code}")
        print(f"Raw Server Response: {response.text}")
        print("==================================================")
        raise Exception(f"Token Exchange Failed with Status Code {response.status_code}")

    tokens = response.json()
    # Inject the captured company Realm ID directly into the saved JSON object
    if _intercepted_realm_id:
        tokens["realmId"] = _intercepted_realm_id

    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)

    return tokens

def refresh_qbo_token(refresh_token):
    """Uses the persistence key to exchange an expired session token for a live token."""
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    # Read the existing company ID from disk before overwriting the file
    old_realm_id = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            old_realm_id = json.load(f).get("realmId")

    response = requests.post(TOKEN_URL, headers=headers, data=payload)
    if response.status_code != 200:
        print("[WARNING] Refresh token expired or rejected. Clearing local session state...")
        if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
        return get_qbo_tokens()

    # --------------------------------------------------------------------------
    # DETAILED DIAGNOSTICS LOGGING
    # --------------------------------------------------------------------------
    if response.status_code != 200:
        print("\n==================================================")
        print("          QUICKBOOKS EXCHANGE DIAGNOSTICS         ")
        print("==================================================")
        print(f"HTTP Status Code: {response.status_code}")
        print(f"Raw Server Response: {response.text}")
        print("==================================================")
        raise Exception(f"Token Exchange Failed with Status Code {response.status_code}")

    tokens = response.json()

    if old_realm_id:
        tokens["realmId"] = old_realm_id
    elif _intercepted_realm_id:
        tokens["realmId"] = _intercepted_realm_id

    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)

    return tokens

# =========================================================================================
# 2. LEDGER READ/WRITE OPERATIONS (The Business Mutation Layer)
# =========================================================================================

def verify_invoice_balance(invoice_num, realm_id, access_token):
    """
    Queries QBO via SQL-like Query Language (Intuit SQL) to check
    if an invoice exists and if it holds an open balance.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    # Intuit uses a specialized SQL suntax wrapped inside and API query parameter
    query = f"SELECT * FROM Invoice WHERE DocNumber = '{invoice_num}'"
    url = f"{QBO_BASE_URL}/{realm_id}/query?query={query}"

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Ledger Query Failed: {response.text}")

    query_result = responses.json().get("QueryResponse", {})
    invoices = query_result.get("Invoice", [])

    if not invoices:
        print(f"[QBO GUARD] Invoice #{invoice_num} was not found inside the ledger.")
        return None
    invoice_data = invoices[0]
    return {
        "id": invoice_data["Id"],
        "balance": float(invoice_data["Balance"]),
        "sync_token": invoice_data["SyncToken"],
        "customer_ref": invoice_data["CustomerRef"]["value"]
    }

def apply_invoice_payment(invoice_record, payment_amount, realm_id, access_token):
    """Generate an explicit Payment Mutation payload to settle the outstanding balance."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    url = f"{QBO_BASE_URL}/{realm_id}/payment"

    # Structural JSON required by Intuit to tie a payment nutation down to an explicit asset object
    payload = {
        "CustomerRef": {
            "value": invoice_record["customer_ref"]
        },
        "TotalAmt": payment_amount,
        "Line": [
            {
                "Amount": payment_amount,
                "LinkedTxn": [
                    {
                        "TxnId": invoice_record["id"],
                        "TxnType": "Invoice"
                    }
                ]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"[QBO SUCCESS] Successfully posted cash application of ${payment_amount} to internal ID: {invoice_record['id']}")
        return response.json()
    else:
        raise Exception (f"Payment posting failed: {response.text}")