# run.py
# SnapYTube Ultimate - مع دعم مجلدات منفصلة للمستخدمين

import os
import sys
import time
import mimetypes
import uuid
import queue
import threading
import subprocess
import json
from urllib.parse import unquote, quote
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS

from config import Config
from downloader import downloader

app = Flask(__name__,
            template_folder=Config.TEMPLATE_FOLDER,
            static_folder=Config.STATIC_FOLDER)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = Config.MAX_CONTENT_LENGTH
CORS(app)

INDEX_HTML_PATH = os.path.join(Config.BASE_DIR, 'index.html')

# ⭐⭐⭐ نطاقات ما تحتاج مجلد مستخدم (تسريع + منع إنشاء مجلدات عشوائية) ⭐⭐⭐
NO_SETUP_PREFIXES = ('/static', '/favicon.ico', '/api/health', '/api/check-update')

# ⭐⭐⭐ Rate limiting بسيط بالذاكرة لكل IP على نقاط التحميل ⭐⭐⭐
_rate_lock = threading.Lock()
_rate_hits = {}  # ip -> [timestamps]


def is_rate_limited(client_ip):
    now = time.time()
    with _rate_lock:
        hits = _rate_hits.setdefault(client_ip, [])
        hits[:] = [t for t in hits if now - t < Config.RATE_LIMIT_WINDOW]
        if len(hits) >= Config.RATE_LIMIT_MAX_REQUESTS:
            return True
        hits.append(now)
        return False


# ⭐⭐⭐ MIDDLEWARE: تحديد مجلد المستخدم حسب IP ⭐⭐⭐
@app.before_request
def set_client_folder():
    """قبل كل طلب (عدا الملفات الثابتة)، نحدد مجلد المستخدم حسب IP"""
    if request.path.startswith(NO_SETUP_PREFIXES):
        return
    client_ip = Config.get_client_ip(request)
    downloader.setup_for_client(client_ip)


