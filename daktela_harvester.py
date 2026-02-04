import streamlit as st
import requests
import re
import os
import time
import unicodedata
import json
from datetime import datetime, timedelta, date
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

# --- 1. FUNKČNÍ FIREMNÍ AUTENTIZACE ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.set_page_config(page_title="Zabezpečený přístup", page_icon="🔒", layout="centered")
    
    col_main_1, col_main_2, col_main_3 = st.columns([1,2,1])
    with col_main_2:
        st.markdown("<h1 style='text-align: center;'>🔒 Přihlášení</h1>", unsafe_allow_html=True)
        st.write("<p style='text-align: center;'>Pro přístup k Balíkobot data centru zadejte heslo.</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            password_input = st.text_input("Heslo", type="password")
            submitted = st.form_submit_button("Přihlásit se", use_container_width=True)

    if submitted:
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Nesprávné heslo.")
    st.stop()

# --- 2. KONFIGURACE DAKTELA ---
INSTANCE_URL = st.secrets["DAKTELA_URL"]
ACCESS_TOKEN = st.secrets["DAKTELA_TOKEN"]

# --- KONFIGURACE A POMOCNÉ FUNKCE ---
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

@st.cache_resource
def load_anonymizer():
    return AnalyzerEngine(), AnonymizerEngine()

analyzer, anonymizer = load_anonymizer()

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

# --- GLOBÁLNÍ CALLBACK FUNKCE (Musí být zde) ---
def set_date_range(d_from, d_to):
    st.session_state.filter_date_from = d_from
    st.session_state.filter_date_to = d_to

def cb_this_year(): set_date_range(date(date.today().year, 1, 1), date.today())
def cb_last_year(): today = date.today(); last_year = today.year - 1; set_date_range(date(last_year, 1, 1), date(last_year, 12, 31))
def cb_last_half_year():
    today = date.today(); first_of_this_month = today.replace(day=1); last_of_prev_month = first_of_this_month - timedelta(days=1)
    start_month = first_of_this_month.month - 6; start_year = first_of_this_month.year
    if start_month <= 0: start_month += 12; start_year -= 1
    set_date_range(date(start_year, start_month, 1), last_of_prev_month)
def cb_last_3_months():
    today = date.today(); first_of_this_month = today.replace(day=1); last_of_prev_month = first_of_this_month - timedelta(days=1)
    start_month = first_of_this_month.month - 3; start_year = first_of_this_month.year
    if start_month <= 0: start_month += 12; start_year -= 1
    set_date_range(date(start_year, start_month, 1), last_of_prev_month)
def cb_last_month():
    today = date.today(); first_of_this_month = today.replace(day=1); last_of_prev_month = first_of_this_month - timedelta(days=1); first_of_prev_month = last_of_prev_month.replace(day=1)
    set_date_range(first_of_prev_month, last_of_prev_month)
def cb_this_month(): set_date_range(date.today().replace(day=1), date.today())
def cb_last_week():
    today = date.today(); start_of_this_week = today - timedelta(days=today.weekday()); start_of_last_week = start_of_this_week - timedelta(weeks=1); end_of_last_week = start_of_last_week + timedelta(days=6)
    set_date_range(start_of_last_week, end_of_last_week)
def cb_this_week(): today = date.today(); start_of_this_week = today - timedelta(days=today.weekday()); set_date_range(start_of_this_week, today)
def cb_yesterday(): yesterday = date.today() - timedelta(days=1); set_date_range(yesterday, yesterday)

def reset_cat_callback(): st.session_state.sb_category = "VŠE (bez filtru)"; st.session_state.selected_cat_key = "ALL"
def reset_stat_callback(): st.session_state.sb_status = "VŠE (bez filtru)"; st.session_state.selected_stat_key = "ALL"
def get_index(options_dict, current_val_key):
    found_key = next((k for k, v in options_dict.items() if v == current_val_key), "VŠE (bez filtru)")
    try: return list(options_dict.keys()).index(found_key)
    except ValueError: return 0

# --- HLAVNÍ UI ---
st.set_page_config(page_title="Balíkobot Data Centrum", layout="centered", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stSidebarNav"] {display: none;}
        
        div[data-testid="column"] button {
            height: 120px !important;
            width: 100% !important;
            font-size: 18px !important;
            font-weight: 600 !important;
            border-radius: 12px !important;
            border: 1px solid #e0e0e0;
            background-color: #ffffff;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            transition: all 0.2s ease-in-out;
            color: #31333F;
        }
        div[data-testid="column"] button:hover {
            transform: translateY(-3px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            border-color: #FF4B4B;
            color: #FF4B4B;
            background-color: #fff5f5;
        }
        div[data-testid="column"] button:active {
            transform: translateY(1px);
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        h1 {
            margin-bottom: 2rem;
        }
    </style>
""", unsafe_allow_html=True)

if 'current_app' not in st.session_state:
    st.session_state.current_app = "dashboard"

def show_wip_msg(module_name):
    st.toast(f"🚧 Modul **{module_name}** je momentálně ve vývoji.", icon="🛠️")

# --- DASHBOARD ---
if st.session_state.current_app == "dashboard":
    st.markdown("<h1 style='text-align: center;'>🗂️ Balíkobot Data Centrum</h1>", unsafe_allow_html=True)

    menu_items = [
        {"label": "🔎\nAnalýza ticketů", "action": "harvester"},
        {"label": "📊\nStatistiky",      "action": "Statistiky"},
        {"label": "📈\nDashboard",       "action": "Dashboard"},
        {"label": "📑\nReporting",       "action": "Reporting"},
        {"label": "👥\nUživatelé",       "action": "Uživatelé"},
        {"label": "🔄\nAutomatizace",    "action": "Automatizace"},
        {"label": "🗄️\nArchiv",          "action": "Archiv"},
        {"label": "⚙️\nNastavení",       "action": "Nastavení"},
        {"label": "❓\nNápověda",        "action": "Nápověda"},
    ]

    rows = [menu_items[i:i+3] for i in range(0, len(menu_items), 3)]
    for row in rows:
        cols = st.columns(3)
        for idx, item in enumerate(row):
            with cols[idx]:
                if st.button(item["label"], use_container_width=True):
                    if item["action"] == "harvester":
                        st.session_state.current_app = "harvester"
                        st.rerun()
                    else:
                        show_wip_msg(item["action"])
        st.write("")

# --- APLIKACE: HARVESTER ---
elif st.session_state.current_app == "harvester":
    
    col_back, col_title, col_void = st.columns([1, 4, 1])
    with col_back:
        if st.button("⬅️ Menu"):
            st.session_state.current_app = "dashboard"
            st.session_state.results_ready = False
            st.session_state.search_performed = False
            st.rerun()
    with col_title:
        st.markdown("<h2 style='text-align: center; margin-top: -10px;'>🔎 Analýza ticketů</h2>", unsafe_allow_html=True)

    st.divider()

    # --- SESSION STATE ---
    if 'process_running' not in st.session_state: st.session_state.process_running = False
    if 'stop_requested' not in st.session_state: st.session_state.stop_requested = False
    if 'results_ready' not in st.session_state: st.session_state.results_ready = False
    if 'export_data' not in st.session_state: st.session_state.export_data = []
    if 'id_list_txt' not in st.session_state: st.session_state.id_list_txt = ""
    if 'stats' not in st.session_state: st.session_state.stats = {}
    if 'found_tickets' not in st.session_state: st.session_state.found_tickets = [] 
    if 'search_performed' not in st.session_state: st.session_state.search_performed = False
    if 'filter_date_from' not in st.session_state: st.session_state.filter_date_from = date.today()
    if 'filter_date_to' not in st.session_state: st.session_state.filter_date_to = date.today()
    if 'selected_cat_key' not in st.session_state: st.session_state.selected_cat_key = "ALL"
    if 'selected_stat_key' not in st.session_state: st.session_state.selected_stat_key = "ALL"

    if 'categories' not in st.session_state:
        try:
            res_cat = requests.get(f"{INSTANCE_URL}/api/v6/ticketsCategories.json", headers={'x-auth-token': ACCESS_TOKEN})
            cat_data = res_cat.json().get('result', {}).get('data', [])
            st.session_state['categories'] = sorted(cat_data, key=lambda x: x.get('title', '').lower())
            res_stat = requests.get(f"{INSTANCE_URL}/api/v6/statuses.json", headers={'x-auth-token': ACCESS_TOKEN})
            stat_data = res_stat.json().get('result', {}).get('data', [])
            st.session_state['statuses'] = sorted(stat_data, key=lambda x: x.get('title', '').lower())
        except:
            st.error("Nepodařilo se načíst číselníky.")
            st.stop()

    cat_options_map = {"VŠE (bez filtru)": "ALL"}
    cat_options_map.update({c['title']: c['name'] for c in st.session_state['categories']})
    stat_options_map = {"VŠE (bez filtru)": "ALL"}
    stat_options_map.update({s['title']: s['name'] for s in st.session_state['statuses']})

    # -------------------------------------------------------------------------
    # STRIKTNÍ LOGIKA ŘÍZENÍ UI (STATE MACHINE)
    # Zobrazí se vždy POUZE JEDEN blok.
    # -------------------------------------------------------------------------

    # >>> BLOK A: BĚŽÍ PROCES (STEP 3) <<<
    if st.session_state.process_running:
        
        # Info o filtru nad loadingem
        with st.container(border=True):
            st.info(f"**Právě zpracovávám data pro:**\n\n"
                    f"📅 **Období:** {st.session_state.filter_date_from.strftime('%d.%m.%Y')} - {st.session_state.filter_date_to.strftime('%d.%m.%Y')}\n\n"
                    f"📂 **Kategorie:** {next((k for k,v in cat_options_map.items() if v == st.session_state.selected_cat_key), 'VŠE')}\n\n"
                    f"🏷️ **Status:** {next((k for k,v in stat_options_map.items() if v == st.session_state.selected_stat_key), 'VŠE')}")
        
        st.write("")
        st.subheader("3. Probíhá těžba dat...")
        st.write("")

        col_stop1, col_stop2, col_stop3 = st.columns([1, 2, 1])
        with col_stop2:
            if st.button("🛑 ZASTAVIT PROCES", use_container_width=True):
                st.session_state.stop_requested = True
                st.session_state.process_running = False
                st.rerun()

        progress_bar = st.progress(0)
        status_text = st.empty()
        eta_text = st.empty()

        # Logika těžby
        noise_patterns = [r"Potvrzujeme, že Vaše zpráva byla úspěšně doručena", r"Jelikož Vám chceme poskytnout nejlepší servis", r"dnes ve dnech .* čerpám dovolenou"]
        cut_off_patterns = [r"S pozdravem", r"S pozdravom", r"Kind regards", r"Regards", r"S přáním pěkného dne", r"S přáním hezkého dne", r"Děkuji\n", r"Ďakujem\n", r"Díky\n", r"Tento e-mail nepředstavuje nabídku", r"Pro případ, že tato zpráva obsahuje návrh smlouvy", r"Disclaimer:", r"Confidentiality Notice:", r"Myslete na životní prostředí", r"Please think about the environment"]
        history_patterns = [r"-{5,}", r"_{5,}", r"---------- Odpovězená zpráva ----------", r"Dne .* odesílatel .* napsal\(a\):", r"Od: .* Posláno: .*", r"---------- Původní e-mail ----------"]
        combined_cut_regex = re.compile("|".join(cut_off_patterns + history_patterns), re.IGNORECASE | re.MULTILINE)

        tickets_to_process = st.session_state.found_tickets
        if st.session_state.final_limit > 0:
            tickets_to_process = tickets_to_process[:st.session_state.final_limit]

        full_export_data = []
        start_time = time.time()
        total_count = len(tickets_to_process)

        for idx, t_obj in enumerate(tickets_to_process):
            if st.session_state.stop_requested: break
            t_num = t_obj.get('name')
            status_text.markdown(f"📥 Zpracovávám ticket **{idx + 1}/{total_count}**: `{t_num}`")
            
            try:
                acts = []
                for attempt in range(3):
                    try:
                        res_act = requests.get(f"{INSTANCE_URL}/api/v6/tickets/{t_num}/activities.json", headers={'X-AUTH-TOKEN': ACCESS_TOKEN}, timeout=30)
                        res_act.raise_for_status()
                        acts = res_act.json().get('result', {}).get('data', [])
                        break
                    except: time.sleep(1)
                
                t_date, t_time = format_date_split(t_obj.get('created'))
                t_status = t_obj.get('statuses', [{}])[0].get('title', 'N/A') if isinstance(t_obj.get('statuses'), list) and t_obj.get('statuses') else "N/A"
                custom_fields = t_obj.get('customFields', {})
                vip_list = custom_fields.get('vip', [])
                ticket_clientType = "VIP" if "→ VIP KLIENT ←" in vip_list else "Standard"
                
                ticket_entry = {"ticket_number": t_num, "ticket_name": t_obj.get('title', 'Bez předmětu'), "ticket_clientType": ticket_clientType, "ticket_category": t_obj.get('category', {}).get('title', 'N/A') if t_obj.get('category') else "N/A", "ticket_status": t_status, "ticket_creationDate": t_date, "ticket_creationTime": t_time, "activities": []}

                for a_idx, act in enumerate(sorted(acts, key=lambda x: x.get('time', '')), 1):
                    item = act.get('item') or {}
                    address = item.get('address', '')
                    cleaned = clean_html(item.get('text') or act.get('description'))
                    if not cleaned: continue
                    if any(re.search(p, cleaned, re.IGNORECASE) for p in noise_patterns): cleaned = "[AUTOMATICKÝ EMAIL BALÍKOBOTU]"
                    else:
                        match = combined_cut_regex.search(cleaned)
                        if match: cleaned = cleaned[:match.start()].strip() + "\n\n[PODPIS]"
                    u_title = (act.get('user') or {}).get('title')
                    c_title = (act.get('contact') or {}).get('title')
                    direction = item.get('direction', 'out')
                    if direction == "in": sender = identify_side(c_title, address, is_user=False); recipient = "Balíkobot"
                    else: sender = identify_side(u_title, "", is_user=True); recipient = identify_side(c_title, address, is_user=False)
                    a_date, a_time = format_date_split(act.get('time'))
                    act_type = act.get('type') or "COMMENT"
                    act_data = {"activity_number": a_idx, "activity_type": act_type, "activity_sender": sender}
                    if act_type != "COMMENT": act_data["activity_recipient"] = recipient
                    act_data.update({"activity_creationDate": a_date, "activity_creationTime": a_time, "activity_text": cleaned})
                    ticket_entry["activities"].append(act_data)
                
                full_export_data.append(ticket_entry)
            except Exception: pass

            progress_bar.progress((idx + 1) / total_count)
            elapsed = time.time() - start_time
            if idx > 0:
                avg_per_item = elapsed / (idx + 1)
                remaining_sec = (total_count - (idx + 1)) * avg_per_item
                eta_text.caption(f"⏱️ Zbývá cca: {int(remaining_sec)} sekund")

        final_ids_list = "SEZNAM ZPRACOVANÝCH ID\nDatum těžby: {}\n------------------------------\n".format(datetime.now().strftime('%d.%m.%Y %H:%M'))
        final_ids_list += "\n".join([str(t['ticket_number']) for t in full_export_data])

        st.session_state.stats = {"tickets": len(full_export_data), "activities": sum(len(t['activities']) for t in full_export_data), "size": f"{len(json.dumps(full_export_data).encode('utf-8')) / 1024:.1f} KB"}
        st.session_state.export_data = full_export_data
        st.session_state.id_list_txt = final_ids_list
        st.session_state.results_ready = True
        st.session_state.process_running = False
        st.rerun()

    # >>> BLOK B: VÝSLEDKY (STEP 4) <<<
    elif st.session_state.results_ready:
        st.divider()
        st.success("🎉 Těžba dokončena!")
        
        st.info(f"**Použitý filtr:**\n\n"
                f"📅 **Období:** {st.session_state.filter_date_from.strftime('%d.%m.%Y')} - {st.session_state.filter_date_to.strftime('%d.%m.%Y')}\n\n"
                f"📂 **Kategorie:** {next((k for k,v in cat_options_map.items() if v == st.session_state.selected_cat_key), 'VŠE')}\n\n"
                f"🏷️ **Status:** {next((k for k,v in stat_options_map.items() if v == st.session_state.selected_stat_key), 'VŠE')}")

        s = st.session_state.stats
        c1, c2, c3 = st.columns(3)
        c1.metric("Zpracováno ticketů", s["tickets"])
        c2.metric("Nalezeno aktivit", s["activities"])
        c3.metric("Velikost dat", s["size"])

        st.write("")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        c_name = "VSE" if st.session_state.selected_cat_key == "ALL" else slugify(next((k for k,v in cat_options_map.items() if v == st.session_state.selected_cat_key), "cat"))
        s_name = "VSE" if st.session_state.selected_stat_key == "ALL" else slugify(next((k for k,v in stat_options_map.items() if v == st.session_state.selected_stat_key), "stat"))
        file_name_data = f"data_{c_name}_{s_name}_{ts}.json"
        file_name_ids = f"tickets_{c_name}_{s_name}_{ts}.txt"
        json_data = json.dumps(st.session_state.export_data, ensure_ascii=False, indent=2)
        
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1: st.download_button(label="💾 STÁHNOUT JSON DATA", data=json_data, file_name=file_name_data, mime="application/json", use_container_width=True)
        with col_dl2: st.download_button(label="🆔 STÁHNOUT SEZNAM ID", data=st.session_state.id_list_txt, file_name=file_name_ids, use_container_width=True)

        st.write("")
        if st.button("🔄 Začít znovu / Nová analýza", type="primary", use_container_width=True):
            st.session_state.results_ready = False
            st.session_state.search_performed = False
            st.rerun()

        st.markdown("**Náhled dat (první ticket):**")
        preview = json.dumps(st.session_state.export_data[0] if st.session_state.export_data else {}, ensure_ascii=False, indent=2)
        st.code(preview, language="json")

    # >>> BLOK C: NASTAVENÍ (STEP 1 & 2) <<<
    else:
        with st.container():
            st.subheader("1. Nastavení filtru")
            c_date1, c_date2 = st.columns(2)
            with c_date1: d_from = st.date_input("Datum od", key="filter_date_from", format="DD.MM.YYYY")
            with c_date2: d_to = st.date_input("Datum do", key="filter_date_to", format="DD.MM.YYYY")
            
            st.caption("Rychlý výběr období:")
            b_r1 = st.columns(3); b_r1[0].button("Tento rok", use_container_width=True, on_click=cb_this_year); b_r1[1].button("Minulý rok", use_container_width=True, on_click=cb_last_year); b_r1[2].button("Poslední půl rok", use_container_width=True, on_click=cb_last_half_year)
            b_r2 = st.columns(3); b_r2[0].button("Poslední 3 měsíce", use_container_width=True, on_click=cb_last_3_months); b_r2[1].button("Minulý měsíc", use_container_width=True, on_click=cb_last_month); b_r2[2].button("Tento měsíc", use_container_width=True, on_click=cb_this_month)
            b_r3 = st.columns(3); b_r3[0].button("Minulý týden", use_container_width=True, on_click=cb_last_week); b_r3[1].button("Tento týden", use_container_width=True, on_click=cb_this_week); b_r3[2].button("Včerejšek", use_container_width=True, on_click=cb_yesterday)

            st.divider()

            c_filt1, c_filt2 = st.columns(2)
            with c_filt1:
                cat_idx = get_index(cat_options_map, st.session_state.selected_cat_key)
                sel_cat_label = st.selectbox("Kategorie", options=list(cat_options_map.keys()), index=cat_idx, key="sb_category")
                st.session_state.selected_cat_key = cat_options_map[sel_cat_label]
                st.button("Vybrat vše (Kategorie)", use_container_width=True, on_click=reset_cat_callback)
            with c_filt2:
                stat_idx = get_index(stat_options_map, st.session_state.selected_stat_key)
                sel_stat_label = st.selectbox("Status", options=list(stat_options_map.keys()), index=stat_idx, key="sb_status")
                st.session_state.selected_stat_key = stat_options_map[sel_stat_label]
                st.button("Vybrat vše (Status)", use_container_width=True, on_click=reset_stat_callback)

            st.write("")
            if st.button("🔍 VYHLEDAT TICKETY", type="primary", use_container_width=True):
                st.session_state.search_performed = False
                params = {"filter[logic]": "and", "filter[filters][0][field]": "created", "filter[filters][0][operator]": "gte", "filter[filters][0][value]": f"{st.session_state.filter_date_from} 00:00:00", "filter[filters][1][field]": "created", "filter[filters][1][operator]": "lte", "filter[filters][1][value]": f"{st.session_state.filter_date_to} 23:59:59", "take": 1000, "fields[0]": "name", "fields[1]": "title", "fields[2]": "created", "fields[3]": "customFields", "fields[4]": "category", "fields[5]": "statuses"}
                filter_idx = 2
                if st.session_state.selected_cat_key != "ALL": params[f"filter[filters][{filter_idx}][field]"] = "category"; params[f"filter[filters][{filter_idx}][operator]"] = "eq"; params[f"filter[filters][{filter_idx}][value]"] = st.session_state.selected_cat_key; filter_idx += 1
                if st.session_state.selected_stat_key != "ALL": params[f"filter[filters][{filter_idx}][field]"] = "statuses"; params[f"filter[filters][{filter_idx}][operator]"] = "eq"; params[f"filter[filters][{filter_idx}][value]"] = st.session_state.selected_stat_key; filter_idx += 1
                
                with st.spinner("Prohledávám databázi..."):
                    try:
                        res = requests.get(f"{INSTANCE_URL}/api/v6/tickets.json", params=params, headers={'X-AUTH-TOKEN': ACCESS_TOKEN})
                        data = res.json().get('result', {}).get('data', [])
                        st.session_state.found_tickets = data
                        st.session_state.search_performed = True
                    except Exception as e: st.error(f"Chyba při komunikaci s API: {e}")

        # STEP 2: VÝSLEDEK HLEDÁNÍ
        # Toto se zobrazí jen když je search_performed=True A zárověn process_running=False (díky struktuře if/elif/else nahoře)
        if st.session_state.search_performed:
            st.divider()
            
            col_x1, col_x2, col_x3 = st.columns([1, 2, 1])
            with col_x2:
                if st.button("❌ Zavřít výsledky a upravit zadání", use_container_width=True):
                    st.session_state.search_performed = False
                    st.rerun()

            st.subheader("2. Výsledek hledání")
            count = len(st.session_state.found_tickets)
            if count == 0: st.warning("⚠️ V zadaném období a nastavení nebyly nalezeny žádné tickety.")
            else:
                st.success(f"✅ Nalezeno **{count}** ticketů.")
                if count == 1000: st.info("ℹ️ API vrátilo maximální počet 1000 položek.")
                
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                c_name = "VSE" if st.session_state.selected_cat_key == "ALL" else slugify(next((k for k,v in cat_options_map.items() if v == st.session_state.selected_cat_key), "cat"))
                s_name = "VSE" if st.session_state.selected_stat_key == "ALL" else slugify(next((k for k,v in stat_options_map.items() if v == st.session_state.selected_stat_key), "stat"))
                
                found_ids_txt = "\n".join([str(t.get('name', '')) for t in st.session_state.found_tickets])
                
                col_d1, col_d2, col_d3 = st.columns([1, 2, 1])
                with col_d2:
                    st.download_button(label="⬇️ Stáhnout nalezená ID (TXT)", data=found_ids_txt, file_name=f"tickets_{c_name}_{s_name}_{ts}.txt", mime="text/plain", use_container_width=True)
                
                st.write("")
                st.write("Kolik ticketů chcete hloubkově zpracovat?")
                limit_val = st.number_input("Limit (0 = zpracovat všechny nalezené)", min_value=0, max_value=count, value=min(count, 50))
                st.write("")
                
                if st.button("⛏️ SPUSTIT ZPRACOVÁNÍ DAT", type="primary", use_container_width=True):
                    st.session_state.final_limit = limit_val
                    st.session_state.process_running = True
                    st.session_state.stop_requested = False
                    st.rerun()
