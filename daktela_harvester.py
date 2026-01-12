import streamlit as st
import requests
import re
import os
import time
import unicodedata
from datetime import datetime
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

# --- KONFIGURACE ---
INSTANCE_URL = st.secrets["DAKTELA_URL"]
ACCESS_TOKEN = st.secrets["DAKTELA_TOKEN"]

# Inicializace anonymizátoru
@st.cache_resource
def load_anonymizer():
    return AnalyzerEngine(), AnonymizerEngine()

analyzer, anonymizer = load_anonymizer()

# --- POMOCNÉ FUNKCE ---

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
    return anonymizer.anonymize(text=text, analyzer_results=results).text

def clean_html(raw_html):
    if not raw_html: return ""
    cleantext = raw_html.replace('</p>', '\n').replace('<br>', '\n').replace('<br />', '\n').replace('</div>', '\n').replace('&nbsp;', ' ')
    cleantext = re.sub(re.compile('<style.*?>.*?</style>|<script.*?>.*?</script>', re.DOTALL), '', cleantext)
    cleantext = re.sub(re.compile('<.*?>'), '', cleantext)
    cleantext = cleantext.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    patterns = [r'From:.*', r'Dne\s.*\snapsal/a:', r'On\s.*\swrote:', r'----------\s*Původní zpráva\s*----------']
    for p in patterns: cleantext = re.split(p, cleantext, flags=re.IGNORECASE)[0]
    return anonymize_text(cleantext.strip())

def format_date_cz(date_str):
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        return dt.strftime('%d.%m.%Y %H:%M:%S')
    except: return date_str

# --- STREAMLIT UI ---
st.set_page_config(page_title="Daktela Harvester", layout="centered", page_icon="🗃️")

# 1. Vycentrovaný název
st.markdown("<h1 style='text-align: center;'>🗃️ Daktela Harvester</h1>", unsafe_allow_html=True)

# Inicializace Session State
if 'process_running' not in st.session_state: st.session_state.process_running = False
if 'stop_requested' not in st.session_state: st.session_state.stop_requested = False
if 'results_ready' not in st.session_state: st.session_state.results_ready = False
if 'full_txt' not in st.session_state: st.session_state.full_txt = ""
if 'id_list_txt' not in st.session_state: st.session_state.id_list_txt = ""
if 'stats' not in st.session_state: st.session_state.stats = {}

# 2. Úvodní text
st.write("Aplikace slouží pro vyexportování dat z Daktely.")
st.write("") 
st.markdown("**Postupuj prosím podle kroků níže:**")

# 3. NASTAVENÍ ČASOVÉHO OBDOBÍ
with st.expander("📅 1. KROK: Nastavení časového období a limitů", expanded=not st.session_state.results_ready):
    col1, col2 = st.columns(2)
    with col1:
        # Vynucení formátu DD.MM.YYYY
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

# 4. VÝBĚR DAT
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

