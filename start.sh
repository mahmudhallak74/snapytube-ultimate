#!/data/data/com.termux/files/usr/bin/bash
# ╔═══════════════════════════════════════════════════════╗
# ║       🎬 SnapYTube-Ultimate — ملف التشغيل             ║
# ║       محلي + عالمي — رابط ثابت                        ║
# ╚═══════════════════════════════════════════════════════╝

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
B='\033[0;34m'; P='\033[0;35m'; C='\033[0;36m'
W='\033[1;37m'; BOLD='\033[1m'; NC='\033[0m'

# ═══ الإعدادات ═══════════════════════════════════════════
PORT=5001
TUNNEL_NAME="SnapYTube_Ultimate"
FIXED_DOMAIN="https://snapytube-ultimate.snaptube.com"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# ══════════════════════════════════════════════════════════

cd "$PROJECT_DIR"

clear
echo -e "${P}${BOLD}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   🎬 SnapYTube-Ultimate v4.0             ║"
echo "  ║   منصة تحميل الفيديو متعددة المنصات     ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ═══ فحص الملفات ═══
MISSING=0
for f in run.py config.py downloader.py index.html; do
    if [ ! -f "$PROJECT_DIR/$f" ]; then
        echo -e "${R}❌ الملف $f مفقود!${NC}"
        MISSING=1
    fi
done
[ $MISSING -eq 1 ] && echo -e "${Y}شغّل أولاً: bash setup.sh${NC}" && exit 1

if ! python -c "import flask" 2>/dev/null; then
    echo -e "${R}❌ Flask غير مثبت! شغّل: bash setup.sh${NC}"
    exit 1
fi

# ═══ تحديث yt-dlp ═══
echo -e "${C}🔄 تحديث yt-dlp...${NC}"
python -m pip install -U yt-dlp -q --break-system-packages 2>/dev/null \
    && echo -e "${G}✅ yt-dlp محدّث${NC}" \
    || echo -e "${Y}⚠️  تخطي التحديث${NC}"

