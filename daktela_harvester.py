import streamlit as st
import requests
import re
import os
import time
import unicodedata
import json
from datetime import datetime
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

# --- 1. FUNKČNÍ FIREMNÍ AUTENTIZACE ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.set_page_config(page_title="Zabezpečený přístup", page_icon="🔒")
    st.markdown("<h1 style='text-align: center;'>🔒 Firemní přístup</h1>", unsafe_allow_html=True)
    st.write("<p style='text-align: center;'>Pro přístup k Daktela Harvesteru zadejte firemní heslo.</p>", unsafe_allow_html=True)
    
    password_input = st.text_input("Heslo", type="password")
    
    col_auth_1, col_auth_2, col_auth_3 = st.columns([1,2,1])
    with col_auth_2:
        if st.button("Přihlásit se", use_container_width=True):
            if password_input == st.secrets["APP_PASSWORD"]:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Nesprávné heslo.")
    st.stop()

# --- 2. KONFIGURACE DAKTELA (Trezor: Secrets) ---
INSTANCE_URL = st.secrets["DAKTELA_URL"]
ACCESS_TOKEN = st.secrets["DAKTELA_TOKEN"]

# --- SEZNAM DOPRAVCŮ PRO DETEKCI (NOVÉ Z PYTHON KÓDU) ---
CARRIERS_DATA = {
    "cp": "Česká pošta", "ppl": "PPL", "dpd": "DPD", "geis": "Geis", "gls": "GLS",
    "zasilkovna": "Zásilkovna", "intime": "We Do", "toptrans": "Top Trans", "pbh": "Pošta Bez Hranic",
    "dhl": "DHL", "sp": "Slovenská pošta", "ups": "UPS", "tnt": "TNT", "sps": "SK Parcel Service",
    "gw": "Gebrüder Weiss SK", "gwcz": "Gebrüder Weiss CZ", "dhlde": "DHL DE", "messenger": "Messenger",
    "fofr": "Fofr", "fedex": "Fedex", "dachser": "Dachser", "raben": "Raben", "dhlfreightec": "DHL Freight Euroconnect",
    "dhlparcel": "DHL Parcel Europe", "liftago": "Kurýr na přesný čas", "dbschenker": "DB Schenker",
    "dsv": "DSV", "spring": "Spring", "kurier": "123 Kuriér", "airway": "Airway", "japo": "JAPO Transport",
    "magyarposta": "Magyar Posta", "sameday": "Sameday", "sds": "SLOVENSKÝ DORUČOVACÍ SYSTÉM",
    "inpost": "InPost", "onebyallegro": "One by Allegro"
}

# Inicializace anonymizátoru
@st.cache_resource
def load_anonymizer():
    return AnalyzerEngine(), AnonymizerEngine()

analyzer, anonymizer = load_anonymizer()

# --- 3. POMOCNÉ FUNKCE (AKTUALIZOVÁNO PODLE PYTHON KÓDU) ---

def slugify(text):
    if not text: return "export"
    text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '_', text)

def anonymize_text(text):
    if not text: return ""
    text = re.sub(r'(?i)(heslo|password|pwd|pass|access_token)(\s*[:=]\s*)(\S+)', r'\1\2[HESLO]', text)
    text = re.sub(r'(\+?420\s?|(?:\b))(\d{3}\s?\d{3}\s?\d{3})\b', '[TELEFON]', text)
    results = analyzer.analyze(text=text, entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "IP_ADDRESS"], language='en')
    anonymized_result = anonymizer.anonymize(text=text, analyzer_results=results)
    return anonymized_result.text

def clean_html(raw_html):
    if not raw_html: return ""
    cleantext = raw_html.replace('</p>', '\n').replace('<br>', '\n').replace('<br />', '\n').replace('</div>', '\n').replace('&nbsp;', ' ')
    cleanr = re.compile('<style.*?>.*?</style>|<script.*?>.*?</script>', re.DOTALL)
    cleantext = re.sub(cleanr, '', cleantext)
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', cleantext)
    cleantext = cleantext.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    patterns = [r'From:.*', r'Dne\s.*\snapsal/a:', r'----------\s*Původní zpráva\s*----------', r'On\s.*\swrote:', r'____________________________________________']
    for pattern in patterns:
        cleantext = re.split(pattern, cleantext, flags=re.IGNORECASE)[0]
    cleantext = re.sub(r'\n\s*\n', '\n\n', cleantext)
    return anonymize_text(cleantext.strip())

