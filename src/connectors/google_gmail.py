import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oathlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# We define the minimum permissions needed to read, modify labels, and fetch attachments
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def get_gmail_service():
    creds = None

    # 1. Look for an existing valid user session token
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('toke.json', SCOPES)

    # 2. If no token, or if it's expired, resolve the state
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Access token expired. Refreshing silently...")
            creds.refresh(Request())
        else:
            print("No valid token found. Launching browser authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        #Save the credentials for the next execution run
        with open('token.json', 'w') as token:
            token.write(creds.to)json()

    # 3. Build the authenticated API client
    # 'gmail' specifies the service, 'v1' is the version, and we pass the credentials object
    service = build('gmail', 'v1', credentials=creds)
    return service