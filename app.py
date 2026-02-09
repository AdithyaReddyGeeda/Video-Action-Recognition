#!/usr/bin/env python3
"""
Flask backend server for video action recognition.
Features:
- Immediate transcoding for non-MP4 video previews.
- Automatic thumbnail generation for video posters.
- Automatic cleanup of temporary files.
- Production-ready: config from env, rate limiting, secure uploads.
"""

import os
import tempfile
import json
import uuid
from flask import Flask, request, jsonify, send_from_directory, url_for
from werkzeug.utils import secure_filename
import subprocess
import sys
import threading

# --- Configuration (from environment) ---
DEBUG = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
PORT = int(os.environ.get("FLASK_PORT", "5001"))
MAX_CONTENT_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
RATE_LIMIT_UPLOAD = os.environ.get("RATE_LIMIT_UPLOAD", "10 per minute")
RATE_LIMIT_PREDICT = os.environ.get("RATE_LIMIT_PREDICT", "20 per minute")

app = Flask(__name__, static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_MB * 1024 * 1024
# Explicit in-memory rate limit storage (set RATELIMIT_STORAGE_URI=redis://... for production multi-worker)
app.config.setdefault('RATELIMIT_STORAGE_URI', os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'))

# Rate limiting
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per hour"],
    )
except ImportError:
    limiter = None

# --- Directory Setup ---
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or tempfile.mkdtemp()
PREVIEW_FOLDER = os.environ.get("PREVIEW_FOLDER", "static/previews")
THUMBNAIL_FOLDER = os.environ.get("THUMBNAIL_FOLDER", "static/thumbnails")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PREVIEW_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm'}

def schedule_deletion(file_path, delay_seconds=3600):
    """Schedules a file to be deleted after a specified delay (default 1 hour)."""
    def delete_file():
        try:
            print(f"⏲️ Deleting temporary file: {file_path}")
            os.remove(file_path)
        except OSError as e:
            print(f"Error deleting file {file_path}: {e}")

    timer = threading.Timer(delay_seconds, delete_file)
    timer.start()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_video_file(file_path, timeout_seconds=10):
    """
    Verify the file is a valid video using ffprobe. Removes the file on failure.
    Returns (True, None) on success, (False, error_message) on failure.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode != 0 or "video" not in (result.stdout or "").lower():
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
            return False, "File is not a valid video or is corrupted."
        return True, None
    except subprocess.TimeoutExpired:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return False, "Video validation timed out."
    except FileNotFoundError:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return False, "Server configuration error (ffprobe not found)."
    except Exception as e:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return False, "Video validation failed."


def generate_thumbnail(video_path, output_filename):
    """Extracts a frame from a video to use as a thumbnail poster."""
    output_path = os.path.join(THUMBNAIL_FOLDER, output_filename)
    try:
        cmd = [
            'ffmpeg', '-i', video_path,
            '-ss', '00:00:01.000',
            '-vframes', '1',
            '-q:v', '2',
            '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        thumbnail_url = url_for('static', filename=f'thumbnails/{output_filename}', _external=True)
        return {"url": thumbnail_url, "path": output_path}
    except Exception as e:
        print(f"Thumbnail generation error: {e}")
        return None

def transcode_for_preview(input_path, output_filename):
    """Converts a video to a web-friendly MP4 format."""
    output_path = os.path.join(PREVIEW_FOLDER, output_filename)
    try:
        cmd = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-crf', '23',
            '-c:a', 'aac',
            '-movflags', '+faststart',
            '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=90)
        preview_url = url_for('static', filename=f'previews/{output_filename}', _external=True)
        return {"url": preview_url, "path": output_path}
    except Exception as e:
        print(f"FFmpeg error: {e}")
        return None

def predict_video_action(video_path):
    """Runs the external prediction script on a video file."""
    try:
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as temp_file:
            temp_output = temp_file.name
        
        cmd = [
            sys.executable, 'predict_single_video.py', 
            '--video', video_path,
            '--output', temp_output
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            return {"error": f"Prediction script failed: {result.stderr}"}
        
        with open(temp_output, 'r') as f:
            prediction_data = json.load(f)
        
        os.unlink(temp_output)
        return prediction_data
        
    except Exception as e:
        return {"error": f"Prediction process error: {str(e)}"}

def _rate_limit(limit_string):
    """Apply rate limit only if limiter is available."""
    if limiter is None:
        return lambda f: f
    return limiter.limit(limit_string)


@app.route('/')
def index():
    """Serves the main HTML page."""
    return send_from_directory('.', 'video_predictor.html')


@app.route('/health')
def health():
    """Health check for load balancers and monitoring."""
    return jsonify({"status": "ok"})


@app.route('/generate_preview', methods=['POST'])
@_rate_limit(RATE_LIMIT_UPLOAD)
def generate_preview():
    """Handles file upload, validates video, generates preview and thumbnail."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type or no file selected"}), 400

    base = secure_filename(file.filename)
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else "mp4"
    unique_name = f"{uuid.uuid4().hex}_{base}" if base else f"{uuid.uuid4().hex}.{ext}"
    original_path = os.path.join(UPLOAD_FOLDER, unique_name)
    file.save(original_path)

    valid, err = validate_video_file(original_path)
    if not valid:
        return jsonify({"error": err}), 400

    base_name = os.path.splitext(unique_name)[0]
    preview_filename = f"{base_name}_preview.mp4"
    thumbnail_filename = f"{base_name}_thumb.jpg"

    transcode_result = transcode_for_preview(original_path, preview_filename)
    thumbnail_result = generate_thumbnail(original_path, thumbnail_filename)

    if transcode_result and thumbnail_result:
        schedule_deletion(transcode_result['path'], 3600)
        schedule_deletion(thumbnail_result['path'], 3600)
        return jsonify({
            "preview_url": transcode_result['url'],
            "poster_url": thumbnail_result['url'],
            "original_filename": unique_name,
        })
    return jsonify({"error": "Failed to generate preview or thumbnail"}), 500


@app.route('/predict', methods=['POST'])
@_rate_limit(RATE_LIMIT_PREDICT)
def predict():
    """Runs prediction on a file that has already been uploaded."""
    data = request.get_json()
    if not data or 'filename' not in data:
        return jsonify({"error": "Filename not provided"}), 400
    
    filename = data.get('filename', '').strip()
    if not filename or os.path.basename(filename) != filename or '..' in filename:
        return jsonify({"error": "Invalid filename"}), 400
    video_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.abspath(video_path).startswith(os.path.abspath(UPLOAD_FOLDER)):
        return jsonify({"error": "Invalid filename"}), 400

    if not os.path.exists(video_path):
        return jsonify({"error": "File not found on server. It may have been cleared or never uploaded."}), 404
    
    prediction_result = predict_video_action(video_path)
    
    if "error" in prediction_result:
        return jsonify(prediction_result), 500
    
    return jsonify(prediction_result)

if __name__ == '__main__':
    print("Starting Video Action Recognition Server...")
    print(f"Debug: {DEBUG}, Host: {HOST}, Port: {PORT}")
    if not DEBUG:
        print("Production mode: set FLASK_DEBUG=1 for development.")
    print(f"Open http://localhost:{PORT}")
    app.run(debug=DEBUG, host=HOST, port=PORT)