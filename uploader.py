import os
import pickle
import logging
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    filename="youtube_uploader_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def get_authenticated_service():
    logging.debug("Starting authentication process")
    credentials = None
    token_path = "tokens/token.pickle"
    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly"  # Добавлено для чтения данных о канале
    ]

    if os.path.exists(token_path):
        logging.debug(f"Found token file: {token_path}")
        try:
            with open(token_path, "rb") as token:
                credentials = pickle.load(token)
            logging.debug(f"Token scopes: {credentials.scopes}")
        except Exception as e:
            logging.error(f"Error loading token: {e}")
            return None

    if not credentials or not credentials.valid or set(scopes) != set(credentials.scopes):
        logging.debug("Token is missing, invalid, or has incorrect scopes")
        if credentials and credentials.expired and credentials.refresh_token:
            logging.debug("Attempting to refresh token")
            try:
                credentials.refresh(Request())
                logging.debug("Token refreshed successfully")
            except Exception as e:
                logging.error(f"Error refreshing token: {e}")
                credentials = None
        if not credentials:
            logging.debug("Starting OAuth flow")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    os.getenv("CLIENT_SECRET_PATH"),
                    scopes=scopes
                )
                credentials = flow.run_local_server(port=0)
                logging.debug(f"OAuth flow completed, saving token with scopes: {scopes}")
                with open(token_path, "wb") as token:
                    pickle.dump(credentials, token)
            except Exception as e:
                logging.error(f"Error during OAuth flow: {e}")
                return None

    logging.debug("Building YouTube API service")
    try:
        youtube = build("youtube", "v3", credentials=credentials)
        logging.debug("YouTube API service created successfully")
        return youtube
    except Exception as e:
        logging.error(f"Error building YouTube API service: {e}")
        return None

def get_channel_info(youtube):
    """Получить информацию о канале, связанном с токеном"""
    try:
        logging.debug("Fetching channel information")
        request = youtube.channels().list(
            part="snippet",
            mine=True
        )
        response = request.execute()
        logging.debug(f"Channel API response: {response}")
        if response["items"]:
            channel = response["items"][0]
            channel_id = channel["id"]
            channel_title = channel["snippet"]["title"]
            logging.info(f"Channel info: ID={channel_id}, Title={channel_title}")
            return channel_id, channel_title
        else:
            logging.error("No channels found for this account. Please create a YouTube channel.")
            return None, None
    except HttpError as e:
        logging.error(f"Error fetching channel info: {e}")
        if "insufficientPermissions" in str(e):
            logging.error("Token lacks required scopes. Delete token.pickle and re-authenticate.")
        return None, None
    except Exception as e:
        logging.error(f"Unexpected error fetching channel info: {e}")
        return None, None

def upload_video(youtube, video_path, thumbnail_path, title, description, publish_immediately=True, keywords=None, is_shorts=False):
    logging.debug(f"Starting video upload: {video_path}")

    # Проверка файлов
    if not os.path.exists(video_path):
        logging.error(f"Video file not found: {video_path}")
        return None
    if thumbnail_path and not os.path.exists(thumbnail_path):
        logging.error(f"Thumbnail file not found: {thumbnail_path}")
        return None
    logging.debug(f"Video file exists: {video_path}")
    logging.debug(f"Thumbnail file exists: {thumbnail_path}")

    try:
        # Оптимизация для Shorts
        if is_shorts:
            title = f"{title[:95]} #Shorts" if len(title) < 95 else title[:95]
            description = f"{description}\n#Shorts #YouTubeShorts"
            keywords = keywords or ["Shorts", "YouTubeShorts", "video", "test"]
            keywords.append("Shorts")
        else:
            keywords = keywords or ["video", "youtube", "test"]

        # Подготовка метаданных
        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": keywords,
                "categoryId": "22"  # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }

        # Установка времени публикации
        if not publish_immediately:
            publish_at = datetime.utcnow() + timedelta(minutes=5)
            body["status"]["publishAt"] = publish_at.isoformat() + "Z"
            logging.debug(f"Scheduled publish time: {publish_at}")
        else:
            logging.debug("Publishing immediately")

        # Загрузка видео
        logging.debug("Uploading video file")
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        response = request.execute()
        logging.debug(f"Video upload API response: {response}")

        video_id = response["id"]
        logging.info(f"Video uploaded successfully: ID={video_id}")

        # Загрузка превью
        if thumbnail_path:
            logging.debug("Uploading thumbnail")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            logging.info(f"Thumbnail set for video: ID={video_id}")

        return video_id

    except HttpError as e:
        logging.error(f"Error uploading video: {e}")
        if "youtubeSignupRequired" in str(e):
            logging.error("Account does not have a YouTube channel. Please create one in YouTube Studio.")
        if "invalidPublishAt" in str(e):
            logging.error("Invalid publish time. Try setting publish_immediately=True.")
        if "insufficientPermissions" in str(e):
            logging.error("Token lacks required scopes. Delete token.pickle and re-authenticate.")
        return None
    except Exception as e:
        logging.error(f"Unexpected error during upload: {e}")
        return None

def main():
    load_dotenv()
    logging.debug("Loading environment variables")
    if not os.getenv("CLIENT_SECRET_PATH"):
        logging.error("CLIENT_SECRET_PATH not set in .env")
        return

    youtube = get_authenticated_service()
    if not youtube:
        logging.error("Failed to authenticate. Check logs for details.")
        return

    # Получить информацию о канале
    channel_id, channel_title = get_channel_info(youtube)
    if not channel_id:
        logging.error("Cannot proceed without a valid YouTube channel.")
        return

    # Пример входных данных
    video_data = {
        "video_path": "source/vid1.mp4",
        "thumbnail_path": "source/thumbnail1.jpg",
        "title": "My Awesome Short",
        "description": "This is a test Short uploaded via YouTube API.\nSubscribe for more!",
        "publish_immediately": True,  # Публиковать сразу
        "keywords": ["youtube", "api", "shorts", "test"],
        "is_shorts": True  # Загружать как YouTube Short
    }

    video_id = upload_video(youtube, **video_data)
    if video_id:
        with open("video_ids.txt", "a") as f:
            f.write(f"{video_id}\n")
        logging.info(f"Video ID saved: {video_id}")
        print(f"Video uploaded successfully! ID: {video_id}, Channel: {channel_title}")
    else:
        logging.error("Video upload failed. Check logs for details.")
        print("Upload failed. Check youtube_uploader_debug.log for details.")

if __name__ == "__main__":
    main()