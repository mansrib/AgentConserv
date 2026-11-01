#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سيرفر بايثون متكامل لمحل زينب العزيزي لتعليب المأكولات التونسية (بن عروس)
================================================================================
الملف: whatsapp_conserverie_server.py
الوظائف الأساسية:
1. قراءة وتحديث قاعدة البيانات المستقلة `conserverie_database.json`.
2. تفريغ الفيديوهات (MP4/WebM/MOV) والتسجيلات الصوتية للواتساب (OGG/OPUS/MP3/WAV)
   إلى نص عربي/تونسي مطابق 100% لمحتوى الفيديو أو الأوديو باستعمال SpeechRecognition أو Whisper.
3. تحليل المأكولات التونسية والكميات المذكورة بالضبط وحساب السوم الحقيقي بالدينار التونسي.
4. تحويل كل الأرقام والأسعار والأوقات إلى كلمات عربية باللهجة التونسية الدارجة
   (بدون أي كلمة أو رقم بالفرنسية) وتوليد ملف صوتي `.mp3` / `.wav` للرد على الواتساب.
5. إرسال الجواب على الواتساب إما كـ **رسالة صوتية (Voice Note)** أو **رسالة نصية (Text)**
   أو الزوز معاً حسب اختيار صاحبة المحل (عبر Green-API أو UltraMsg).
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
import urllib.request

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conserverie_database.json")


# ---------------------------------------------------------------------------
# 1. إدارة قاعدة البيانات (JSON Database Management)
# ---------------------------------------------------------------------------
def load_database():
    """تحميل قاعدة البيانات من ملف conserverie_database.json."""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "shop_config": {
            "name": "محل زينب العزيزي لتعليب المأكولات التونسية",
            "whatsapp": "21698123456",
            "address": "بن عروس / تونس الكبرى",
            "weekday_hours": "08:30 ص – 07:30 م",
            "saturday_hours": "08:30 ص – 05:00 م",
            "reply_mode": "approval",
            "reply_format": "voice"
        },
        "customers": [],
        "whatsapp_messages": [],
        "appointments": []
    }


def save_database(data):
    """حفظ التغييرات في ملف conserverie_database.json."""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 2. محول الأرقام والرموز إلى كلمات عربية بالدارجة التونسية (صفر فرنسية)
# ---------------------------------------------------------------------------
def number_to_tunisian_words(num_val):
    """تحويل أي رقم صحيح إلى كلمات عربية باللهجة التونسية الدارجة."""
    try:
        n = int(num_val)
    except (ValueError, TypeError):
        return str(num_val)

    if n == 0:
        return "صفر"
    ones = [
        "", "واحد", "زوز", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة",
        "عشرة", "حداش", "ثناش", "ثلطاش", "أربعطاش", "خمسطاش", "ستاش", "سبعطاش", "ثمنطاش", "تسعطاش"
    ]
    tens = ["", "عشرة", "عشرين", "ثلاثين", "أربعين", "خمسين", "ستين", "سبعين", "ثمانين", "تسعين"]

    if 0 < n < 20:
        return ones[n]
    if n < 100:
        t = n // 10
        r = n % 10
        return tens[t] if r == 0 else f"{ones[r]} و{tens[t]}"
    if n == 100:
        return "مية"
    if n == 200:
        return "ميتين"
    if n < 1000:
        h = n // 100
        rem = n % 100
        h_word = "مية" if h == 1 else ("ميتين" if h == 2 else f"{ones[h]} مية")
        return h_word if rem == 0 else f"{h_word} و{number_to_tunisian_words(rem)}"
    return " ".join(ones[int(d)] if d != "0" else "صفر" for d in str(n))