def format_date_split(date_str):
    if not date_str: return "N/A", "N/A"
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        return dt.strftime('%d.%m.%Y'), dt.strftime('%H:%M:%S')
    except: return date_str, "N/A"

def identify_side(title, email, is_user=False):
    if is_user:
        return f"Balíkobot ({title})" if title and title.lower() != "balikobot" else "Balíkobot"
    clean_title = title.lower() if title else ""
    clean_email = email.lower() if email else ""
    if "balikobot" in clean_email or "balikobot" in clean_title:
        return f"Balíkobot ({title})" if title and title.lower() != "balikobot" else "Balíkobot"
    for slug, name in CARRIERS_DATA.items():
        if (slug and f"@{slug}." in clean_email) or (slug and clean_email.endswith(f"@{slug}.com")) or (name.lower() in clean_title):
            return f"Dopravce ({name})"
    return f"Klient ({title})" if title else "Klient"

# --- 4. STREAMLIT UI ---
# Nastavení schová levý panel (initial_sidebar_state="collapsed")
st.set_page_config(page_title="Daktela Harvester", layout="centered", page_icon="🗃️", initial_sidebar_state="collapsed")

# Skrytí sidebaru pomocí CSS (pro jistotu, aby tam nezůstala ani šipka)
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stSidebarNav"] {display: none;}
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='text-align: center;'>🗃️ Daktela Harvester</h1>", unsafe_allow_html=True)

# Inicializace Session State
if 'process_running' not in st.session_state: st.session_state.process_running = False
if 'stop_requested' not in st.session_state: st.session_state.stop_requested = False
if 'results_ready' not in st.session_state: st.session_state.results_ready = False
if 'export_data' not in st.session_state: st.session_state.export_data = [] # ZMĚNA: Ukládáme data, ne text
if 'id_list_txt' not in st.session_state: st.session_state.id_list_txt = ""
if 'stats' not in st.session_state: st.session_state.stats = {}

st.write("Aplikace slouží pro vyexportování dat z Daktely do strukturovaného JSON formátu.")
st.write("") 
st.markdown("**Postupuj prosím podle kroků níže:**")

# KROK 1
with st.expander("📅 1. KROK: Nastavení časového období a limitů", expanded=not st.session_state.results_ready):
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("Datum od", datetime.now().replace(day=1), format="DD.MM.YYYY")
    with col2:
        date_to = st.date_input("Datum do", datetime.now(), format="DD.MM.YYYY")
    
    test_limit = st.number_input("Testovací limit (kolik ticketů max.? 0 = vše)", min_value=0, value=10)
    
    if st.button("Načíst číselníky z Daktely"):
        with st.spinner("Načítám kategorie a statusy..."):
            res_cat = requests.get(f"{INSTANCE_URL}/api/v6/ticketsCategories.json", headers={'x-auth-token': ACCESS_TOKEN})
            st.session_state['categories'] = res_cat.json().get('result', {}).get('data', [])
            res_stat = requests.get(f"{INSTANCE_URL}/api/v6/statuses.json", headers={'x-auth-token': ACCESS_TOKEN})
            st.session_state['statuses'] = res_stat.json().get('result', {}).get('data', [])
        st.success("Seznamy načteny.")

# KROK 2
if 'categories' in st.session_state:
    with st.expander("📁 2 KROK: výběr kategorie a statusu", expanded=not st.session_state.results_ready):
        cat_options = {c['title']: c['name'] for c in st.session_state['categories']}
        selected_cat = st.selectbox("Vyber kategorii", options=["-- Vyber kategorii --"] + list(cat_options.keys()))
        
        stat_options = {s['title']: s['name'] for s in st.session_state['statuses']}
        selected_stat = st.selectbox("Vyber status", options=["-- Vyber status --"] + list(stat_options.keys()))

    if selected_cat != "-- Vyber kategorii --" and selected_stat != "-- Vyber status --":
        if not st.session_state.process_running and not st.session_state.results_ready:
            if st.button("🚀 SPUSTIT SBĚR DAT", use_container_width=True):
                st.session_state.process_running = True
                st.session_state.stop_requested = False
                st.rerun()

