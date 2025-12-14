import os
import sys
import json
import glob
import datetime
import yt_dlp

# New Authentication Libraries for User Account (2TB Storage)
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIGURATION ---
CHANNEL_URL = "https://www.youtube.com/@DramaGo-Go/videos"
HISTORY_FILE = "download_history.txt"
COOKIE_FILE_PATH = "cookies.txt"

# Standard Options for Downloading
YTDLP_OPTS = {
    'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]',
    
    # Speed Boost Settings
    'concurrent_fragment_downloads': 4,
    'http_chunk_size': 10485760, 

    # Settings for stability
    'outtmpl': '%(id)s.%(ext)s',        # Use ID for filename safety
    'quiet': True,
    'no_warnings': True,
    'noprogress': True,                 # Clean logs
    'restrictfilenames': True,
    'sleep_interval': 5,
}

def setup_cookies():
    """Creates a local cookies.txt file from the GitHub Secret env var"""
    cookies_content = os.environ.get('COOKIES_TXT')
    if cookies_content:
        print("Loading cookies from secret...")
        with open(COOKIE_FILE_PATH, 'w') as f:
            f.write(cookies_content)
        YTDLP_OPTS['cookiefile'] = COOKIE_FILE_PATH
        return True
    else:
        print("Warning: COOKIES_TXT secret not found. Trying without cookies (might fail).")
        return False

def get_drive_service():
    """Authenticate using OAuth 2.0 User Credentials (Uses YOUR 2TB quota)"""
    oauth_json = os.environ.get('GDRIVE_OAUTH')
    if not oauth_json:
        print("Error: GDRIVE_OAUTH secret is missing. Please add it to GitHub Secrets.")
        sys.exit(1)
    
    try:
        creds_data = json.loads(oauth_json)
        
        # Reconstruct the user credentials using the Refresh Token
        # This allows the script to get a new "Session Token" automatically
        creds = Credentials(
            None, # No access token yet, we will refresh it
            refresh_token=creds_data['refresh_token'],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_data['client_id'],
            client_secret=creds_data['client_secret'],
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        
        # Refresh the token immediately to make sure it works
        if not creds.valid:
            creds.refresh(Request())
            
        return build('drive', 'v3', credentials=creds)
        
    except Exception as e:
        print(f"Authentication Error: {e}")
        print("Check if your GDRIVE_OAUTH secret is correct.")
        sys.exit(1)

def upload_file(service, filepath, folder_id, display_name):
    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"Uploading {filepath} ({file_size_mb:.2f} MB) as '{display_name}'...")
    
    file_metadata = {'name': display_name, 'parents': [folder_id]}
    
    media = MediaFileUpload(filepath, resumable=True)
    try:
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"File ID: {file.get('id')} uploaded successfully.")
        return file.get('id')
    except Exception as e:
        print(f"API Error during upload: {e}")
        # If error is 403, it means permissions issues, but we solved storage quota by switching users.
        return None

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, 'r') as f:
        return set(line.strip() for line in f)

def save_history(video_id):
    with open(HISTORY_FILE, 'a') as f:
        f.write(f"{video_id}\n")

def main():
    folder_id = os.environ.get('GDRIVE_FOLDER_ID')
    if not folder_id:
        print("Error: GDRIVE_FOLDER_ID secret is missing.")
        sys.exit(1)

    has_cookies = setup_cookies()
    history = load_history()
    
    try:
        drive_service = get_drive_service()
    except Exception as e:
        print(f"Failed to connect to Google Drive: {e}")
        return

    print("Checking for new videos (Scanning last 10 uploads)...")
    
    extract_opts = {
        'extract_flat': True, 
        'quiet': True,
        'playlistend': 10,
        'dateafter': 'now-24hours',
    }
    if has_cookies:
        extract_opts['cookiefile'] = COOKIE_FILE_PATH

    with yt_dlp.YoutubeDL(extract_opts) as ydl:
        try:
            info = ydl.extract_info(CHANNEL_URL, download=False)
        except Exception as e:
            print(f"Error fetching channel info: {e}")
            sys.exit(1)

    if 'entries' not in info:
        print("No videos found.")
        return

    recent_videos = [v for v in info['entries'] if v]
    if not recent_videos:
        print("No videos found in the last 24 hours.")
        return

    for video in recent_videos:
        vid_id = video.get('id')
        title = video.get('title', 'Unknown Title')
        
        if not vid_id: continue

        if vid_id in history:
            print(f"Skipping already downloaded: {title}")
            continue

        print(f"Found new video: {title} ({vid_id})")
        print("Starting download... (Multi-threaded speed boost active)")
        
        download_success = False
        try:
            with yt_dlp.YoutubeDL(YTDLP_OPTS) as ydl:
                ydl.download([video['url']])
            download_success = True
            print("Download phase complete.")
        except Exception as e:
            print(f"Failed to download {title}: {e}")
            continue

        if download_success:
            # Find file by ID
            possible_files = glob.glob(f"{vid_id}.*")
            video_files = [f for f in possible_files if f.endswith(('.mp4', '.mkv', '.webm'))]

            if not video_files:
                print(f"Error: Downloaded file for ID {vid_id} not found on disk.")
                continue
                
            target_file = video_files[0]
            ext = target_file.split('.')[-1]
            drive_filename = f"{title}.{ext}"

            # Upload using OAuth Service
            file_id = upload_file(drive_service, target_file, folder_id, drive_filename)
            
            if file_id:
                save_history(vid_id)
                print(f"Success! {title} processed.")
            else:
                print("Upload failed.")
                
            # Cleanup
            if os.path.exists(target_file):
                os.remove(target_file)
    
    if os.path.exists(COOKIE_FILE_PATH):
        os.remove(COOKIE_FILE_PATH)

if __name__ == "__main__":
    main()
