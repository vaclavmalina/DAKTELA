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

# --- SEZNAM DOPRAVCŮ PRO DETEKCI ---
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

# --- 3. POMOCNÉ FUNKCE ---

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
st.set_page_config(page_title="Daktela Harvester", layout="centered", page_icon="🗃️", initial_sidebar_state="collapsed")

# Skrytí sidebaru
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        [data-testid="stSidebarNav"] {display: none;}
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='text-align: center;'>🗃️ Daktela Harvester</h1>", unsafe_allow_html=True)

# --- SESSION STATE INICIALIZACE ---
if 'process_running' not in st.session_state: st.session_state.process_running = False
if 'stop_requested' not in st.session_state: st.session_state.stop_requested = False
if 'results_ready' not in st.session_state: st.session_state.results_ready = False
if 'export_data' not in st.session_state: st.session_state.export_data = []
if 'id_list_txt' not in st.session_state: st.session_state.id_list_txt = ""
if 'stats' not in st.session_state: st.session_state.stats = {}
if 'found_tickets' not in st.session_state: st.session_state.found_tickets = [] # Seznam nalezených ticketů (fáze 1)
if 'search_performed' not in st.session_state: st.session_state.search_performed = False

# Výchozí datumy
if 'filter_date_from' not in st.session_state: st.session_state.filter_date_from = date.today().replace(day=1)
if 'filter_date_to' not in st.session_state: st.session_state.filter_date_to = date.today()

# Načtení číselníků při startu
if 'categories' not in st.session_state:
    try:
        res_cat = requests.get(f"{INSTANCE_URL}/api/v6/ticketsCategories.json", headers={'x-auth-token': ACCESS_TOKEN})
        cat_data = res_cat.json().get('result', {}).get('data', [])
        st.session_state['categories'] = sorted(cat_data, key=lambda x: x.get('title', '').lower())
        
        res_stat = requests.get(f"{INSTANCE_URL}/api/v6/statuses.json", headers={'x-auth-token': ACCESS_TOKEN})
        stat_data = res_stat.json().get('result', {}).get('data', [])
        st.session_state['statuses'] = sorted(stat_data, key=lambda x: x.get('title', '').lower())
    except:
        st.error("Nepodařilo se načíst číselníky. Zkontrolujte připojení nebo TOKEN.")
        st.stop()