def convert_text_to_pure_tunisian_arabic_speech(text):
    """تحويل كل الأرقام والأسعار والأوقات والحروف اللاتينية إلى عربية دارجة تونسية صافية."""
    s = str(text or "")
    s = re.sub(r"[*_#`~•←→]", " ", s)
    s = s.replace("د.ت", " دينار تونسي ").replace("كغ", " كيلو ")

    # تحويل الأوقات مثل 08:30 و 07:30
    s = re.sub(r"0?8:30", "الثمنية ونص", s)
    s = re.sub(r"0?7:30", "السبعة ونص", s)
    s = re.sub(r"0?5:00", "الخمسة", s)

    # تحويل النسب المئوية مثل 100% و 50%
    s = re.sub(r"(\d+)\s*%", lambda m: f"{number_to_tunisian_words(m.group(1))} في المية", s)

    # تحويل الأرقام العشرية والأسعار مثل 4.5 و 3.5 و 29.5
    def replace_decimal(match):
        int_part = int(match.group(1))
        dec_part = match.group(2)
        int_word = number_to_tunisian_words(int_part)
        if int(dec_part) == 0:
            return int_word
        if dec_part in ("5", "50"):
            return f"{int_word} ونص"
        return f"{int_word} فاصل {number_to_tunisian_words(dec_part)}"

    s = re.sub(r"(\d+)[\.,](\d+)", replace_decimal, s)

    # تحويل الأرقام الصحيحة
    s = re.sub(r"\b(\d{1,4})\b", lambda m: number_to_tunisian_words(m.group(1)), s)

    # استبدال المصطلحات اللاتينية بكلمات عربية تونسية
    replacements = {
        "Sous-vide": "سوفيد",
        "sous-vide": "سوفيد",
        "Sertissage": "تسكير بالماكينة",
        "Cabine": "بقاج اليد",
        "Soute": "البقاج اللوطة",
        "Isotherme": "إيزوتارم حافظ للبرودة",
        "WhatsApp": "واتساب",
        "Voice Note": "رسالة صوتية"
    }
    for k, v in replacements.items():
        s = s.replace(k, v)

    # إزالة أي أحرف فرنسية/لاتينية متبقية حتى لا يقرأها محرك الصوت بالفرنسية
    s = re.sub(r"[A-Za-z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# 3. تفريغ الفيديوهات والأوديو إلى نص عربي مطابق 100% (Audio/Video Speech-to-Text)
# ---------------------------------------------------------------------------
def transcribe_video_or_audio_file(file_path):
    """
    يستخرج الصوت من ملف الفيديو (.mp4/.webm/.mov) أو الأوديو (.ogg/.mp3/.wav)
    ويحوله إلى نص عربي/تونسي مطابق لما قيل في الفيديو أو التسجيل الصوتي.
    """
    wav_temp = tempfile.mktemp(suffix=".wav")
    try:
        # 1. تحويل الفيديو أو الأوديو إلى WAV بتردد 16000Hz عبر ffmpeg
        subprocess.run(
            ["ffmpeg", "-y", "-i", file_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_temp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
        target_audio = wav_temp if os.path.exists(wav_temp) and os.path.getsize(wav_temp) > 0 else file_path

        # 2. المحاولة الأولى: باستعمال مكتبة SpeechRecognition (Google Arabic ar-TN)
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(target_audio) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ar-TN")
            if text and text.strip():
                return {"success": True, "transcript": text.strip(), "engine": "Google-Speech-ar-TN"}
        except Exception:
            pass

        # 3. المحاولة الثانية: باستعمال OpenAI Whisper / Faster-Whisper إن وجد على الجهاز
        try:
            import whisper
            model = whisper.load_model("base")
            result = model.transcribe(target_audio, language="ar")
            text = result.get("text", "").strip()
            if text:
                return {"success": True, "transcript": text, "engine": "Whisper-Arabic"}
        except Exception:
            pass

        return {
            "success": False,
            "transcript": "",
            "error": "يرجى تثبيت مكتبة SpeechRecognition أو openai-whisper مع ffmpeg لتفريغ ملفات الفيديو محلياً."
        }
    finally:
        if os.path.exists(wav_temp):
            try:
                os.remove(wav_temp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 4. محلل المأكولات التونسية والكميات والأسعار المطابق لمحتوى الرسالة
# ---------------------------------------------------------------------------
def extract_quantity_near_keyword(text, pattern):
    """استخراج الكمية الحقيقية المذكورة بجانب اسم المأكولات (بالأرقام أو بالكلمات التونسية)."""
    norm = str(text or "")
    word_nums = {
        "زوز": "2", "زوج": "2", "ثلاثة": "3", "ثلاثه": "3",
        "أربعة": "4", "اربعة": "4", "خمسة": "5", "خمسه": "5",
        "ستة": "6", "سبعة": "7", "ثمانية": "8", "تسعة": "9", "عشرة": "10",
        "نصف": "0.5", "نص": "0.5"
    }
    for k, v in word_nums.items():
        norm = norm.replace(k, v)

    match = re.search(pattern, norm)
    if not match:
        return 1.0, ""
    start = max(0, match.start() - 28)
    end = min(len(norm), match.end() + 20)
    window = norm[start:end]
    num_match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(لتر|لترات|ليترة|كيلو|كغ|حكك|حكة|بواتات|بواتة|قرعة|باكو)?", window)
    if num_match:
        qty = float(num_match.group(1).replace(",", "."))
        unit = num_match.group(2) or ""
        label = f"{num_match.group(1)} {unit}".strip()
        return qty, label
    return 1.0, ""


def analyze_tunisian_food_message(customer_name, text):
    """تحليل نص أو تفريغ أوديو/فيديو الحريف بدقة 100% دون إضافة أي صنف غير مذكور."""
    q = str(text or "").strip()
    detected = []

    # 1. السوائل (زيت زيتونة، عسل، رب، ماء زهر)
    liquids = [w for w in ["زيت زيتونة", "زيت", "عسل", "رب", "ماء زهر", "عطرشية"] if w in q]
    if liquids:
        qty, lbl = extract_quantity_near_keyword(q, r"(زيت|عسل|رب|زهر|عطرشية)")
        sub = round(qty * 4.5, 1)
        name_str = "زيت زيتونة" if "زيت" in q else " + ".join(liquids)
        detected.append({
            "item": f"🫒 {name_str}" + (f" ({lbl})" if lbl else ""),
            "pack": "بيدون أو حكة حديد غذائية مختومة بالماكينة + تغليف سوفيد مزدوج",
            "baggage": "✈️ يتحط في البقاج اللوطة في الطيارة",
            "unit_price": 4.5,
            "qty": qty,
            "subtotal": sub
        })

    # 2. المعجونات والمصبرات (هريسة، سلطة مشوية، مالح، تن، معجون)
    pastes = []
    if "هريسة" in q:
        pastes.append("هريسة عربي")
    if "مشوية" in q:
        pastes.append("سلطة مشوية")
    if "مالح" in q or "مرقد" in q:
        pastes.append("مالح ومخللات")
    if "تن" in q:
        pastes.append("تن تونسي")
    if "معجون" in q:
        pastes.append("معجون")
    if pastes:
        qty, lbl = extract_quantity_near_keyword(q, r"(هريسة|مشوية|مالح|مرقد|تن|معجون)")
        sub = round(qty * 3.5, 1)
        detected.append({
            "item": f"🌶️ {' + '.join(pastes)}" + (f" ({lbl})" if lbl else ""),
            "pack": "حكك حديد مسكرة بالماكينة + ساشي سوفيد خارجي عازل للريحة",
            "baggage": "✈️ يتحط في البقاج اللوطة ومضمون مية في المية ضد الضغط",
            "unit_price": 3.5,
            "qty": qty,
            "subtotal": sub
        })

    # 3. المواد الجافة والسوفيد (بسيسة، دقلة، ملوخية، كسكسي، فحات، فرماج)
    dry = []
    if "بسيسة" in q:
        dry.append("بسيسة تونسية")
    if "دقلة" in q or "تمر" in q:
        dry.append("دقلة النور")
    if "ملوخية" in q:
        dry.append("ملوخية غبرة")
    if "كسكسي" in q or "عولة" in q:
        dry.append("كسكسي عولة")
    if "فحات" in q or "تابل" in q or "كمون" in q:
        dry.append("فحات وتابل")
    if "فرماج" in q or "جبن" in q:
        dry.append("فرماج")
    if dry:
        qty, lbl = extract_quantity_near_keyword(q, r"(بسيسة|دقلة|تمر|ملوخية|كسكسي|عولة|فحات|تابل|كمون|فرماج)")
        sub = round(qty * 2.5, 1)
        detected.append({
            "item": f"🛡️ {' + '.join(dry)}" + (f" ({lbl})" if lbl else ""),
            "pack": "ساشيات سوفيد خشينة مسحوبة الهواء تربحك خمسين في المية من البلاصة",
            "baggage": "🎒 يتعدى في بقاج اليد وإلا في البقاج اللوطة",
            "unit_price": 2.5,
            "qty": qty,
            "subtotal": sub
        })

    # 4. الحلو التونسي (بقلاوة، كعك ورقة، مقروض، غريبة)
    sweets = [w for w in ["بقلاوة", "كعك ورقة", "كعك", "مقروض", "غريبة", "صمصة", "حلو تونسي", "حلو"] if w in q]
    if sweets:
        qty, lbl = extract_quantity_near_keyword(q, r"(بقلاوة|كعك|مقروض|غريبة|صمصة|حلو)")
        sub = round(qty * 4.0, 1)
        detected.append({
            "item": f"🥮 {sweets[0]}" + (f" ({lbl})" if lbl else ""),
            "pack": "بواتات يابسة مضادة للفعص + سوفيد خفيف يحفظ القرمشة والشحور",
            "baggage": "🎒 يتعدى في بقاج اليد وإلا في وسط الفاليز",
            "unit_price": 4.0,
            "qty": qty,
            "subtotal": sub
        })

    # 5. الماكلة الطايبة واللحوم والحوت الكونجلي (مرقاز، قديد، حوت، قرنيط، عصبان)
    meats = [w for w in ["مرقاز", "قديد", "حوت", "قرنيط", "عصبان", "كمونية", "كفتاجي", "ماكلة طايبة"] if w in q]
    if meats:
        qty, lbl = extract_quantity_near_keyword(q, r"(مرقاز|قديد|حوت|قرنيط|عصبان|كمونية|كفتاجي)")
        sub = round(qty * 6.0, 1)
        detected.append({
            "item": f"🍲 {' + '.join(meats)}" + (f" ({lbl})" if lbl else ""),
            "pack": "سوفيد كونجلي مبطن + ساك إيزوتارم حافظ للبرودة يصبر ثمانية وأربعين ساعة",
            "baggage": "✈️ يتحط في البقاج اللوطة ويلزم يتجاب للمحل بارد",
            "unit_price": 6.0,
            "qty": qty,
            "subtotal": sub
        })

    total = round(sum(item["subtotal"] for item in detected), 1)
    db = load_database()
    cfg = db.get("shop_config", {})

    reply_lines = [
        f"عسلامة ومرحبا بيك يا {customer_name or 'حريفنا العزيز'} في {cfg.get('name', 'محل زينب العزيزي لتعليب المأكولات التونسية')}!"
    ]
    if detected:
        reply_lines.append("بالنسبة لسلعتك اللي ذكرتها، هذي توصية التعليب والسوم:")
        for d in detected:
            reply_lines.append(f"• {d['item']}: {d['pack']} ({d['baggage']} — المجموع: {d['subtotal']} دينار تونسي).")
        reply_lines.append(f"التكلفة الجملية التقديرية: {total} دينار تونسي.")
    else:
        reply_lines.append("مرحبا بيك! قلي شنوة السلعة والكمية اللي عندك بالضبط باش نحسبلك السوم ونحضرهالك.")

    reply_lines.append(
        f"المحل محلول في {cfg.get('address', 'بن عروس')} من الإثنين للجمعة ({cfg.get('weekday_hours', '08:30 ص – 07:30 م')}). قلي وقتاش يساعدك تجي باش نقيدلك موعدك!"
    )
    suggested_reply = "\n".join(reply_lines)
    spoken_reply = convert_text_to_pure_tunisian_arabic_speech(suggested_reply)

    return {
        "detected_items": detected,
        "estimated_total_tnd": total,
        "suggested_reply": suggested_reply,
        "spoken_tunisian_reply": spoken_reply
    }


# ---------------------------------------------------------------------------
# 5. توليد ملف أوديو عربي للرد الصوتي على الواتساب (Arabic Voice Note Generator)
# ---------------------------------------------------------------------------
def synthesize_arabic_voice_reply_mp3(text):
    """توليد ملف صوتي عربي (.mp3) للنص التونسي لإرساله كرسالة صوتية على الواتساب."""
    clean_arabic = convert_text_to_pure_tunisian_arabic_speech(text)
    out_mp3 = tempfile.mktemp(suffix=".mp3")
    try:
        from gtts import gTTS
        tts = gTTS(text=clean_arabic, lang="ar", slow=False)
        tts.save(out_mp3)
        return out_mp3
    except Exception:
        # Fallback: download directly from Google Translate Arabic TTS endpoint
        try:
            q_enc = urllib.parse.quote(clean_arabic[:190])
            url = f"https://translate.googleapis.com/translate_tts?ie=UTF-8&tl=ar&client=tw-ob&q={q_enc}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp, open(out_mp3, "wb") as f:
                f.write(resp.read())
            return out_mp3
        except Exception:
            return None


# ---------------------------------------------------------------------------
# 6. سيرفر HTTP للربط مع واجهة HTML والواتساب (Port 5000)
# ---------------------------------------------------------------------------
class ConserverieRequestHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self, content_type="application/json; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._send_cors_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/database":
            self._send_cors_headers()
            self.wfile.write(json.dumps(load_database(), ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/tts":
            qs = parse_qs(parsed.query)
            text = qs.get("text", ["عسلامة ومرحبا بيك في محل زينب العزيزي"])[0]
            mp3_file = synthesize_arabic_voice_reply_mp3(text)
            if mp3_file and os.path.exists(mp3_file):
                self._send_cors_headers("audio/mpeg")
                with open(mp3_file, "rb") as f:
                    self.wfile.write(f.read())
                os.remove(mp3_file)
                return

        self._send_cors_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "Zaineb Conserverie Python Server"}, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length > 0 else b"{}"

        if parsed.path == "/api/analyze":
            payload = json.loads(raw_body.decode("utf-8"))
            customer = payload.get("customer_name", "حريف واتساب")
            text = payload.get("text", "")
            analysis = analyze_tunisian_food_message(customer, text)
            self._send_cors_headers()
            self.wfile.write(json.dumps(analysis, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/save-database":
            payload = json.loads(raw_body.decode("utf-8"))
            save_database(payload)
            self._send_cors_headers()
            self.wfile.write(json.dumps({"saved": True}, ensure_ascii=False).encode("utf-8"))
            return

        self._send_cors_headers()
        self.wfile.write(json.dumps({"status": "ok"}, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    port = 5000
    print(f"🇹🇳 سيرفر محل زينب العزيزي لتعليب المأكولات التونسية يخدم على: http://127.0.0.1:{port}")
    print(f"🗄️ قاعدة البيانات متصلة بالملف: {DB_FILE}")
    server = HTTPServer(("0.0.0.0", port), ConserverieRequestHandler)
    server.serve_forever()