# PROCES SBĚRU
if st.session_state.process_running:
    st.divider()
    if st.button("🛑 ZASTAVIT SBĚR"):
        st.session_state.stop_requested = True
        st.session_state.process_running = False
        st.rerun()

    # Příprava regexů pro čištění (Podle Python kódu)
    noise_patterns = [r"Potvrzujeme, že Vaše zpráva byla úspěšně doručena", r"Jelikož Vám chceme poskytnout nejlepší servis", r"dnes ve dnech .* čerpám dovolenou"]
    cut_off_patterns = [r"S pozdravem", r"S pozdravom", r"Kind regards", r"Regards", r"S přáním pěkného dne", r"S přáním hezkého dne", r"Děkuji\n", r"Ďakujem\n", r"Díky\n", r"Tento e-mail nepředstavuje nabídku", r"Pro případ, že tato zpráva obsahuje návrh smlouvy", r"Disclaimer:", r"Confidentiality Notice:", r"Myslete na životní prostředí", r"Please think about the environment"]
    history_patterns = [r"-{5,}", r"_{5,}", r"---------- Odpovězená zpráva ----------", r"Dne .* odesílatel .* napsal\(a\):", r"Od: .* Posláno: .*", r"---------- Původní e-mail ----------"]
    combined_cut_regex = re.compile("|".join(cut_off_patterns + history_patterns), re.IGNORECASE | re.MULTILINE)

    params = {
        "filter[logic]": "and",
        "filter[filters][0][field]": "created", "filter[filters][0][operator]": "gte", "filter[filters][0][value]": f"{date_from} 00:00:00",
        "filter[filters][1][field]": "created", "filter[filters][1][operator]": "lte", "filter[filters][1][value]": f"{date_to} 23:59:59",
        "filter[filters][2][field]": "category", "filter[filters][2][operator]": "eq", "filter[filters][2][value]": cat_options[selected_cat],
        "filter[filters][3][field]": "statuses", "filter[filters][3][operator]": "eq", "filter[filters][3][value]": stat_options[selected_stat],
        "take": 1000 # Bere plné objekty ticketů pro detekci VIP atd.
    }
    
    with st.spinner("Získávám seznam ticketů..."):
        res = requests.get(f"{INSTANCE_URL}/api/v6/tickets.json", params=params, headers={'X-AUTH-TOKEN': ACCESS_TOKEN})
        tickets_raw = res.json().get('result', {}).get('data', [])
    
    if test_limit > 0: tickets_raw = tickets_raw[:test_limit]

    if not tickets_raw:
        st.error("Žádné tickety nenalezeny.")
        st.session_state.process_running = False
    else:
        pbar = st.progress(0)
        eta_placeholder = st.empty()
        status_placeholder = st.empty()
        
        full_export_data = [] # List pro JSON
        id_list_txt = f"SEZNAM ID TICKETŮ\nFiltr: {selected_cat} | {selected_stat}\nObdobí: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}\n" + "-"*30 + "\n"
        
        start_time = time.time()
        
        for idx, t_obj in enumerate(tickets_raw):
            if st.session_state.stop_requested: break
            t_num = t_obj.get('name')
            status_placeholder.markdown(f"📥 Právě zpracovávám ticket: **{t_num}**")
            id_list_txt += f"{t_num}\n"
            
            # --- LOGIKA ZPRACOVÁNÍ JEDNOHO TICKETU (PŘEVZATO Z PYTHON KÓDU) ---
            try:
                # Retry mechanizmus (zjednodušený pro seq)
                acts = []
                for attempt in range(3):
                    try:
                        res_act = requests.get(f"{INSTANCE_URL}/api/v6/tickets/{t_num}/activities.json", headers={'X-AUTH-TOKEN': ACCESS_TOKEN}, timeout=30)
                        res_act.raise_for_status()
                        acts = res_act.json().get('result', {}).get('data', [])
                        break
                    except:
                        time.sleep(1)
                
                t_date, t_time = format_date_split(t_obj.get('created'))
                t_status = t_obj.get('statuses', [{}])[0].get('title', 'N/A') if isinstance(t_obj.get('statuses'), list) and t_obj.get('statuses') else "N/A"
                
                # Detekce VIP klienta
                custom_fields = t_obj.get('customFields', {})
                vip_list = custom_fields.get('vip', [])
                ticket_clientType = "VIP" if "→ VIP KLIENT ←" in vip_list else "Standard"
                
                ticket_entry = {
                    "ticket_number": t_num, 
                    "ticket_name": t_obj.get('title', 'Bez předmětu'),
                    "ticket_clientType": ticket_clientType,
                    "ticket_category": t_obj.get('category', {}).get('title', 'N/A') if t_obj.get('category') else "N/A",
                    "ticket_status": t_status, 
                    "ticket_creationDate": t_date, 
                    "ticket_creationTime": t_time,
                    "activities": []
                }

                for a_idx, act in enumerate(sorted(acts, key=lambda x: x.get('time', '')), 1):
                    item = act.get('item') or {}
                    address = item.get('address', '')
                    cleaned = clean_html(item.get('text') or act.get('description'))
                    if not cleaned: continue
                    
                    if any(re.search(p, cleaned, re.IGNORECASE) for p in noise_patterns):
                        cleaned = "[AUTOMATICKÝ EMAIL BALÍKOBOTU]"
                    else:
                        match = combined_cut_regex.search(cleaned)
                        if match: cleaned = cleaned[:match.start()].strip() + "\n\n[PODPIS]"

                    u_title = (act.get('user') or {}).get('title')
                    c_title = (act.get('contact') or {}).get('title')
                    direction = item.get('direction', 'out')

                    if direction == "in":
                        sender = identify_side(c_title, address, is_user=False)
                        recipient = "Balíkobot"
                    else:
                        sender = identify_side(u_title, "", is_user=True)
                        recipient = identify_side(c_title, address, is_user=False)

                    a_date, a_time = format_date_split(act.get('time'))
                    act_type = act.get('type') or "COMMENT"
                    
                    act_data = {
                        "activity_number": a_idx, 
                        "activity_type": act_type,
                        "activity_sender": sender
                    }
                    if act_type != "COMMENT":
                        act_data["activity_recipient"] = recipient
                    
                    act_data.update({
                        "activity_creationDate": a_date, 
                        "activity_creationTime": a_time,
                        "activity_text": cleaned
                    })
                    ticket_entry["activities"].append(act_data)
                
                full_export_data.append(ticket_entry)

            except Exception as e:
                pass # Error handling mlčí, jako v původním UI

            pbar.progress((idx + 1) / len(tickets_raw))
            avg_time = (time.time() - start_time) / (idx + 1)
            remaining = (len(tickets_raw) - (idx + 1)) * avg_time
            eta_placeholder.markdown(f"⏱️ **ETA:** cca {int(remaining)}s | **Hotovo:** {idx+1}/{len(tickets_raw)}")

        st.session_state.stats = {
            "tickets": len(tickets_raw),
            "activities": sum(len(t['activities']) for t in full_export_data),
            "lines": "N/A (JSON)",
            "size": f"{len(json.dumps(full_export_data).encode('utf-8')) / 1024:.1f} KB"
        }
        st.session_state.export_data = full_export_data
        st.session_state.id_list_txt = id_list_txt
        st.session_state.results_ready = True
        st.session_state.process_running = False
        st.rerun()

