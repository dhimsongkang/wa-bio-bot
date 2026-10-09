import os
import re
import time
import json
import tempfile
import base64
import threading
from datetime import datetime

import telebot
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# ==========================================
# 1. MASUKKAN TOKEN BOT TELEGRAM KAMU DI SINI
# ==========================================
BOT_TOKEN = '8777369357:AAEGc9-vHNlej3dKYdso6pSAiOA0qwrNyAs' 

bot = telebot.TeleBot(BOT_TOKEN)

# Global Driver
driver = None
driver_lock = threading.Lock()
checking_active = False

def normalize_number(raw: str) -> str:
    digits = re.sub(r'\D', '', raw.strip())
    if digits.startswith('0'):
        digits = '62' + digits[1:]
    return digits

def start_driver():
    opts = Options()
    wa_profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wa_chrome_profile_bot')
    os.makedirs(wa_profile, exist_ok=True)
    opts.add_argument(f'--user-data-dir={wa_profile}')
    opts.add_argument('--window-size=1200,800')
    import platform
    if platform.system() == 'Linux':
        opts.binary_location = '/usr/bin/chromium'

    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--disable-software-rasterizer')
    opts.add_argument('--disable-extensions')

    from webdriver_manager.core.os_manager import ChromeType
    try:
        service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
    except Exception:
        service = Service()
    drv = webdriver.Chrome(service=service, options=opts)
    drv.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    drv.get('https://web.whatsapp.com')
    return drv

def wait_for_login(drv, chat_id, timeout=120):
    bot.send_message(chat_id, "⏳ Membuka WhatsApp Web... Tunggu sebentar.")
    start = time.time()
    last_qr_b64 = None
    qr_msg_id = None
    last_debug_time = time.time()
    
    while time.time() - start < timeout:
        try:
            # Check QR
            try:
                qr_canvas = drv.find_element(By.CSS_SELECTOR, 'canvas')
                png = qr_canvas.screenshot_as_png
                b64 = base64.b64encode(png).decode()
                if b64 != last_qr_b64:
                    last_qr_b64 = b64
                    msg = bot.send_photo(chat_id, png, caption="📸 Silakan scan QR Code ini menggunakan WhatsApp di HP kamu!")
                    if qr_msg_id:
                        try: bot.delete_message(chat_id, qr_msg_id)
                        except: pass
                    qr_msg_id = msg.message_id
            except NoSuchElementException:
                pass

            # Check Logged In
            try:
                drv.find_element(By.CSS_SELECTOR, '#app div[data-tab="3"], div[aria-label="Search input textbox"], div[title="New chat"], header img')
                bot.send_message(chat_id, "✅ Login berhasil!")
                if qr_msg_id:
                    try: bot.delete_message(chat_id, qr_msg_id)
                    except: pass
                return True
            except NoSuchElementException:
                pass
                
            # DEBUG: Send full screen every 20 seconds if no QR found
            if time.time() - last_debug_time > 20 and not last_qr_b64:
                try:
                    bot.send_photo(chat_id, drv.get_screenshot_as_png(), caption="[DEBUG] Layar WhatsApp Web saat ini.")
                except Exception:
                    pass
                last_debug_time = time.time()
                
        except WebDriverException as e:
            bot.send_message(chat_id, f"⚠️ [DEBUG ERROR] Browser Crash/Tertutup: {str(e)[:200]}")
            break
        time.sleep(1.5)
    return False