def get_index_html():
    """قراءة ملف index.html"""
    if os.path.exists(INDEX_HTML_PATH):
        with open(INDEX_HTML_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    return None


# ============================================
# Routes
# ============================================

@app.route('/')
def index():
    """الصفحة الرئيسية"""
    html_content = get_index_html()
    if html_content:
        return html_content
    
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>{Config.APP_NAME}</title>
        <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body style="background:#0a0012;color:#fff;font-family:'Cairo',sans-serif;padding:40px;text-align:center;">
        <h1 style="background:linear-gradient(135deg,#a78bfa,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">
            {Config.APP_NAME} v{Config.APP_VERSION}
        </h1>
        <p>✅ السيرفر يعمل بنجاح</p>
        <p>📁 مجلد التحميل: {downloader.download_folder}</p>
    </body>
    </html>
    """


@app.route('/api/download', methods=['POST'])
def api_download():
    """API التحميل العادي"""
    try:
        client_ip = Config.get_client_ip(request)
        if is_rate_limited(client_ip):
            return jsonify({'status': 'error', 'message': '⏳ طلبات كتيرة بوقت قصير، جرب بعد شوي'}), 429

        data = request.get_json(silent=True)
        if not data:
            return jsonify({'status': 'error', 'message': 'بيانات غير صالحة'}), 400

        url = data.get('url', '').strip()
        if not url:
            return jsonify({'status': 'error', 'message': Config.MESSAGES['invalid_url']}), 400

        result = downloader.download(url)

        if result['success']:
            return jsonify({
                'status': 'success',
                'message': Config.MESSAGES['download_success'],
                'filename': result['filename'],
                'title': result['title'],
                'platform': result['platform'],
                'duration': result['duration'],
                'filesize': result['filesize'],
                'filesize_mb': result['filesize_mb'],
                'quality': result.get('quality'),
                'thumbnail': result.get('thumbnail'),
                'download_url': f"/api/video/{quote(result['filename'], safe='')}"
            })
        else:
            return jsonify({
                'status': 'error',
                'message': result['error']
            }), 500

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/download/progress', methods=['POST'])
def api_download_progress():
    """API تحميل مع شريط تقدم (SSE)"""
    try:
        client_ip = Config.get_client_ip(request)
        if is_rate_limited(client_ip):
            return jsonify({'status': 'error', 'message': '⏳ طلبات كتيرة بوقت قصير، جرب بعد شوي'}), 429

        data = request.get_json(silent=True)
        if not data:
            return jsonify({'status': 'error', 'message': 'بيانات غير صالحة'}), 400

        url = data.get('url', '').strip()
        if not url:
            return jsonify({'status': 'error', 'message': Config.MESSAGES['invalid_url']}), 400

        download_id = str(uuid.uuid4())[:8]
        progress_queue = queue.Queue()
        
        def progress_callback(progress_data):
            try:
                progress_queue.put({
                    'type': 'progress',
                    'download_id': download_id,
                    'data': {
                        'percent': progress_data.get('percent', 0),
                        'speed': progress_data.get('speed', 0),
                        'speed_str': progress_data.get('speed_str', '0 B/s'),
                        'eta': progress_data.get('eta', '?'),
                        'status': progress_data.get('status', 'downloading')
                    }
                })
            except:
                pass
        
        def generate():
            def do_download():
                try:
                    result = downloader.download(url, progress_callback, download_id)
                    if result.get('success'):
                        result['message'] = Config.MESSAGES['download_success']
                        result['download_url'] = f"/api/video/{quote(result['filename'], safe='')}"
                    progress_queue.put({'type': 'complete', 'data': result})
                except Exception as e:
                    progress_queue.put({'type': 'complete', 'data': {'success': False, 'error': str(e)}})
            
            thread = threading.Thread(target=do_download)
            thread.daemon = True
            thread.start()
            
            while True:
                try:
                    msg = progress_queue.get(timeout=30)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    if msg.get('type') == 'complete':
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Access-Control-Allow-Origin': '*'
            }
        )
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/videos', methods=['GET'])
def api_videos():
    """API قائمة الفيديوهات"""
    try:
        videos = []
        folder = downloader.download_folder

        if folder and os.path.exists(folder):
            for f in os.listdir(folder):
                if f.lower().endswith(('.mp4', '.webm', '.mkv')):
                    filepath = os.path.join(folder, f)
                    size = os.path.getsize(filepath)
                    videos.append({
                        'name': f,
                        'url': f'/api/video/{f}',
                        'size': size,
                        'size_mb': round(size / (1024 * 1024), 1),
                        'created': os.path.getctime(filepath)
                    })

        videos.sort(key=lambda x: x['created'], reverse=True)

        return jsonify({
            'status': 'success',
            'videos': videos,
            'count': len(videos)
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/video/<path:filename>')
def api_video(filename):
    """تحميل فيديو - مع حماية من الوصول لملفات برا مجلد المستخدم"""
    try:
        filename = unquote(filename)
        filename = os.path.basename(filename)  # يمنع ../ وأي مسار خارج المجلد
        folder = downloader.download_folder

        if not filename or not folder:
            return jsonify({'error': 'الملف غير موجود'}), 404

        # ⭐ نتأكد إن المسار النهائي فعلياً داخل مجلد المستخدم (حماية إضافية)
        safe_folder = os.path.realpath(folder)
        direct_path = os.path.realpath(os.path.join(folder, filename))
        if not direct_path.startswith(safe_folder + os.sep):
            return jsonify({'error': 'طلب غير صالح'}), 400

        if os.path.exists(direct_path):
            return send_file(direct_path, as_attachment=True, download_name=filename)

        # ⭐ مطابقة دقيقة فقط (بدون تطابق جزئي) لمنع تسريب ملف غلط
        for f in os.listdir(folder):
            if f == filename:
                filepath = os.path.join(folder, f)
                return send_file(filepath, as_attachment=True, download_name=f)

        return jsonify({'error': 'الملف غير موجود'}), 404

    except Exception as e:
        return jsonify({'error': 'تعذر جلب الملف'}), 500


# امتدادات مدعومة لكل نوع وسائط (لصفحة "الملفات المحفوظة")
MEDIA_EXTS = {
    'video': ('.mp4', '.webm', '.mkv', '.mov', '.avi'),
    'audio': ('.m4a', '.mp3', '.opus', '.aac', '.wav'),
    'image': ('.jpg', '.jpeg', '.png', '.webp', '.gif'),
}


@app.route('/api/files', methods=['GET'])
def api_files():
    """API قائمة كل الملفات المحفوظة (فيديو/صوت/صورة) + مكان الحفظ"""
    try:
        folder = downloader.download_folder
        result = {'video': [], 'audio': [], 'image': []}

        if folder and os.path.exists(folder):
            for f in os.listdir(folder):
                low = f.lower()
                kind = None
                for k, exts in MEDIA_EXTS.items():
                    if low.endswith(exts):
                        kind = k
                        break
                if not kind:
                    continue
                filepath = os.path.join(folder, f)
                size = os.path.getsize(filepath)
                result[kind].append({
                    'name': f,
                    'url': f'/api/video/{quote(f, safe="")}',
                    'size_mb': round(size / (1024 * 1024), 2),
                    'created': os.path.getctime(filepath)
                })

        for k in result:
            result[k].sort(key=lambda x: x['created'], reverse=True)

        return jsonify({
            'status': 'success',
            'folder': folder,
            'files': result,
            'count': sum(len(v) for v in result.values())
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def api_stats():
    """API الإحصائيات"""
    try:
        stats = downloader.get_stats()
        videos = []
        total_size = 0
        folder = downloader.download_folder

        if folder and os.path.exists(folder):
            for f in os.listdir(folder):
                if f.lower().endswith(('.mp4', '.webm', '.mkv')):
                    total_size += os.path.getsize(os.path.join(folder, f))
                    videos.append(f)

        return jsonify({
            'status': 'success',
            'total': len(videos),
            'total_size_mb': round(total_size / (1024 * 1024), 1),
            'today': stats.get('today', 0),
            'download_folder': folder
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def api_health():
    """فحص صحة السيرفر"""
    return jsonify({
        'status': 'ok',
        'app': Config.APP_NAME,
        'version': Config.APP_VERSION,
        'download_folder': downloader.download_folder,
        'supported_platforms': list(Config.SUPPORTED_PLATFORMS.keys())
    })


# ⭐⭐⭐ حالة التحديث التلقائي (تُقرأ من الواجهة عند كل فتح للتطبيق) ⭐⭐⭐
_update_state = {'checking': False, 'updated': False, 'version': None, 'message': ''}


def _run_ytdlp_update():
    """تحديث yt-dlp بالخلفية بدون ما يعطّل تشغيل السيرفر"""
    _update_state['checking'] = True
    try:
        import yt_dlp
        before = yt_dlp.version.__version__
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp',
             '-q', '--break-system-packages'],
            timeout=90, capture_output=True
        )
        # إعادة قراءة النسخة بعد التحديث
        import importlib
        import yt_dlp.version as v
        importlib.reload(v)
        after = v.__version__
        _update_state['version'] = after
        _update_state['updated'] = (after != before)
        _update_state['message'] = f'yt-dlp v{after}'
    except Exception as e:
        _update_state['message'] = f'تعذّر التحديث التلقائي: {e}'
    finally:
        _update_state['checking'] = False


@app.route('/api/check-update', methods=['GET'])
def api_check_update():
    """الواجهة تستدعي هذا عند كل فتح للتطبيق لمعرفة حالة التحديث"""
    return jsonify({'status': 'success', **_update_state})


if Config.AUTO_UPDATE_YTDLP:
    threading.Thread(target=_run_ytdlp_update, daemon=True).start()


# ============================================
# تشغيل السيرفر
# ============================================

def main():
    print(Config.get_banner())
    print(f"\n{'='*55}")
    print(f"🚀 {Config.APP_NAME} v{Config.APP_VERSION}")
    print(f"📁 مجلد المستخدمين: {Config.USERS_FOLDER}")
    print(f"🌐 http://localhost:{Config.PORT}")
    print(f"🌍 http://{Config.get_local_ip()}:{Config.PORT}")
    print(f"🔒 كل جهاز له مجلده الخاص (حسب IP)")
    print(f"🔴 Ctrl+C لإيقاف السيرفر")
    print(f"{'='*55}\n")

    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        threaded=True
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n🛑 {Config.MESSAGES['server_stop']}")
        sys.exit(0)