# 5. LOADING A PROCES
if st.session_state.process_running:
    st.divider()
    if st.button("🛑 ZASTAVIT SBĚR"):
        st.session_state.stop_requested = True
        st.session_state.process_running = False
        st.rerun()

    params = {
        "filter[logic]": "and",
        "filter[filters][0][field]": "created", "filter[filters][0][operator]": "gte", "filter[filters][0][value]": f"{date_from} 00:00:00",
        "filter[filters][1][field]": "created", "filter[filters][1][operator]": "lte", "filter[filters][1][value]": f"{date_to} 23:59:59",
        "filter[filters][2][field]": "category", "filter[filters][2][operator]": "eq", "filter[filters][2][value]": cat_options[selected_cat],
        "filter[filters][3][field]": "statuses", "filter[filters][3][operator]": "eq", "filter[filters][3][value]": stat_options[selected_stat],
        "fields[0]": "name", "take": 1000
    }
    
    res = requests.get(f"{INSTANCE_URL}/api/v6/tickets.json", params=params, headers={'X-AUTH-TOKEN': ACCESS_TOKEN})
    tickets = [t['name'] for t in res.json().get('result', {}).get('data', [])]
    if test_limit > 0: tickets = tickets[:test_limit]

    if not tickets:
        st.error("Žádné tickety nenalezeny.")
        st.session_state.process_running = False
    else:
        pbar = st.progress(0)
        eta_placeholder = st.empty()
        status_placeholder = st.empty()
        
        full_txt = f"{'#'*80}\n### EXPORT: {selected_cat} | {selected_stat}\n### OBDOBÍ: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}\n{'#'*80}\n"
        id_list_txt = f"SEZNAM ID TICKETŮ\nFiltr: {selected_cat} | {selected_stat}\nObdobí: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}\n" + "-"*30 + "\n"
        
        start_time = time.time()
        total_acts_found = 0
        
        for idx, t_num in enumerate(tickets):
            if st.session_state.stop_requested: break
            status_placeholder.markdown(f"📥 Právě zpracovávám ticket: **{t_num}**")
            id_list_txt += f"{t_num}\n"
            
            try:
                res_act = requests.get(f"{INSTANCE_URL}/api/v6/tickets/{t_num}/activities.json", headers={'X-AUTH-TOKEN': ACCESS_TOKEN}, timeout=30)
                acts = res_act.json().get('result', {}).get('data', [])
                if acts:
                    t_title = acts[0].get('ticket', {}).get('title', 'Bez předmětu')
                    full_txt += f"\n\n{'#'*80}\n### TICKET č. {t_num} | {t_title}\n{'#'*80}\n\n"
                    
                    for act in sorted(acts, key=lambda x: x.get('time', '')):
                        raw_text = (act.get('item') or {}).get('text') or act.get('description')
                        cleaned = clean_html(raw_text)
                        if not cleaned: continue
                        
                        total_acts_found += 1
                        raw_type = str(act.get('type', '')).upper()
                        is_comment = "COMMNET" in raw_type or (not act.get('type') and act.get('description'))
                        user_title = (act.get('user') or {}).get('title', 'Podpora')
                        contact_title = (act.get('contact') or {}).get('title', 'Klient')

                        if is_comment:
                            act_label = f"AKTIVITA (komentář)"
                            direction_text = f"INTERNÍ POZNÁMKA ({user_title})"
                        else:
                            act_label = f"AKTIVITA (e-mail)"
                            direction_text = f"Klient ({contact_title}) >>>> Balíkobot" if (act.get('item') or {}).get('direction') == "in" else f"Balíkobot ({user_title}) >>>> Klient"
                        
                        full_txt += f"  --- {act_label} | {format_date_cz(act.get('time'))} ---\n"
                        full_txt += f"  SMĚR: {direction_text}\n  {'-'*40}\n"
                        indented = "\n".join("    " + line for line in cleaned.splitlines())
                        full_txt += f"{indented}\n\n  {'. '*20}\n\n"
            except: pass
            
            pbar.progress((idx + 1) / len(tickets))
            avg_time = (time.time() - start_time) / (idx + 1)
            remaining = (len(tickets) - (idx + 1)) * avg_time
            eta_placeholder.markdown(f"⏱️ **ETA:** cca {int(remaining)}s | **Hotovo:** {idx+1}/{len(tickets)}")

        # Uložení statistik
        st.session_state.stats = {
            "tickets": len(tickets),
            "activities": total_acts_found,
            "lines": len(full_txt.splitlines()),
            "size": f"{len(full_txt.encode('utf-8')) / 1024:.1f} KB"
        }
        st.session_state.full_txt = full_txt
        st.session_state.id_list_txt = id_list_txt
        st.session_state.results_ready = True
        st.session_state.process_running = False
        st.rerun()

# 6. VÝSLEDKY A STATISTIKY
if st.session_state.results_ready:
    st.divider()
    st.success("🎉 Export dokončen!")
    
    # Statistiky v aplikaci
    s = st.session_state.stats
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ticketů", s["tickets"])
    c2.metric("Aktivit", s["activities"])
    c3.metric("Řádků textu", s["lines"])
    c4.metric("Velikost", s["size"])

    st.write("")
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button("💾 STÁHNOUT EXPORT", st.session_state.full_txt, file_name=f"report_{slugify(selected_cat)}.txt", use_container_width=True)
    with col_dl2:
        st.download_button("🆔 STÁHNOUT SEZNAM TICKETŮ", st.session_state.id_list_txt, file_name=f"seznam_id_{slugify(selected_cat)}.txt", use_container_width=True)

    st.markdown("**Náhled exportu (posledních 500 řádků):**")
    # Scrollovací okno díky pevném výšce v st.code (v nových verzích Streamlitu automatické)
    preview = "\n".join(st.session_state.full_txt.splitlines()[-500:])
    st.code(preview, language="text")
    
    if st.button("🔄 Nový export"):
        st.session_state.results_ready = False

        st.rerun()
