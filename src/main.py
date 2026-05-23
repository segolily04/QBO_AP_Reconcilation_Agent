# src/main.py

from connectors.google_gmail import (
    get_gmail_service,
    fetch_unreconciled_emails,
    download_pdf_attachments
)

def run_reconciliation_pipeline():
    print("==================================================")
    print("   LAUNCHING AP RECONCILIATION AGENT CORE CYCLE   ")
    print("==================================================")

    # Phase 1: Ingestion & Environment Bootstrapping
    try:
        gmail_service = get_gmail_service()
        candidate_emails = fetch_unreconciled_emails(gmail_service)

        for email in candidate_emails:
            download_pdf_attachments(gmail_service, email)

        print("\n[SYSTEM] Phase 1 execution cycle completed successfully.")

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Pipeline execution aborted: {e}")
        # In later phases, this is where our automated alert system catches general faults

if __name__ == "__main__":
    run_reconciliation_pipeline()