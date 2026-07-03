import logging
import asyncio
import json
import os
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import yfinance as yf
import google.generativeai as genai
from finvizfinance.screener.overview import Overview
from gnews import GNews

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 1. DOSYA TABANLI HAFIZA YÖNETİMİ (JSON)
PORTFOY_DOSYASI = "portfoy.json"
ALARMLAR_DOSYASI = "alarmlar.json"

def veriyi_yukle(dosya_adi, varsayilan):
    if os.path.exists(dosya_adi):
        with open(dosya_adi, "r", encoding="utf-8") as f:
            return json.load(f)
    return varsayilan

def veriyi_kaydet(dosya_adi, veri):
    with open(dosya_adi, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=4)

# Hafızayı Dosyalardan Yüklüyoruz
PORTFOY = veriyi_yukle(PORTFOY_DOSYASI, {})
ALARMLAR = veriyi_yukle(ALARMLAR_DOSYASI, [])

# Yapay Zeka Hazırlığı
def yapay_zeka_hazirla(api_key):
    genai.configure(api_key=api_key)
    sistem_talimati = (
        "Sen kıdemli bir küresel piyasa uzmanı, finans analistisin.\n"
        "Sana bir hissenin teknik verileri ve o şirket hakkındaki son haber başlıkları verilecek.\n"
        "Verileri ve haber duyarlılığını (sentiment) birleştirerek yatırımcıya haftalık bir strateji çiz.\n"
        "Yalnızca HTML etiketleri kullan (<b>, <i>, <code>). Asla Markdown (*) kullanma."
    )
    return genai.GenerativeModel(model_name="gemini-2.5-flash", system_instruction=sistem_talimati)

def ana_menu_klavyesi():
    klavye = [
        ["📈 Hisse Verileri", "🔍 Keşfet Modu"],
        ["💼 Portföy Analizi", "🚨 Alarm Kur"]
    ]
    return ReplyKeyboardMarkup(klavye, resize_keyboard=True)

