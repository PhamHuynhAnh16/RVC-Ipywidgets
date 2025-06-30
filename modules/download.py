import re
import os
import sys
import shutil
from yt_dlp import YoutubeDL
import os
from urllib.parse import urlparse
import re


sys.path.append(os.getcwd())

from modules.utils import HF_download_file
from modules import gdown, meganz, mediafire, pixeldrain

def move_files_from_directory(src_dir, dest_models, model_name):
    for root, _, files in os.walk(src_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if file.endswith(".index"):
                filepath = os.path.join(dest_models, file.replace(' ', '_').replace('(', '').replace(')', '').replace('[', '').replace(']', '').replace(",", "").replace('"', "").replace("'", "").replace("|", "").strip())

                shutil.move(file_path, filepath)
            elif file.endswith(".pth") and not file.startswith("D_") and not file.startswith("G_"):
                pth_path = os.path.join(dest_models, model_name + ".pth")

                shutil.move(file_path, pth_path)

def save_drop_model(dropbox):
    model_folders = "rvc_models" 
    save_model_temp = "save_model_temp"

    if not os.path.exists(model_folders): os.makedirs(model_folders, exist_ok=True)
    if not os.path.exists(save_model_temp): os.makedirs(save_model_temp, exist_ok=True)

    shutil.move(dropbox, save_model_temp)

    try:
        print("[INFO] Start uploading...")

        file_name = os.path.basename(dropbox)
        model_folders = os.path.join(model_folders, file_name.replace(".zip", "").replace(".pth", "").replace(".index", ""))

        if file_name.endswith(".zip"):
            shutil.unpack_archive(os.path.join(save_model_temp, file_name), save_model_temp)
            move_files_from_directory(save_model_temp, model_folders, file_name.replace(".zip", ""))
        elif file_name.endswith(".pth"): 
            output_file = os.path.join(model_folders, file_name)
            shutil.move(os.path.join(save_model_temp, file_name), output_file)
        elif file_name.endswith(".index"):
            def extract_name_model(filename):
                match = re.search(r"([A-Za-z]+)(?=_v|\.|$)", filename)
                return match.group(1) if match else None
            
            model_logs = os.path.join(model_folders, extract_name_model(file_name))
            if not os.path.exists(model_logs): os.makedirs(model_logs, exist_ok=True)
            shutil.move(os.path.join(save_model_temp, file_name), model_logs)
        else: 
            print("[WARNING] Format not supported. Supported formats ('.zip', '.pth', '.index')")
            return
        
        print("[INFO] Completed upload.")
    except Exception as e:
        print(f"[ERROR] An error occurred during unpack: {e}")
    finally:
        shutil.rmtree(save_model_temp, ignore_errors=True)

def download_model(url=None, model=None):
    if not url: 
        print("[WARNING] Please provide a valid url.")
        return

    if not model: 
        print("[WARNING] Please provide a valid model name.")
        return

    model = model.replace(".pth", "").replace(".index", "").replace(".zip", "").replace(" ", "_").replace("(", "").replace(")", "").replace("[", "").replace("]", "").replace(",", "").replace('"', "").replace("'", "").replace("|", "").strip()
    url = url.replace("/blob/", "/resolve/").replace("?download=true", "").strip()

    download_dir = "download_model"
    model_folders = "rvc_models" 

    if not os.path.exists(download_dir): os.makedirs(download_dir, exist_ok=True)
    if not os.path.exists(model_folders): os.makedirs(model_folders, exist_ok=True)

    model_folders = os.path.join(model_folders, model)
    os.makedirs(model_folders, exist_ok=True)
    
    try:
        print("[INFO] Start downloading...")

        if url.endswith(".pth"): HF_download_file(url, os.path.join(model_folders, f"{model}.pth"))
        elif url.endswith(".index"): HF_download_file(url, os.path.join(model_folders, f"{model}.index"))
        elif url.endswith(".zip"):
            output_path = HF_download_file(url, os.path.join(download_dir, model + ".zip"))
            shutil.unpack_archive(output_path, download_dir)

            move_files_from_directory(download_dir, model_folders, model)
        else:
            if "drive.google.com" in url or "drive.usercontent.google.com" in url:
                file_id = None

                if "/file/d/" in url: file_id = url.split("/d/")[1].split("/")[0]
                elif "open?id=" in url: file_id = url.split("open?id=")[1].split("/")[0]
                elif "/download?id=" in url: file_id = url.split("/download?id=")[1].split("&")[0]
                
                if file_id:
                    file = gdown.gdown_download(id=file_id, output=download_dir)
                    if file.endswith(".zip"): shutil.unpack_archive(file, download_dir)

                    move_files_from_directory(download_dir, model_folders, model)
            elif "mega.nz" in url:
                meganz.mega_download_url(url, download_dir)

                file_download = next((f for f in os.listdir(download_dir)), None)
                if file_download.endswith(".zip"): shutil.unpack_archive(os.path.join(download_dir, file_download), download_dir)

                move_files_from_directory(download_dir, model_folders, model)
            elif "mediafire.com" in url:
                file = mediafire.Mediafire_Download(url, download_dir)
                if file.endswith(".zip"): shutil.unpack_archive(file, download_dir)

                move_files_from_directory(download_dir, model_folders, model)
            elif "pixeldrain.com" in url:
                file = pixeldrain.pixeldrain(url, download_dir)
                if file.endswith(".zip"): shutil.unpack_archive(file, download_dir)

                move_files_from_directory(download_dir, model_folders, model)
            else:
                print("[WARNING] The url path is not supported.")
                return
        
        print("[INFO] Model download complete.")
    except Exception as e:
        print(f"[INFO] An error has occurred: {e}")
    finally:
        shutil.rmtree(download_dir, ignore_errors=True)




def is_valid_url(url):
    """
    Validates if the provided string is a valid URL.
    
    Args:
        url: The URL to validate.
    
    Returns:
        True if valid URL, False otherwise.
    """
    url_pattern = re.compile(
        r'^(https?://)?'  # http:// or https://
        r'((([A-Za-z0-9-]+\.)+[A-Za-z]{2,6})|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(:[0-9]{1,5})?(/.*)?$'  # optional port and path
    )
    return bool(url_pattern.match(url))

def sanitize_filename(filename):
    """
    Sanitizes filename by removing invalid characters.
    
    Args:
        filename: The filename to sanitize.
    
    Returns:
        Sanitized filename.
    """
    return re.sub(r'[<>:"/\\|?*]', '', filename)

def download_audio(url, output_path='.', audio_format='mp3', quality='192'):
    """
    Downloads audio from a YouTube video URL with enhanced error handling and progress feedback.

    Args:
        url: The URL of the YouTube video.
        output_path: Directory to save the downloaded audio. Defaults to current directory.
        audio_format: Desired audio format (mp3, wav, flac, etc.). Defaults to 'mp3'.
        quality: Audio quality in kbps. Defaults to '192'.

    Returns:
        Path to the downloaded file or None if download fails.
    """
    # Validate URL
    if not is_valid_url(url):
        print("[Error]: Invalid URL provided.")
        return None

    # Validate and create output directory
    output_path = os.path.abspath(output_path)
    try:
        os.makedirs(output_path, exist_ok=True)
    except OSError as e:
        print(f"[Error]: Failed to create output directory '{output_path}': {e}")
        return None

    # Validate audio format
    valid_formats = ['mp3', 'wav', 'flac', 'm4a', 'ogg']
    if audio_format not in valid_formats:
        print(f"Error: Invalid audio format. Supported formats: {', '.join(valid_formats)}")
        return None

    # Validate quality
    try:
        quality_int = int(quality)
        if not 32 <= quality_int <= 320:
            print("[Error]: Quality must be between 32 and 320 kbps.")
            return None
    except ValueError:
        print("[Error]: Quality must be a valid number.")
        return None

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': audio_format,
            'preferredquality': quality,
        }],
        'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        'cookiefile': 'assets/ytdl.txt' if os.path.exists('assets/ytdl.txt') else None,
        'quiet': False,
        'progress_hooks': [lambda d: print(f"Downloading: {d['downloaded_bytes'] / d['total_bytes'] * 100:.1f}%"
                                        if d['status'] == 'downloading' else 
                                        "Download complete!" if d['status'] == 'finished' else '')],
        'noplaylist': True,  # Download single video, not playlist
        'retries': 3,  # Retry on failure
        'fragment_retries': 3,
        'socket_timeout': 30,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            title = sanitize_filename(info_dict.get('title', 'audio'))
            output_file = os.path.join(output_path, f"{title}.{audio_format}")
            print(f"[INFO]: Successfully downloaded: {output_file}")
            return output_file
    except Exception as e:
        print(f"[ERROR]: AError during download: {e}")
        return None