# --- STEP 1: FILTRY ---
if not st.session_state.process_running and not st.session_state.results_ready:
    with st.container():
        st.subheader("1. Nastavení filtru")
        
        # A) DATUMY
        c_date1, c_date2 = st.columns(2)
        with c_date1:
            d_from = st.date_input("Datum od", value=st.session_state.filter_date_from, format="DD.MM.YYYY")
        with c_date2:
            d_to = st.date_input("Datum do", value=st.session_state.filter_date_to, format="DD.MM.YYYY")
        
        # Aktualizace state
        st.session_state.filter_date_from = d_from
        st.session_state.filter_date_to = d_to

        # B) RYCHLÉ VOLBY (3 řady po 3 tlačítkách = 9 tlačítek)
        st.caption("Rychlý výběr období:")
        
        # --- ŘADA 1 ---
        b_r1 = st.columns(3)
        
        # 1. TENTO ROK
        if b_r1[0].button("Tento rok", use_container_width=True):
            st.session_state.filter_date_from = date(date.today().year, 1, 1)
            st.session_state.filter_date_to = date.today()
            st.rerun()

        # 2. MINULÝ ROK (NOVÉ)
        if b_r1[1].button("Minulý rok", use_container_width=True):
            today = date.today()
            last_year = today.year - 1
            st.session_state.filter_date_from = date(last_year, 1, 1)
            st.session_state.filter_date_to = date(last_year, 12, 31)
            st.rerun()

        # 3. POSLEDNÍ PŮL ROK (Kalendářně: 6 celých měsíců zpět)
        if b_r1[2].button("Poslední půl rok", use_container_width=True):
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_of_prev_month = first_of_this_month - timedelta(days=1)
            
            # Výpočet startu: -6 měsíců
            start_month = first_of_this_month.month - 6
            start_year = first_of_this_month.year
            if start_month <= 0:
                start_month += 12
                start_year -= 1
            start_date = date(start_year, start_month, 1)

            st.session_state.filter_date_from = start_date
            st.session_state.filter_date_to = last_of_prev_month
            st.rerun()

        # --- ŘADA 2 ---
        b_r2 = st.columns(3)

        # 4. POSLEDNÍ 3 MĚSÍCE (Kalendářně: 3 celé měsíce zpět)
        if b_r2[0].button("Poslední 3 měsíce", use_container_width=True):
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_of_prev_month = first_of_this_month - timedelta(days=1)
            
            # Výpočet startu: -3 měsíce
            start_month = first_of_this_month.month - 3
            start_year = first_of_this_month.year
            if start_month <= 0:
                start_month += 12
                start_year -= 1
            start_date = date(start_year, start_month, 1)

            st.session_state.filter_date_from = start_date
            st.session_state.filter_date_to = last_of_prev_month
            st.rerun()

        # 5. MINULÝ MĚSÍC (Kalendářní)
        if b_r2[1].button("Minulý měsíc", use_container_width=True):
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_of_prev_month = first_of_this_month - timedelta(days=1)
            first_of_prev_month = last_of_prev_month.replace(day=1)
            
            st.session_state.filter_date_from = first_of_prev_month
            st.session_state.filter_date_to = last_of_prev_month
            st.rerun()

        # 6. TENTO MĚSÍC
        if b_r2[2].button("Tento měsíc", use_container_width=True):
            st.session_state.filter_date_from = date.today().replace(day=1)
            st.session_state.filter_date_to = date.today()
            st.rerun()

        # --- ŘADA 3 ---
        b_r3 = st.columns(3)

        # 7. MINULÝ TÝDEN (Po-Ne)
        if b_r3[0].button("Minulý týden", use_container_width=True):
            today = date.today()
            start_of_this_week = today - timedelta(days=today.weekday()) # Po tohoto týdne
            start_of_last_week = start_of_this_week - timedelta(weeks=1) # Po min. týdne
            end_of_last_week = start_of_last_week + timedelta(days=6) # Ne min. týdne
            
            st.session_state.filter_date_from = start_of_last_week
            st.session_state.filter_date_to = end_of_last_week
            st.rerun()

        # 8. TENTO TÝDEN (Po-Dnes)
        if b_r3[1].button("Tento týden", use_container_width=True):
            today = date.today()
            start_of_this_week = today - timedelta(days=today.weekday())
            st.session_state.filter_date_from = start_of_this_week
            st.session_state.filter_date_to = today
            st.rerun()

        # 9. VČEREJŠEK
        if b_r3[2].button("Včerejšek", use_container_width=True):
            yesterday = date.today() - timedelta(days=1)
            st.session_state.filter_date_from = yesterday
            st.session_state.filter_date_to = yesterday
            st.rerun()

        st.write("") # Mezera

        # C) KATEGORIE A STATUS (Vlevo / Vpravo)
        c_filt1, c_filt2 = st.columns(2)
        with c_filt1:
            cat_options = {c['title']: c['name'] for c in st.session_state['categories']}
            selected_cat = st.selectbox("Kategorie", options=["-- Vyber kategorii --"] + list(cat_options.keys()))
        
        with c_filt2:
            stat_options = {s['title']: s['name'] for s in st.session_state['statuses']}
            selected_stat = st.selectbox("Status", options=["-- Vyber status --"] + list(stat_options.keys()))

        # Tlačítko pro FÁZI 1 (Hledání)
        st.write("")
        if selected_cat != "-- Vyber kategorii --" and selected_stat != "-- Vyber status --":
            if st.button("🔍 VYHLEDAT TICKETY", type="primary", use_container_width=True):
                st.session_state.search_performed = False # Reset
                
                # Sestavení filtrů
                params = {
                    "filter[logic]": "and",
                    "filter[filters][0][field]": "created", "filter[filters][0][operator]": "gte", "filter[filters][0][value]": f"{st.session_state.filter_date_from} 00:00:00",
                    "filter[filters][1][field]": "created", "filter[filters][1][operator]": "lte", "filter[filters][1][value]": f"{st.session_state.filter_date_to} 23:59:59",
                    "filter[filters][2][field]": "category", "filter[filters][2][operator]": "eq", "filter[filters][2][value]": cat_options[selected_cat],
                    "filter[filters][3][field]": "statuses", "filter[filters][3][operator]": "eq", "filter[filters][3][value]": stat_options[selected_stat],
                    "take": 1000, 
                    "fields[0]": "name", 
                    "fields[1]": "title",
                    "fields[2]": "created",
                    "fields[3]": "customFields", 
                    "fields[4]": "category",
                    "fields[5]": "statuses"
                }
                
                with st.spinner("Prohledávám databázi..."):
                    try:
                        res = requests.get(f"{INSTANCE_URL}/api/v6/tickets.json", params=params, headers={'X-AUTH-TOKEN': ACCESS_TOKEN})
                        data = res.json().get('result', {}).get('data', [])
                        st.session_state.found_tickets = data
                        st.session_state.search_performed = True
                    except Exception as e:
                        st.error(f"Chyba při komunikaci s API: {e}")