# VÝSLEDKY
if st.session_state.results_ready:
    st.divider()
    st.success("🎉 Export dokončen!")
    s = st.session_state.stats
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ticketů", s["tickets"])
    c2.metric("Aktivit", s["activities"])
    c3.metric("Formát", "JSON")
    c4.metric("Velikost", s["size"])

    st.write("")
    
    # Serializace JSON pro stažení
    json_data = json.dumps(st.session_state.export_data, ensure_ascii=False, indent=2)
    
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(label="💾 STÁHNOUT JSON DATA", data=json_data, file_name=f"export_{slugify(selected_cat)}.json", mime="application/json", use_container_width=True)
    with col_dl2:
        st.download_button(label="🆔 STÁHNOUT SEZNAM ID", data=st.session_state.id_list_txt, file_name=f"seznam_id_{slugify(selected_cat)}.txt", use_container_width=True)

    st.markdown("**Náhled dat (JSON - první ticket):**")
    
    # Náhled prvního záznamu (pokud existuje)
    if st.session_state.export_data:
        preview = json.dumps(st.session_state.export_data[0], ensure_ascii=False, indent=2)
    else:
        preview = "{}"
    
    # Scrollovací okno s fixní výškou 400px
    st.code(preview, language="json")
    st.markdown("""<style> div[data-testid="stCodeBlock"] > div { overflow-y: auto; height: 400px; } </style>""", unsafe_allow_html=True)
    
    if st.button("🔄 Nový export", use_container_width=True):
        st.session_state.results_ready = False
        st.rerun()
