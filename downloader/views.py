import re
import yt_dlp
import requests
import time
import os
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from .models import MediaStore

# Download location
DOWNLOAD_FOLDER = os.path.expanduser("~/Downloads")

# URL to check internet connection
CHECK_URL = "https://www.google.com"

def check_internet():
    """Check if the internet is available."""
    try:
        requests.get(CHECK_URL, timeout=5)
        return True
    except requests.RequestException:
        return False

def clean_progress(progress_str):
    """Extract numerical progress from a progress string."""
    cleaned_str = re.sub(r'\x1b\[[0-9;]*m', '', progress_str)
    match = re.search(r'(\d+)', cleaned_str)
    return match.group(1) if match else '0'

def wait_for_network(timeout=30, check_interval=5):
    """Wait for network restoration within a timeout period."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if check_internet():
            return True
        time.sleep(check_interval)
    return False

def download_with_resume(video_url, cache_key, ydl_opts):
    """Download with automatic resume on network failure."""
    start_time = time.time()
    max_timeout = 420  # 7 minutes in seconds
    
    while True:
        # Check if it has exceeded the overall timeout
        if time.time() - start_time > max_timeout:
            cache.set(f"status_{cache_key}", "Download failed after timeout")
            print("[ERROR] Overall timeout reached. Aborting download.")
            return None
            
        if not check_internet():
            cache.set(f"status_{cache_key}", "Network lost, download paused")
            print("[INFO] Network lost. Waiting for restoration...")
            
            # Wait for network with a shorter interval inside the main timeout
            network_wait_start = time.time()
            while time.time() - network_wait_start < 30:  # Check every 30 seconds
                if check_internet():
                    cache.set(f"status_{cache_key}", "Network restored, resuming download")
                    print("[INFO] Network restored. Resuming download...")
                    break
                time.sleep(5)  # Check every 5 seconds
            
            # If it haves't broken out of the loop, continue to outer loop which will check timeout
            continue
        
        cache.set(f"status_{cache_key}", "Downloading...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=True)
                filename = ydl.prepare_filename(info_dict)
            return filename  
        except yt_dlp.utils.DownloadError as e:
            error_str = str(e)
            cache.set(f"status_{cache_key}", f"Download error: {error_str}")
            print(f"[ERROR] yt-dlp DownloadError: {e}")
            
            # Check if it's a DNS resolution error
            if "getaddrinfo failed" in error_str or "Failed to resolve" in error_str:
                print("[INFO] DNS resolution issue detected. Waiting before retry...") 
                time.sleep(10)  # Wait longer for DNS issues
                continue
            else:
                # For other download errors, abort
                return None
        except Exception as e:
            cache.set(f"status_{cache_key}", f"Unexpected error: {str(e)}")
            print(f"[ERROR] Unexpected Error: {e}")
            return None

@csrf_exempt
def download_video(request, unique_id):
    """Download video with resume support."""
    if request.method != 'POST':
        return JsonResponse({"error": "Invalid request method"}, status=405)
    try:
        data = json.loads(request.body)
        video_url = data.get('video_url')
        if not video_url:
            return JsonResponse({"error": "Missing video_url"}, status=400)

        cache_key = f'progress_{unique_id}'
        cache.set(cache_key, '0')
        cache.set(f"status_{unique_id}", "Preparing download...")

        def hook(d):
            if d['status'] == 'downloading':
                percent = clean_progress(d.get('_percent_str', '0%').strip())
                cache.set(cache_key, percent)
            elif d['status'] == 'finished':
                cache.set(cache_key, '100')

        # Create a reverse timestamp - Newer files will be sorted first alphabetically
        # Using high numbers that decrease over time ensures newest files appear first
        current_time = int(time.time())
        reverse_timestamp = f"{9999999999 - current_time}"
        
        # Define a new folder path for recent downloads
        recent_download_folder = os.path.join(DOWNLOAD_FOLDER, "recent_downloads")
        os.makedirs(recent_download_folder, exist_ok=True)

        # Update the outtmpl to include the reverse timestamp
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': os.path.join(recent_download_folder, f'{reverse_timestamp}_%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'progress_hooks': [hook],
            'continuedl': True,
            'retries': 10,
            'socket_timeout': 15,
        }

        filename = download_with_resume(video_url, unique_id, ydl_opts)
        if filename:
            MediaStore.objects.create(url=video_url, media_type="video")
            return JsonResponse({"file_url": f"/downloads/inno{os.path.basename(filename)}", "unique_id": unique_id})
        return JsonResponse({"error": "Download failed"}, status=500)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format"}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Unexpected error: {str(e)}"}, status=500)

@csrf_exempt
def download_audio(request, unique_id):
    """Download audio with progress tracking."""
    if request.method != 'POST':
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        data = json.loads(request.body)
        video_url = data.get('video_url')
        if not video_url:
            return JsonResponse({"error": "Missing video_url"}, status=400)
        
        cache_key = f'progress_{unique_id}'
        cache.set(cache_key, '0')
        cache.set(f"status_{unique_id}", "Preparing audio download...")

        def hook(d):
            if d['status'] == 'downloading':
                percent = clean_progress(d.get('_percent_str', '0%').strip())
                cache.set(cache_key, percent)
            elif d['status'] == 'finished':
                cache.set(cache_key, '100')

        # Create a reverse timestamp - Newer files will be sorted first alphabetically
        # Using high numbers that decrease over time ensures newest files appear first
        current_time = int(time.time())
        reverse_timestamp = f"{9999999999 - current_time}"
        
        # Define a new folder path for recent downloads
        recent_download_folder = os.path.join(DOWNLOAD_FOLDER, "recent_downloads")
        os.makedirs(recent_download_folder, exist_ok=True)

        # Update the outtmpl to include the reverse timestamp
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(recent_download_folder, f'{reverse_timestamp}_%(title)s.%(ext)s'),
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            'progress_hooks': [hook],
            'continuedl': True,
            'retries': 10,
            'socket_timeout': 15,
        }

        # Use the download_with_resume function for audio as well
        filename = download_with_resume(video_url, unique_id, ydl_opts)
        if filename:
            # Since the postprocessor changes the extension to mp3
            filename_base = os.path.splitext(filename)[0]
            mp3_filename = f"{filename_base}.mp3"
            
            MediaStore.objects.create(url=video_url, media_type="audio")
            return JsonResponse({"file_url": f"/downloads/inno{os.path.basename(mp3_filename)}", "unique_id": unique_id})
        return JsonResponse({"error": "Download failed"}, status=500)
    
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format"}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Unexpected error: {str(e)}"}, status=500)

@csrf_exempt
def progress_view(request, unique_id):
    """Get progress and status messages."""
    progress = cache.get(f'progress_{unique_id}', '0')
    status = cache.get(f'status_{unique_id}', 'Waiting...')
    return JsonResponse({"progress": progress, "status": status})