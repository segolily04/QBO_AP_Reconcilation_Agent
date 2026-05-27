# src/main.py

import os
import glob
import shutil
from connectors.google_gmail import (
    get_gmail_service,
    fetch_unreconciled_emails,
    download_pdf_attachments
)
from connectors.gemini_ai import extract_invoice_data

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
    # Phase 2: AI Extraction Testing
    # ========================================================
    # We look inside our local folder sandbox for any downloaded PDFs
    pdf_sandbox_path = "incoming_invoices" # Maps to your working folder configuration
    pdf_files = glob.glob(os.path.join(pdf_sandbox_path, "*.pdf"))
    if not pdf_files:
        print("[SYSTEM] No local PDFs available to process in the sandbox.")
        return

    #Let's grab the very first PDF found and verify our GEMINI connection
    test_pdf = pdf_files[0]
    print(f"\n[SYSTEM] Target testing file identified: {test_pdf}")

    try:
        extracted_payload = extract_invoice_data(test_pdf)

        print("\n==========================================")
        print("       VALIDATED AI EXTRACTION RESULT       ")
        print("\n==========================================")
        print(f"Client Detected: {extracted_payload.client_name}")
        print("Remittance Array:")
        for idx, line in enumerate(extracted_payload.remittance_array, 1):
            print(f" LINE {idx}: Inv#{line.invoice_number} | Billed: ${line.amount_invoiced} | Paid: ${line.amount_paid}")
        print("\n==========================================")

        #---------------------------------------------------------------------------
        # Archiving Step (Executes only if the code above succeeds without errors)
        #---------------------------------------------------------------------------
        archive_dir = "data/reconciled_invoices"
        if not os.path.exists(archive_dir):
            os.makedirs(archive_dir)

        # Construct the destination path keeping the unique filename
        dest_path = os.path.join(archive_dir, os.path.basename(test_pdf))

        # Move the file from the inbound queue to the success archive
        shutil.move(test_pdf, dest_path)
        print(f"[SYSTEM] Clean cycle complete. Archived invoice to {dest_path}")

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Phase 2 validation failed: {e}")

if __name__ == "__main__":
    run_reconciliation_pipeline()