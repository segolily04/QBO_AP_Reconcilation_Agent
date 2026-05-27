# src/main.py

import os
import glob
import shutil
import sys
from connectors.google_gmail import (
    get_gmail_service,
    fetch_unreconciled_emails,
    download_pdf_attachments
)
from connectors.gemini_ai import extract_invoice_data
from connectors.qbo_ledger import get_qbo_tokens, verify_invoice_balance, apply_invoice_payment


def run_reconciliation_pipeline():
    print("==================================================")
    print("   LAUNCHING AP RECONCILIATION AGENT CORE CYCLE   ")
    print("==================================================")

    # ========================================================
    # Phase 1: Ingestion & Environment Bootstrapping
    # ========================================================
    try:
        gmail_service = get_gmail_service()
        candidate_emails = fetch_unreconciled_emails(gmail_service)

        for email in candidate_emails:
            download_pdf_attachments(gmail_service, email)

        print("\n[SYSTEM] Phase 1 execution cycle completed successfully.")
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Pipeline execution aborted: {e}")
        print("[SYSTEM] Halting pipeline execution to prevent downstream corruption")
        return # <--- Gracefully exists the function right here, protecting Phase 2

    # ========================================================
    # Phase 3 Auth Verification: Initialize Ledger Handshake
    # ========================================================
    try:
        qbo_session = get_qbo_tokens()
        access_token = qbo_session["access_token"]
        #Realm ID is your unique Quickbooks Sandbox Company identifier returned in the handshake
        realm_id = qbo_session.get("realmId", "YOUR_FALLBACK_SANDBOX_REALM_ID")
        print("[SYSTEM] QBO Token verification successful.")
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Phase 3 QBO Authenticaion failed: {e}")
        return

    # ====================================================================
    # Phase 2 & 3 Integration: Loop, Extract, AI Guardrail, and Mutate
    # ====================================================================
    # We look inside our local folder sandbox for any downloaded PDFs
    pdf_sandbox_path = "incoming_invoices" # Maps to your working folder configuration
    pdf_files = glob.glob(os.path.join(pdf_sandbox_path, "*.pdf"))
    if not pdf_files:
        print("[SYSTEM] No local PDFs available to process in the sandbox.")
        return

    # 1. Add 'import time' to slow the traffic down
    import time

    for target_pdf in pdf_files:
        print(f"\n[SYSTEM] Commencing analysis on file: {target_pdf}")

        extracted_payload = None

        # ---------------------------------------------------------------
        # RATE LIMIT SAFETY NET: Auto-retry loop for 429 and 503 spikes
        # ---------------------------------------------------------------
        for attempt in range(1,4):
            try:
                print(f"[GEMINI AI] Sending {os.path.basename(target_pdf)} to Gemini Flash (Attempt {attempt}/3...")
                extracted_payload = extract_invoice_data((target_pdf))
                break # Extraction succeeded! Breat out of the retry loop.
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "503" in err_msg:
                    if attempt == 3:
                        print("\n==================================================")
                        print("CRITICAL: Exceeded Gemini resource limit limits.")
                        print("The system is halting execution to protect your quota.")
                        print("Please wait for your reset window and try again later.")
                        print("==================================================")
                        sys.exit(1)  # Hard stops the entire script right here
                    print(f"[RATE LIMIT] Gemini is busy or quota-throttled. Backing off for 15 seconds...")
                    time.sleep(15)
                else:
                    # If it's a structural code error, raise it immediately
                    raise e
        if not extracted_payload:
            print(f"[ERROR] Skipping {target_pdf} - Gemini API limits couldn't clear.")

        # --------------------------------------------------------------------------
        # LEDGER VALIDATION & CASH APPLICATION
        # --------------------------------------------------------------------------
        try:
            # Phase 2 AI Extraction
            extracted_payload = extract_invoice_data(target_pdf)
            print(f"[DATA] Extracted Client: {extracted_payload.client_name}")

            # Process line items from remittance array through ledger validation boundaries
            for line in extracted_payload.remittance_array:
                print(f"[DATA] Inspecting line item: Inv#{line.invoice_number}")

                # Phase 3 Guardrail: Verify current ledger state before posting mutations
                invoice_record = verify_invoice_balance(line.invoice_number, realm_id, access_token)

                if invoice_record is None:
                    print(f"[ROUTE] Guardrail Intercept: Inv#{line.invoice_number} is already paid ($0 balance). Skipping mutation.")
                    continue

                # Phase 3 Mutation: If check passes commit financial mutation safely
                apply_invoice_payment(invoice_record, line.amount_paid, realm_id, access_token)

            # Archiving Step (Executes only if the loop runs without exceptions)
            archive_dir = "data/reconciled_invoices"
            if not os.path.exists(archive_dir): os.makedirs(archive_dir)
            dest_path  = os.path.join(archive_dir, os.path.basename(target_pdf))
            shutil.move(target_pdf, dest_path)
            print(f"[SYSTEM] cycle complete. Archived source file to: {dest_path}")

            # 2-Second sleep to prevent rate-limiting/503 spikes on the next file
            print("[SYSTEM] Pacing pipeline... sleeping for 2 seconds.")
            time.sleep(2)

        except Exception as e:
            print(f"\n[CRITICAL ERROR] Phase 2/3 processing failed for {target_pdf}: {e}")

if __name__ == "__main__":
     run_reconciliation_pipeline()