# ==========================================
# (Fungsi scrap get_whatsapp_bio dan inject sama seperti sebelumnya)
# ==========================================
def get_whatsapp_bio(drv, number: str) -> dict:
    result = {
        'number': number, 'registered': False, 'name': '', 'bio': '',
        'is_business': False, 'business_category': '', 'business_description': '',
        'business_email': '', 'business_website': '', 'business_address': '',
        'account_type': 'Unknown', 'status': 'not_found', 'error': ''
    }
    try:
        url = f'https://web.whatsapp.com/send?phone={number}&text&app_absent=0'
        drv.get(url)
        time.sleep(3)

        # Invalid check
        try:
            popups = drv.find_elements(By.CSS_SELECTOR, 'div[data-animate-modal-popup="true"]')
            for popup in popups:
                popup_text = popup.text.lower()
                if any(w in popup_text for w in ['invalid', 'tidak valid', 'not found']):
                    try:
                        popup.find_element(By.CSS_SELECTOR, 'div[role="button"]').click()
                    except: pass
                    result['status'] = 'invalid'
                    return result
        except: pass

        chat_loaded = False
        for selector in ['div[contenteditable="true"][data-tab="10"]', 'footer div[contenteditable="true"]', 'div[role="textbox"][data-tab="10"]']:
            try:
                WebDriverWait(drv, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                chat_loaded = True
                break
            except: continue

        if not chat_loaded:
            result['status'] = 'timeout'
            return result

        result['registered'] = True
        time.sleep(1)

        # Name
        try:
            header_el = drv.find_element(By.CSS_SELECTOR, 'header span[title]')
            result['name'] = header_el.get_attribute('title') or header_el.text or ''
        except: pass

        # Open Panel
        try:
            clicked = False
            for sel in ['header div[data-testid="conversation-info-header"]', 'header img[data-testid="image-thumb"]', 'header span[title]']:
                try:
                    drv.find_element(By.CSS_SELECTOR, sel).click()
                    clicked = True
                    break
                except: continue

            if clicked:
                time.sleep(2)
                panel_text = ''
                try:
                    panels = drv.find_elements(By.CSS_SELECTOR, 'div[data-testid="contact-info-drawer"]')
                    if not panels: panels = drv.find_elements(By.CSS_SELECTOR, 'span[data-testid="drawer-right"]')
                    for p in panels:
                        panel_text = p.text
                        break
                except: pass

                # Bio
                try:
                    sections = drv.find_elements(By.CSS_SELECTOR, 'div[class*="copyable-text"]')
                    for sec in sections:
                        t = sec.text.strip()
                        if t and t != result['name'] and len(t) > 2 and t not in ['+' + number, number]:
                            result['bio'] = t
                            break
                except: pass

                # Business detect
                if any(ind.lower() in panel_text.lower() for ind in ['business', 'bisnis', 'katalog', 'category']):
                    result['is_business'] = True
                    result['account_type'] = 'Business'
                    
                    try:
                        spans = drv.find_elements(By.CSS_SELECTOR, 'span[dir="auto"]')
                        for sp in spans:
                            txt = sp.text.strip()
                            if any(cat in txt.lower() for cat in ['shopping', 'belanja', 'retail', 'health', 'finance', 'automotive', 'apparel', 'lainnya', 'other']):
                                result['business_category'] = txt
                                break
                    except: pass

                if not result['is_business']:
                    if any(ind.lower() in panel_text.lower() for ind in ['ai', 'bot', 'agent', 'channel']):
                        result['account_type'] = 'AI Agent'
                    else:
                        result['account_type'] = 'Personal'

                try:
                    drv.find_element(By.CSS_SELECTOR, 'div[data-testid="btn-closer-drawer"]').click()
                except: pass
        except: pass

        result['status'] = 'found'
        return result
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        return result

def generate_report_text(filename: str, results: list) -> str:
    total = len(results)
    terdaftar = [r for r in results if r['registered']]
    tidak_terdaftar = total - len(terdaftar)
    
    punya_bio = [r for r in terdaftar if r['bio']]
    tanpa_bio = len(terdaftar) - len(punya_bio)
    bisnis = [r for r in terdaftar if r['is_business']]
    ai = [r for r in terdaftar if r['account_type'] == 'AI Agent']
    
    pct_reg = round((len(terdaftar) / total) * 100, 1) if total > 0 else 0
    pct_unreg = round((tidak_terdaftar / total) * 100, 1) if total > 0 else 0

    laporan = f"========================\n"
    laporan += f"  LAPORAN /cekbio — {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    laporan += f"========================\n"
    laporan += f"  File sumber : {filename}\n"
    laporan += f"  Total input : {total} nomor\n"
    laporan += f"========================\n\n"
    laporan += f"STATISTIK RINGKASAN\n-------------------\n"
    laporan += f"  Terdaftar WA      : {len(terdaftar)}  ({pct_reg}%)\n"
    laporan += f"  Tidak Terdaftar   : {tidak_terdaftar}  ({pct_unreg}%)\n\n"
    laporan += f"  ── dari {len(terdaftar)} terdaftar ──\n"
    laporan += f"  Memiliki Bio      : {len(punya_bio)}\n"
    laporan += f"  Tanpa Bio         : {tanpa_bio}\n"
    laporan += f"  Business Meta     : {len(bisnis)}\n"
    laporan += f"  Agent AI          : {len(ai)}\n\n"
    
    if len(terdaftar) > 0:
        laporan += "DETAIL NOMOR (10 Teratas):\n"
        for r in terdaftar[:10]:
            tipe = r['account_type']
            bio_text = f" · Bio: {r['bio'][:20]}..." if r['bio'] else " · No Bio"
            laporan += f"+{r['number']} ({tipe}){bio_text}\n"
            
    return laporan

def generate_excel(results: list) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'WA Bio Checker'

    headers = ['No', 'Nomor WA', 'Terdaftar', 'Nama', 'Bio', 'Tipe Akun', 'Kategori Bisnis']
    ws.append(headers)

    for i, r in enumerate(results, 1):
        ws.append([
            i, f"+{r['number']}", 'YA' if r['registered'] else 'TIDAK',
            r['name'], r['bio'], r['account_type'], r['business_category']
        ])
        
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    wb.save(tmp.name)
    tmp.close()
    return tmp.name

# ==========================================
# 2. HANDLER BOT TELEGRAM
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    text = (
        "👋 Halo! Saya adalah Bot Cek Bio WhatsApp.\n\n"
        "Kirimkan file berformat `.txt` yang berisi daftar nomor (satu baris satu nomor, atau dipisahkan koma) "
        "untuk mulai mengecek nomor.\n\n"
        "Jika sesi Chrome belum terbuka, bot akan mengirimkan QR Code yang bisa kamu scan."
    )
    bot.reply_to(message, text, parse_mode='Markdown')

@bot.message_handler(content_types=['document'])
def handle_document(message):
    global driver, checking_active
    if checking_active:
        bot.reply_to(message, "⚠️ Bot sedang memproses dokumen lain. Tunggu sampai selesai!")
        return

    chat_id = message.chat.id
    doc = message.document
    
    if not doc.file_name.endswith('.txt'):
        bot.reply_to(message, "⚠️ Harap kirimkan file berekstensi .txt!")
        return

    # Download file
    file_info = bot.get_file(doc.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    try:
        text_data = downloaded_file.decode('utf-8')
    except:
        bot.reply_to(message, "⚠️ Gagal membaca file. Pastikan file txt berupa teks biasa.")
        return

    numbers = []
    for r in re.split(r'[\n,;]+', text_data):
        n = normalize_number(r)
        if 7 <= len(n) <= 15:
            numbers.append(n)
            
    numbers = list(dict.fromkeys(numbers))
    if not numbers:
        bot.reply_to(message, "⚠️ Tidak ada nomor valid yang ditemukan di file tersebut.")
        return

    bot.reply_to(message, f"✅ Menerima **{len(numbers)}** nomor. Memulai proses pengecekan...", parse_mode='Markdown')
    
    # Start thread
    threading.Thread(target=process_numbers, args=(chat_id, numbers, doc.file_name)).start()

def process_numbers(chat_id, numbers, filename):
    global driver, checking_active
    checking_active = True
    results = []

    try:
        with driver_lock:
            if driver is None:
                driver = start_driver()
            
            # Check login
            if not wait_for_login(driver, chat_id):
                bot.send_message(chat_id, "❌ Gagal login (Timeout). Coba kirim ulang file.")
                checking_active = False
                return

        prog_msg = bot.send_message(chat_id, f"Memproses 0/{len(numbers)}...")
        
        for i, num in enumerate(numbers, 1):
            if not checking_active: break
            
            with driver_lock:
                res = get_whatsapp_bio(driver, num)
            results.append(res)
            
            # Update message every 5 numbers to avoid spamming TG API
            if i % 5 == 0 or i == len(numbers):
                try:
                    bot.edit_message_text(f"⏳ Memproses {i}/{len(numbers)}...", chat_id, prog_msg.message_id)
                except: pass

        # Generate Reports
        laporan_text = generate_report_text(filename, results)
        excel_path = generate_excel(results)

        # Send Text Report
        bot.send_message(chat_id, f"```\n{laporan_text}\n```", parse_mode='Markdown')
        
        # Send Excel File
        with open(excel_path, 'rb') as f:
            bot.send_document(chat_id, f, caption="Ini adalah file Excel lengkap dari hasil pengecekan!")
            
        os.remove(excel_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Terjadi kesalahan: {e}")
    finally:
        checking_active = False

if __name__ == '__main__':
    print("[+] Bot Telegram siap! Tekan Ctrl+C untuk berhenti.")
    bot.infinity_polling()
