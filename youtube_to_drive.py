import os
import sys
import json
import glob
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import yt_dlp

# --- CONFIGURATION ---
CHANNEL_URL = "https://www.youtube.com/@DramaGo-Go/videos"
HISTORY_FILE = "download_history.txt"
COOKIE_FILE_PATH = "cookies.txt"

# Standard Options
YTDLP_OPTS = {
    'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
    'outtmpl': '%(title)s.%(ext)s',
    'quiet': True,
    'no_warnings': True,
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
        # Add cookie file to options
        YTDLP_OPTS['cookiefile'] = COOKIE_FILE_PATH
        return True
    else:
        print("Warning: COOKIES_TXT secret not found. Trying without cookies (might fail).")
        return False

def get_drive_service():
    creds_json = os.environ.get('GDRIVE_SA_KEY')
    if not creds_json:
        print("Error: GDRIVE_SA_KEY secret is missing.")
        sys.exit(1)
    
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)

def upload_file(service, filepath, folder_id):
    print(f"Uploading {filepath}...")
    file_metadata = {'name': filepath, 'parents': [folder_id]}
    media = MediaFileUpload(filepath, resumable=True)
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"File ID: {file.get('id')} uploaded.")
    return file.get('id')

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

    # Setup Cookies
    has_cookies = setup_cookies()

    history = load_history()
    drive_service = get_drive_service()

    print("Checking for new videos...")
    
    # Configure extraction options
    extract_opts = {
        'extract_flat': True, 
        'quiet': True,
    }
    if has_cookies:
        extract_opts['cookiefile'] = COOKIE_FILE_PATH

    # 1. Fetch Video List
    with yt_dlp.YoutubeDL(extract_opts) as ydl:
        try:
            info = ydl.extract_info(CHANNEL_URL, download=False)
        except Exception as e:
            print(f"Error fetching channel info: {e}")
            sys.exit(1)

    if 'entries' not in info:
        print("No videos found.")
        return

    # Check the last 10 videos
    recent_videos = [v for v in info['entries'][:10] if v]

    for video in recent_videos:
        vid_id = video.get('id')
        title = video.get('title', 'Unknown Title')
        
        if not vid_id: continue

        if vid_id in history:
            print(f"Skipping already downloaded: {title}")
            continue

        print(f"Found new video: {title} ({vid_id})")
        
        # 2. Download
        download_success = False
        try:
            with yt_dlp.YoutubeDL(YTDLP_OPTS) as ydl:
                ydl.download([video['url']])
            download_success = True
        except Exception as e:
            print(f"Failed to download {title}: {e}")
            continue

        if download_success:
            # Find the file
            files = sorted(glob.glob("*"), key=os.path.getmtime, reverse=True)
            video_files = [f for f in files if f.endswith(('.mp4', '.mkv', '.webm'))]

            if not video_files:
                print("Error: Downloaded file not found on disk.")
                continue
                
            target_file = video_files[0]

            # 3. Upload
            try:
                upload_file(drive_service, target_file, folder_id)
                save_history(vid_id)
                print(f"Success! {title} processed.")
                
                # Cleanup video file
                if os.path.exists(target_file):
                    os.remove(target_file)
            except Exception as e:
                print(f"Error uploading {title}: {e}")
    
    # Cleanup cookies file for security
    if os.path.exists(COOKIE_FILE_PATH):
        os.remove(COOKIE_FILE_PATH)

if __name__ == "__main__":
    main()
