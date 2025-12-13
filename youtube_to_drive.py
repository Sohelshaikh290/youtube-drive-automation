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
# Resolution limit: downloads best video <= 720p
YTDLP_OPTS = {
    'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
    'outtmpl': '%(title)s.%(ext)s',
    'quiet': True,
    'no_warnings': True,
    'restrictfilenames': True,
}

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

    history = load_history()
    drive_service = get_drive_service()

    # 1. Fetch latest videos from channel using yt-dlp (fast extraction)
    print("Checking for new videos...")
    
    # We use extract_flat to get metadata without downloading yet
    opts = {'extract_flat': True, 'quiet': True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(CHANNEL_URL, download=False)
        except Exception as e:
            print(f"Error fetching channel info: {e}")
            sys.exit(1)

    if 'entries' not in info:
        print("No videos found.")
        return

    # Check the last 10 videos (to save time/resources)
    recent_videos = info['entries'][:10]

    for video in recent_videos:
        vid_id = video['id']
        title = video['title']
        
        if vid_id in history:
            print(f"Skipping already downloaded: {title}")
            continue

        print(f"Found new video: {title} ({vid_id})")
        
        # 2. Download the video
        try:
            with yt_dlp.YoutubeDL(YTDLP_OPTS) as ydl:
                ydl.download([video['url']])
        except Exception as e:
            print(f"Failed to download {title}: {e}")
            continue

        # Find the downloaded file
        # yt-dlp might save as mp4, mkv, or webm depending on format availability
        files = glob.glob(f"*{title[:10]}*") # Match partial title safely
        # Better approach: find most recent file in dir
        files = sorted(glob.glob("*"), key=os.path.getmtime, reverse=True)
        
        # Filter for video extensions
        video_files = [f for f in files if f.endswith(('.mp4', '.mkv', '.webm'))]

        if not video_files:
            print("Error: Downloaded file not found.")
            continue
            
        target_file = video_files[0]

        # 3. Upload to Drive
        try:
            upload_file(drive_service, target_file, folder_id)
            
            # 4. Update History
            save_history(vid_id)
            print(f"Success! {title} processed.")

            # 5. Cleanup local file to save space on runner
            os.remove(target_file)
            
        except Exception as e:
            print(f"Error uploading {title}: {e}")

if __name__ == "__main__":
    main()