# --- STEP 2: VÝSLEDEK HLEDÁNÍ & LIMIT ---
if st.session_state.search_performed and not st.session_state.process_running and not st.session_state.results_ready:
    st.divider()
    
    # NOVÉ: Tlačítko zpět, které resetuje hledání a umožní znovu nastavit filtry
    if st.button("⬅️ Změnit filtr / Hledat znovu"):
        st.session_state.search_performed = False
        st.rerun()

    st.subheader("2. Výsledek hledání")
    
    count = len(st.session_state.found_tickets)
    if count == 0:
        st.warning("⚠️ V zadaném období a nastavení nebyly nalezeny žádné tickety.")
    else:
        st.success(f"✅ Nalezeno **{count}** ticketů.")
        if count == 1000:
            st.info("ℹ️ API vrátilo maximální počet 1000 položek. Pokud potřebujete víc, zúžete období.")

        # NOVÉ: Tlačítko pro okamžité stažení seznamu ID
        found_ids_txt = "\n".join([t.get('name', '') for t in st.session_state.found_tickets])
        st.download_button(
            label="⬇️ Stáhnout nalezená ID (TXT)", 
            data=found_ids_txt, 
            file_name=f"found_tickets_ids.txt", 
            mime="text/plain"
        )
        st.write("") # Mezera

        st.write("Kolik ticketů chcete hloubkově zpracovat (stáhnout aktivity, e-maily)?")
        limit_val = st.number_input("Limit (0 = zpracovat všechny nalezené)", min_value=0, max_value=count, value=min(count, 50))
        
        st.write("")
        if st.button("⛏️ SPUSTIT HLOUBKOVOU TĚŽBU", type="primary", use_container_width=True):
            st.session_state.final_limit = limit_val
            st.session_state.process_running = True
            st.session_state.stop_requested = False
            st.rerun()

