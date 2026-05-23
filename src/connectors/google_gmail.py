import os
import base64
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# We define the minimum permissions needed to read, modify labels, and fetch attachments
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def get_gmail_service():
    """Established and returns an authenticated Gmail API client session."""
    creds = None

    # 1. Look for an existing valid user session token
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # 2. If no token, or if it's expired, resolve the state
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[GMAIL] Access token expired. Refreshing silently...")
            creds.refresh(Request())
        else:
            print("[GMAIL] No valid token found. Launching browser authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next execution run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # 3. Build the authenticated API client
    # 'gmail' specifies the service, 'v1' is the version, and we pass the credentials object
    service = build('gmail', 'v1', credentials=creds)
    return service

def fetch_unreconciled_emails(service):
    # Gmail search query syntax:
    # - "is:unread" limits to unread items
    # - "-label:Reconciled" excludes emails already processed by our agent
    # - "has:attachment filename:pdf" ensures there is a PDF to parse
    query = "is:unread -label:Reconciled has:attachment filename:pdf"

    # Step 1: Fetch the list of matching Message IDs
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])

    if not messages:
        print("[GMAIL] No new invoice emails found.")
        return []

    print(f"[GMIAL] Found {len(messages)} candidate email(s) to inspect.")

    detailed_emails = []
    # Step 2: Loop and fetch full details for each message ID
    for msg in messages:
        # We fetch the full message payload metadata
        msg_detail = service.users().messages().get(userId='me', id=msg['id']).execute()
        detailed_emails.append(msg_detail)

    return detailed_emails

def download_pdf_attachments(service, email_message, output_dir="incoming_invoices"):
    #Traverse the email MIME tree
    # isolate PDF file
    # stream raw bytes to the sandbox data directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    msg_id = email_message['id']
    payload = email_message.get('payload', {})
    parts = payload.get('parts', [])

    # Traverse the MIME parts tree
    for part in parts:
        filename = part.get('filename')
        mime_type = part.get('mimeType')

        # Check if this part is a PDF attachment
        if filename and mime_type == 'application/pdf':
            body = part.get('body', {})
            attachment_id = body.get('attachmentId')

            if attachment_id:
                print(f"[GMAIL] Extracting attachment '{filename}' from Message ID: {msg_id}")

                # Call the attachments endpoint to grab the raw base64 data block
                attachment = service.users().messages().attachments().get(
                    userId='me', messageId=msg_id, id=attachment_id
                ).execute()

                data = attachment.get('data')

                # Decode base64url data into standard raw file bytes
                file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))

                # Sanitize or construct a unique filename to prevent overwriting
                # Best Practice: Prepend the unique email message ID
                unique_filename = f"{msg_id}_{filename}"
                file_path = os.path.join(output_dir, unique_filename)

                with open(file_path, 'wb') as f:
                    f.write(file_data)

                print(f"[GMAIL] Successfully saved to disk: {file_path}")