# ═══ IP المحلي ═══
LOCAL_IP=$(python -c "
import socket
try:
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()
except: print('127.0.0.1')
" 2>/dev/null)

# ═══ إحصائيات ═══
VIDEO_COUNT=$(find "$PROJECT_DIR/users" \( -name "*.mp4" -o -name "*.mkv" -o -name "*.webm" \) 2>/dev/null | wc -l)
DISK_USED=$(du -sh "$PROJECT_DIR/users" 2>/dev/null | cut -f1)
YT_VER=$(python -c "import yt_dlp; print(yt_dlp.version.__version__)" 2>/dev/null)

echo ""
echo -e "${W}════════════════════════════════════════${NC}"
echo -e "  ${BOLD}📊 إحصائيات${NC}"
echo -e "  ${G}🎬 فيديوهات:${NC}  ${VIDEO_COUNT:-0}"
echo -e "  ${G}💾 مساحة:${NC}     ${DISK_USED:-0}"
echo -e "  ${G}🔧 yt-dlp:${NC}    v${YT_VER:-غير معروف}"
echo -e "${W}════════════════════════════════════════${NC}"
echo ""
echo -e "  ${R}▶${NC} YouTube 4K   ${Y}▶${NC} TikTok"
echo -e "  ${P}▶${NC} Instagram   ${B}▶${NC} Facebook"
echo -e "  ${C}▶${NC} Twitter/X   ${G}▶${NC} Vimeo & CapCut"
echo ""

# ═══════════════════════════════════════════
# تشغيل Flask
# ═══════════════════════════════════════════
echo -e "${C}🚀 تشغيل السيرفر...${NC}"
python run.py > "$PROJECT_DIR/flask.log" 2>&1 &
FLASK_PID=$!
sleep 3

if ! kill -0 $FLASK_PID 2>/dev/null; then
    echo -e "${R}❌ Flask ما اشتغل!${NC}"
    echo -e "${Y}السبب:${NC}"
    tail -5 "$PROJECT_DIR/flask.log"
    exit 1
fi
echo -e "${G}✅ Flask شغال${NC}"

# ═══════════════════════════════════════════
# تشغيل Cloudflare Tunnel
# ═══════════════════════════════════════════
TUNNEL_PID=""
GLOBAL_URL=""

if ! command -v cloudflared &>/dev/null; then
    echo -e "${Y}⚠️  cloudflared غير مثبت${NC}"
    echo -e "${Y}   للتثبيت: pkg install cloudflared${NC}"
else
    # فحص هل الـ tunnel مضبوط (يعني عنده cert.pem)
    if [ -f "$HOME/.cloudflared/cert.pem" ] && \
       [ -f "$HOME/.cloudflared/${TUNNEL_NAME}.json" -o \
         -f "$HOME/.cloudflared/33dec31a-f0a0-4f19-9329-058f57064784.json" ]; then
        # رابط ثابت من الـ tunnel المضبوط
        echo -e "${C}🌐 تشغيل النفق الثابت — $FIXED_DOMAIN${NC}"
        cloudflared tunnel run SnapYTube_Ultimate \
            
            --no-autoupdate \
            > "$PROJECT_DIR/tunnel.log" 2>&1 &
        TUNNEL_PID=$!
        GLOBAL_URL="$FIXED_DOMAIN"
    else
        # لا يوجد إعداد — استخدم رابط مؤقت مجاني
        echo -e "${Y}⚠️  النفق الثابت غير مضبوط — رابط مؤقت${NC}"
        cloudflared tunnel --url http://localhost:$PORT \
            --no-autoupdate \
            > "$PROJECT_DIR/tunnel.log" 2>&1 &
        TUNNEL_PID=$!

        # انتظر الرابط
        echo -ne "${C}⏳ انتظار الرابط"
        for i in $(seq 1 20); do
            GLOBAL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' \
                "$PROJECT_DIR/tunnel.log" 2>/dev/null | head -1)
            [ -n "$GLOBAL_URL" ] && break
            echo -n "."
            sleep 1
        done
        echo ""
        [ -n "$GLOBAL_URL" ] && echo "$GLOBAL_URL" > "$PROJECT_DIR/global_url.txt"
    fi
fi

# ═══════════════════════════════════════════
# عرض الروابط
# ═══════════════════════════════════════════
echo ""
echo -e "${W}════════════════════════════════════════${NC}"
echo -e "  ${BOLD}🌐 عناوين السيرفر${NC}"
echo -e "  ${G}📱 محلي:${NC}    ${C}http://${LOCAL_IP}:${PORT}${NC}"
if [ -n "$GLOBAL_URL" ]; then
    echo -e "  ${G}🌍 عالمي:${NC}   ${C}${BOLD}${GLOBAL_URL}${NC}"
else
    echo -e "  ${Y}🌍 عالمي:${NC}   لم يبدأ — شوف tunnel.log"
fi
echo -e "${W}════════════════════════════════════════${NC}"
echo ""

# QR Code
if [ -n "$GLOBAL_URL" ]; then
    if command -v qrencode &>/dev/null; then
        echo -e "${Y}${BOLD}📲 QR Code:${NC}"
        qrencode -t ANSIUTF8 -m 1 "$GLOBAL_URL"
        echo ""
    elif python -c "import qrcode" 2>/dev/null; then
        echo -e "${Y}${BOLD}📲 QR Code:${NC}"
        python -c "
import qrcode,sys
qr=qrcode.QRCode(border=1)
qr.add_data(sys.argv[1])
qr.make(fit=True)
qr.print_ascii(invert=True)
" "$GLOBAL_URL" 2>/dev/null
        echo ""
    fi
fi

echo -e "  ${Y}⚡ اضغط ${BOLD}Ctrl+C${NC}${Y} لإيقاف كل شي${NC}"
echo -e "  ${Y}📁 ملفاتك في:${NC} users/device_<IP>/downloads/"
echo ""

# ═══ إيقاف نظيف ═══
cleanup() {
    echo -e "\n${R}${BOLD}🛑 جاري الإيقاف...${NC}"
    [ -n "$FLASK_PID" ]  && kill "$FLASK_PID"  2>/dev/null
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
    echo -e "${G}✅ تم الإيقاف${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

wait "$FLASK_PID"