# --- STEP 3: PROCES TĚŽBY (LOOP) ---
if st.session_state.process_running:
    st.divider()
    st.subheader("3. Probíhá těžba dat...")
    
    if st.button("🛑 ZASTAVIT"):
        st.session_state.stop_requested = True
        st.session_state.process_running = False
        st.rerun()

    # Příprava regexů
    noise_patterns = [r"Potvrzujeme, že Vaše zpráva byla úspěšně doručena", r"Jelikož Vám chceme poskytnout nejlepší servis", r"dnes ve dnech .* čerpám dovolenou"]
    cut_off_patterns = [r"S pozdravem", r"S pozdravom", r"Kind regards", r"Regards", r"S přáním pěkného dne", r"S přáním hezkého dne", r"Děkuji\n", r"Ďakujem\n", r"Díky\n", r"Tento e-mail nepředstavuje nabídku", r"Pro případ, že tato zpráva obsahuje návrh smlouvy", r"Disclaimer:", r"Confidentiality Notice:", r"Myslete na životní prostředí", r"Please think about the environment"]
    history_patterns = [r"-{5,}", r"_{5,}", r"---------- Odpovězená zpráva ----------", r"Dne .* odesílatel .* napsal\(a\):", r"Od: .* Posláno: .*", r"---------- Původní e-mail ----------"]
    combined_cut_regex = re.compile("|".join(cut_off_patterns + history_patterns), re.IGNORECASE | re.MULTILINE)

    # Aplikace limitu na seznam
    tickets_to_process = st.session_state.found_tickets
    if st.session_state.final_limit > 0:
        tickets_to_process = tickets_to_process[:st.session_state.final_limit]

    pbar = st.progress(0)
    eta_placeholder = st.empty()
    status_placeholder = st.empty()
    
    full_export_data = []
    id_list_txt = f"SEZNAM ZPRACOVANÝCH ID\nDatum těžby: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n" + "-"*30 + "\n"
    
    start_time = time.time()
    total_count = len(tickets_to_process)

    for idx, t_obj in enumerate(tickets_to_process):
        if st.session_state.stop_requested: break
        
        t_num = t_obj.get('name')
        status_placeholder.markdown(f"📥 Zpracovávám ticket **{idx + 1}/{total_count}**: `{t_num}`")
        id_list_txt += f"{t_num}\n"
        
        try:
            # --- API VOLÁNÍ AKTIVIT ---
            # Retry logika
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
            
            # Detekce VIP
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
                
                # Čištění šumu
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
            pass 

        # Update Progress
        progress = (idx + 1) / total_count
        pbar.progress(progress)
        
        elapsed = time.time() - start_time
        if idx > 0:
            avg_per_item = elapsed / (idx + 1)
            remaining_sec = (total_count - (idx + 1)) * avg_per_item
            eta_placeholder.caption(f"⏱️ Zbývá cca: {int(remaining_sec)} sekund")

    # Konec procesu
    st.session_state.stats = {
        "tickets": len(full_export_data),
        "activities": sum(len(t['activities']) for t in full_export_data),
        "size": f"{len(json.dumps(full_export_data).encode('utf-8')) / 1024:.1f} KB"
    }
    st.session_state.export_data = full_export_data
    st.session_state.id_list_txt = id_list_txt
    st.session_state.results_ready = True
    st.session_state.process_running = False
    st.rerun()

# --- STEP 4: VÝSLEDKY ---
if st.session_state.results_ready:
    st.divider()
    st.success("🎉 Těžba dokončena!")
    
    s = st.session_state.stats
    c1, c2, c3 = st.columns(3)
    c1.metric("Zpracováno ticketů", s["tickets"])
    c2.metric("Nalezeno aktivit", s["activities"])
    c3.metric("Velikost dat", s["size"])

    st.write("")
    
    # Serializace
    json_data = json.dumps(st.session_state.export_data, ensure_ascii=False, indent=2)
    cat_slug = slugify(st.session_state.get('categories', [{'name': 'all'}])[0]['name']) # fallback pro jméno
    
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(label="💾 STÁHNOUT JSON DATA", data=json_data, file_name=f"export_harvest.json", mime="application/json", use_container_width=True)
    with col_dl2:
        st.download_button(label="🆔 STÁHNOUT SEZNAM ID", data=st.session_state.id_list_txt, file_name=f"seznam_id_harvest.txt", use_container_width=True)

    st.markdown("**Náhled dat (první ticket):**")
    preview = json.dumps(st.session_state.export_data[0] if st.session_state.export_data else {}, ensure_ascii=False, indent=2)
    st.code(preview, language="json")
    st.markdown("""<style> div[data-testid="stCodeBlock"] > div { overflow-y: auto; height: 300px; } </style>""", unsafe_allow_html=True)
    
    if st.button("🔄 Začít znovu (Reset)", use_container_width=True):
        st.session_state.results_ready = False
        st.session_state.search_performed = False
        st.rerun()