async def start_veya_merhaba(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["beklenen_islem"] = None
    await update.message.reply_text(
        "🧠 <b>Yapay Zekalı Finans Terminaline Hoş Geldiniz!</b>\n\n"
        "<b>Portföy Komutları:</b>\n"
        "• Alım Ekle: `/ekle HISSE ADET MALIYET` (Örn: `/ekle ASELS 100 62.50`)\n"
        "• Satım Düş: `/cikar HISSE ADET` (Örn: `/cikar ASELS 50`)\n\n"
        "<b>Alarm Komutları:</b>\n"
        "• Alarmları Gör: `/alarmlarim`\n"
        "• Alarm İptal Et: `/alarmsil ALARM_NO` (Örn: `/alarmsil 1`)",
        parse_mode="HTML", reply_markup=ana_menu_klavyesi()
    )

# 2. ARKA PLAN ALARM DENETLEYİCİSİ
async def alarm_denetleyici(context: ContextTypes.DEFAULT_TYPE):
    global ALARMLAR
    if not ALARMLAR:
        return

    degisiklik_var = False
    for alarm in ALARMLAR[:]:
        try:
            hisse = yf.Ticker(alarm["hisse"])
            df = hisse.history(period="1d")
            if df.empty: continue
            
            guncel_fiyat = round(df['Close'].iloc[-1], 2)
            tetiklendi = False
            
            if alarm["tip"] == "ustunde" and guncel_fiyat >= alarm["hedef"]:
                tetiklendi = True
            elif alarm["tip"] == "altinda" and guncel_fiyat <= alarm["hedef"]:
                tetiklendi = True
                
            if tetiklendi:
                yon = "ÜZERİNE ÇIKTI" if alarm["tip"] == "ustunde" else "ALTINA DÜŞTÜ"
                mesaj = (
                    f"🚨 <b>FİYAT ALARMI TETİKLENDİ!</b>\n\n"
                    f"📊 <b>Hisse:</b> {alarm['hisse']}\n"
                    f"💰 <b>Güncel Fiyat:</b> {guncel_fiyat}\n"
                    f"🎯 <b>Hedefiniz:</b> {alarm['hedef']} {yon}!\n"
                )
                await context.bot.send_message(chat_id=alarm["chat_id"], text=mesaj, parse_mode="HTML")
                ALARMLAR.remove(alarm)
                degisiklik_var = True
        except Exception as e:
            print(f"Alarm denetim hatası: {e}")
            
    if degisiklik_var:
        veriyi_kaydet(ALARMLAR_DOSYASI, ALARMLAR)

# 3. YENİ EKKLENEN KOMUTLAR (EKLE, CIKAR, ALARMLARIM, ALARMSIL)
async def portfoy_ekle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PORTFOY
    try:
        # Örn: /ekle ASELS 100 62.50
        kod = context.args[0].upper()
        adet = int(context.args[1])
        maliyet = float(context.args[2])
        
        if len(kod) <= 5 and "." not in kod: kod = f"{kod}.IS"
        
        if kod in PORTFOY:
            # Ortalama Maliyet Hesaplama
            eski_adet = PORTFOY[kod]["adet"]
            eski_maliyet = PORTFOY[kod]["maliyet"]
            yeni_adet = eski_adet + adet
            yeni_maliyet = ((eski_maliyet * eski_adet) + (maliyet * adet)) / yeni_adet
            PORTFOY[kod] = {"adet": yeni_adet, "maliyet": round(yeni_maliyet, 2)}
        else:
            PORTFOY[kod] = {"adet": adet, "maliyet": maliyet}
            
        veriyi_kaydet(PORTFOY_DOSYASI, PORTFOY)
        await update.message.reply_text(f"✅ <b>{kod}</b> portföye eklendi! Güncel: {PORTFOY[kod]['adet']} adet | Ort. Maliyet: {PORTFOY[kod]['maliyet']}", parse_mode="HTML")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Hatalı kullanım! Örnek: `/ekle ASELS 100 62.50`", parse_mode="HTML")

async def portfoy_cikar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PORTFOY
    try:
        kod = context.args[0].upper()
        adet = int(context.args[1])
        if len(kod) <= 5 and "." not in kod: kod = f"{kod}.IS"
        
        if kod not in PORTFOY:
            await update.message.reply_text("❌ Bu hisse zaten portföyünüzde yok.")
            return
            
        if PORTFOY[kod]["adet"] <= adet:
            del PORTFOY[kod]
            await update.message.reply_text(f"🗑️ <b>{kod}</b> portföyden tamamen kaldırıldı.", parse_mode="HTML")
        else:
            PORTFOY[kod]["adet"] -= adet
            await update.message.reply_text(f"📉 <b>{kod}</b> varlığınız {adet} adet azaltıldı. Kalan: {PORTFOY[kod]['adet']} adet.", parse_mode="HTML")
            
        veriyi_kaydet(PORTFOY_DOSYASI, PORTFOY)
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Hatalı kullanım! Örnek: `/cikar ASELS 50`", parse_mode="HTML")

async def alarmlari_listele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ALARMLAR:
        await update.message.reply_text("📭 Şu an kurulu herhangi bir fiyat bildiriminiz (alarmınız) bulunmuyor.")
        return
        
    mesaj = "🚨 <b>AKTİF FİYAT BİLDİRİMLERİNİZ</b>\n\n"
    for idx, alarm in enumerate(ALARMLAR, 1):
        yon = "≥ (Üstünde)" if alarm["tip"] == "ustunde" else "≤ (Altında)"
        mesaj += f"<b>{idx}.</b> <code>{alarm['hisse']}</code> hedefi: <b>{alarm['hedef']}</b> {yon}\n"
        
    mesaj += "\n💡 Bir alarmı silmek için: `/alarmsil NO` yazabilirsiniz."
    await update.message.reply_text(mesaj, parse_mode="HTML")

async def alarm_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALARMLAR
    try:
        no = int(context.args[0]) - 1
        if no < 0 or no >= len(ALARMLAR):
            await update.message.reply_text("❌ Geçersiz alarm numarası. Listeyi görmek için `/alarmlarim` yazın.")
            return
            
        silinen = ALARMLAR.pop(no)
        veriyi_kaydet(ALARMLAR_DOSYASI, ALARMLAR)
        await update.message.reply_text(f"🗑️ <code>{silinen['hisse']}</code> için kurulan <b>{silinen['hedef']}</b> alarmı iptal edildi.", parse_mode="HTML")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Hatalı kullanım! Örnek: `/alarmsil 1`", parse_mode="HTML")

# 4. KLASİK BUTON MESAJ YÖNLENDİRİCİSİ
async def mesaj_yonlendir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    metin = update.message.text.strip()
    beklenen = context.user_data.get("beklenen_islem")

    if metin.lower() in ["merhaba", "selam", "sa", "başlat"]:
        await start_veya_merhaba(update, context)
        return

    if metin == "📈 Hisse Verileri":
        context.user_data["beklenen_islem"] = "hisse_kodu_bekliyor"
        await update.message.reply_text("📝 Analiz edilecek <b>Hisse Kodunu</b> girin (Örn: ASELS, TSLA):", parse_mode="HTML")
        return
    elif metin == "🔍 Keşfet Modu":
        await kesfet_modu(update, context)
        return
    elif metin == "💼 Portföy Analizi":
        await portfoy_hesapla_ve_goster(update, context)
        return
    elif metin == "🚨 Alarm Kur":
        context.user_data["beklenen_islem"] = "alarm_tanimi_bekliyor"
        await update.message.reply_text("🚨 <b>Alarm Formatı:</b>\n<code>HISSE HEDEF_FIYAT</code> şeklinde yazın. (Örn: `ASELS 68.50`)", parse_mode="HTML")
        return

    if beklenen == "hisse_kodu_bekliyor":
        context.user_data["beklenen_islem"] = None
        await hisse_verisi_getir(update, context, metin)
        return
    elif beklenen == "alarm_tanimi_bekliyor":
        context.user_data["beklenen_islem"] = None
        await alarm_kaydet(update, context, metin)
        return

    await update.message.reply_text("💡 Lütfen menüdeki butonları kullanın.", reply_markup=ana_menu_klavyesi())

# YARDIMCI FONKSİYONLAR (HİSSE, PORTFÖY HESAPLAMA, ALARM KAYDET, KEŞFET)
async def hisse_verisi_getir(update: Update, context: ContextTypes.DEFAULT_TYPE, hisse_kod: str):
    hisse_kod = hisse_kod.upper()
    if len(hisse_kod) <= 5 and "." not in hisse_kod:
        test = yf.Ticker(hisse_kod)
        if test.history(period="1d").empty: hisse_kod = f"{hisse_kod}.IS"
    try:
        hisse = yf.Ticker(hisse_kod)
        df = hisse.history(period="2d")
        if df.empty:
            await update.message.reply_text("❌ Hisse verisi çekilemedi.")
            return
        son_fiyat = round(df['Close'].iloc[-1], 2)
        onceki_kapanis = round(df['Close'].iloc[-2], 2)
        degisim = round(((son_fiyat - onceki_kapanis) / onceki_kapanis) * 100, 2)
        rapor = f"📋 <b>HİSSE ÖZETİ: {hisse_kod}</b>\n💰 <b>Son Fiyat:</b> {son_fiyat} {hisse.info.get('currency', 'USD')}\n📈 <b>Günlük Değişim:</b> {degisim}%\n🔊 <b>Hacim:</b> {int(df['Volume'].iloc[-1]):,}\n"
        klavye = [[InlineKeyboardButton("🧠 Haberleri & Verileri AI ile Yorumlat", callback_data=f"ai_hisse_{hisse_kod}")]]
        await update.message.reply_text(rapor, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(klavye))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Hata: {str(e)}")

async def portfoy_hesapla_ve_goster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PORTFOY
    if not PORTFOY:
        await update.message.reply_text("📭 Portföyünüz şu an boş. Eklemek için `/ekle` komutunu kullanabilirsiniz.", parse_mode="HTML")
        return
        
    await update.message.reply_text("💼 Portföy değeriniz piyasadan canlı hesaplanıyor...")
    try:
        toplam_maliyet, toplam_guncel_deger = 0, 0
        rapor = "💼 <b>ÖZEL PORTFÖY RAPORUNUZ</b>\n\n"
        for kod, veri in PORTFOY.items():
            h = yf.Ticker(kod)
            df = h.history(period="1d")
            if df.empty: continue
            guncel_fiyat = round(df['Close'].iloc[-1], 2)
            maliyet, adet = veri["maliyet"], veri["adet"]
            
            hisse_maliyet_toplam = maliyet * adet
            hisse_guncel_toplam = guncel_fiyat * adet
            toplam_maliyet += hisse_maliyet_toplam
            toplam_guncel_deger += hisse_guncel_toplam
            
            hisse_kar_zarar = hisse_guncel_toplam - hisse_maliyet_toplam
            hisse_kz_yuzde = round((hisse_kar_zarar / hisse_maliyet_toplam) * 100, 2)
            durum_emoji = "🟢" if hisse_kar_zarar >= 0 else "🔴"
            rapor += f"{durum_emoji} <b>{kod}</b> ({adet} Adet)\n├ Maliyet: {maliyet} | Güncel: {guncel_fiyat}\n└ Kâr/Zarar: {round(hisse_kar_zarar, 2)} ({hisse_kz_yuzde}%)\n\n"
            
        net_kar_zarar = toplam_guncel_deger - toplam_maliyet
        net_kz_yuzde = round((net_kar_zarar / toplam_maliyet) * 100, 2) if toplam_maliyet > 0 else 0
        rapor += f"---------------------------\n💰 <b>Toplam Maliyet Değeri:</b> {round(toplam_maliyet, 2)}\n📊 <b>Anlık Güncel Değer:</b> {round(toplam_guncel_deger, 2)}\n💵 <b>Net Kâr/Zarar:</b> {round(net_kar_zarar, 2)} ({net_kz_yuzde}%)\n"
        klavye = [[InlineKeyboardButton("🧠 Portföy Eğilimini AI'a Yorumlat", callback_data="ai_portfoy")]]
        await update.message.reply_text(rapor, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(klavye))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Hata: {str(e)}")

async def alarm_kaydet(update: Update, context: ContextTypes.DEFAULT_TYPE, girdi: str):
    global ALARMLAR
    try:
        parcalar = girdi.split()
        hisse_kod = parcalar[0].upper()
        hedef_fiyat = float(parcalar[1])
        if len(hisse_kod) <= 5 and "." not in hisse_kod: hisse_kod = f"{hisse_kod}.IS"
        
        df = yf.Ticker(hisse_kod).history(period="1d")
        guncel = round(df['Close'].iloc[-1], 2)
        tip = "ustunde" if hedef_fiyat > guncel else "altinda"
        
        ALARMLAR.append({"chat_id": update.message.chat_id, "hisse": hisse_kod, "hedef": hedef_fiyat, "tip": tip})
        veriyi_kaydet(ALARMLAR_DOSYASI, ALARMLAR)
        
        yon = "üzerine çıktığında" if tip == "ustunde" else "altına düştüğünde"
        await update.message.reply_text(f"✅ Alarm Kuruldu! <code>{hisse_kod}</code> {hedef_fiyat} {yon} bildirim göndereceğim.", parse_mode="HTML")
    except Exception:
        await update.message.reply_text("❌ Hatalı format. Örnek: `ASELS 68.50`")

async def kesfet_modu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Tarama yapılıyor...")
    try:
        fverse = Overview()
        fverse.set_filter(filters_dict={'Price': 'Under $1', 'Relative Volume': 'Over 1.5'})
        df = fverse.screener_view().dropna(subset=['Ticker', 'Price', 'Volume']).head(3)
        cevap = "🚀 <b>1$ Altı Hareketli Hisseler:</b>\n\n"
        kodlar = []
        for idx, row in df.iterrows():
            cevap += f"▪️ <b>{row['Ticker']}</b> | Fiyat: ${row['Price']} | Değişim: {row['Change']}\n"
            kodlar.append(row['Ticker'])
        klavye = [[InlineKeyboardButton("🧠 Listeyi AI ile Yorumlat", callback_data=f"ai_kesfet_{','.join(kodlar)}")]]
        await update.message.reply_text(cevap, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(klavye))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Hata: {str(e)}")

# INTERNETTEKI HABERLERI CEKIP CEVAPLAYAN AI MOTORU
async def buton_tiklandi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    model = context.application.bot_data["ai_model"]
    await query.message.reply_text("🤖 Haberler taranıyor ve Yapay Zeka strateji hazırlıyor...")
    try:
        if data.startswith("ai_hisse_"):
            kod = data.split("_")[2]
            google_haberler = GNews(language='tr', country='TR', max_results=3) if ".IS" in kod else GNews(language='en', country='US', max_results=3)
            haber_listesi = google_haberler.get_news(f"{kod.replace('.IS', '')} stock")
            haber_metni = "".join([f"- {h['title']} ({h['publisher']['title']})\n" for h in haber_listesi])
            prompt = f"{kod} hissesi son haber başlıkları:\n\n{haber_metni}\n\nBu verilere göre duyarlılık (sentiment) analizi yap."
        elif data == "ai_portfoy":
            prompt = f"Yatırımcının portföyündeki hisseler: {list(PORTFOY.keys())}. Genel küresel piyasayı ve trendleri yorumla."
        elif data.startswith("ai_kesfet_"):
            prompt = f"Şu kuruşluk hisseler hacim patlaması yaşıyor: {data.split('_')[2]}. Risk analizi yap."

        response = model.generate_content(prompt)
        await query.message.reply_text(f"🤖 <b>AI Raporu:</b>\n\n{response.text}", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Kota veya Teknik Hata: {str(e)}")

def main():
    TELEGRAM_TOKEN = 'key1'
    GEMINI_API_KEY = 'key2'
    
    ai_model = yapay_zeka_hazirla(GEMINI_API_KEY)
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.bot_data["ai_model"] = ai_model

    job_queue = application.job_queue
    job_queue.run_repeating(alarm_denetleyici, interval=60, first=10)

    # Yeni Komut Yönetim Linkleri
    application.add_handler(CommandHandler("start", start_veya_merhaba))
    application.add_handler(CommandHandler("ekle", portfoy_ekle))
    application.add_handler(CommandHandler("cikar", portfoy_cikar))
    application.add_handler(CommandHandler("alarmlarim", alarmlari_listele))
    application.add_handler(CommandHandler("alarmsil", alarm_sil))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_yonlendir))
    application.add_handler(CallbackQueryHandler(buton_tiklandi))

    print("🚀 Süper Gelişmiş Finans Terminali Yayında!")
    application.run_polling()

if __name__ == '__main__':
    main()