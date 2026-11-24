"""One-time sign-in for the Update data Action: prints the Google refresh token for the GDRIVE_* secrets.

    python -m pip install google-auth-oauthlib
    python drive_auth.py CLIENT_ID CLIENT_SECRET

CLIENT_ID and CLIENT_SECRET: a Google Cloud "Desktop app" OAuth client of a project with the Drive API enabled.
A browser opens; sign in with the Google account whose Drive holds the temporary copies (fetch_data.py deletes
each copy right after downloading it). Then add three repository secrets on GitHub (Settings > Secrets and
variables > Actions): GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET and GDRIVE_REFRESH_TOKEN (printed below).

The token is shown only here; it is not saved to a file. Keep the OAuth consent screen "In production":
in "Testing", Google lets refresh tokens expire after 7 days.
"""
import sys

# full Drive access: copying a file that someone else owns needs it (drive.file / drive.readonly can't copy)
SCOPES = ["https://www.googleapis.com/auth/drive"]


def main(client_id, client_secret):
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_config({"installed": {
        "client_id": client_id, "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        sys.exit("Google sent no refresh token; remove the app's access at myaccount.google.com/permissions and retry")
    print("\nGDRIVE_REFRESH_TOKEN:\n" + creds.refresh_token)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
