import streamlit as st
import pdfplumber
import re
import os
from pyairtable import Api

# Impostazione della pagina
st.set_page_config(page_title="PCO Manager - Upload PDF", layout="centered")

st.title("PCO Manager - Inserimento Airtable")
st.markdown("Carica i file PDF delle prenotazioni per estrarre automaticamente i dati e inviarli su Airtable.")

# Costanti e Liste
COMPANIES_LIST = [
    'Marghera', 'Esquilino', 'Gioberti', 'Cavour191', 'Word Travel', 
    'Rome Aurea Tours', 'Sharkei', 'Trevio', 'Alatri40', 'Bhauya Aviations', 
    'SVM Vacanze', 'Castelli Viaggi', 'Tours & Tours', 'Bella Vita Food Tours', 
    'Navigamondo', 'First Choice', 'Branduoo', 'Karma', 'Aquila'
]

def extract_data_from_pdf(pdf_file):
    text = ""
    # Estrazione testo dal PDF
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
                
    data = {}
    
    # ==========================================
    # BLOCCO 1: Dati Generali
    # ==========================================
    
    # 1. Codice Prenotazione
    # Cerca la parola "PRENOTAZIONE" seguita da a capo, e poi la stringa che inizia per "PCO"
    match_pco = re.search(r"PRENOTAZIONE\s*\n\s*(PCO[^\s]+)", text)
    data["PCO"] = match_pco.group(1) if match_pco else None
    
    # 2. Scadenza Pagamento
    # Cerca la stringa "Pagare entro il: " e cattura la data, formattandola per Airtable (YYYY-MM-DD)
    match_payment = re.search(r"Pagare entro il:\s*(\d{2})/(\d{2})/(\d{4})", text)
    if match_payment:
        data["Payment Deadline"] = f"{match_payment.group(3)}-{match_payment.group(2)}-{match_payment.group(1)}"
    else:
        data["Payment Deadline"] = None
    # 3. Totale Prenotazione
    # Cerca "Totale Prenotazione: " e cattura il valore (fino a fine riga)
    match_total = re.search(r"Totale Prenotazione:\s*([^\n]+)", text)
    if match_total:
        # Rimuoviamo il simbolo Euro e gli spazi
        val_str = match_total.group(1).replace("€", "").strip()
        # Rimuoviamo il punto delle migliaia e cambiamo la virgola in punto per i decimali
        val_str = val_str.replace(".", "").replace(",", ".")
        try:
            data["Totale Prenotazione"] = float(val_str)
        except ValueError:
            data["Totale Prenotazione"] = None
    else:
        data["Totale Prenotazione"] = None

    # 4. Azienda (Denominazione)
    match_denominazione = re.search(r"Denominazione:\s*([^\n]+)", text)
    data["Company Profile"] = None
    if match_denominazione:
        denominazione_str = match_denominazione.group(1)
        # Rimuoviamo gli spazi dalla stringa estratta e standardizziamo 'and' in '&' e 'bhavya' in 'bhauya' per facilitare il match
        denominazione_str_clean = denominazione_str.lower().replace(" ", "").replace("and", "&").replace("bhavya", "bhauya")
        
        for company in COMPANIES_LIST:
            # Rimuoviamo gli spazi e standardizziamo anche il nome in lista
            company_clean = company.lower().replace(" ", "").replace("and", "&")
            # Match parziale o totale, case insensitive e senza spazi
            if company_clean in denominazione_str_clean:
                # Formattato come array per supportare il campo Linked Record su Airtable
                data["Company Profile"] = [company]
                break

    # ==========================================
    # BLOCCO 2: Dati Linea (Biglietti)
    # ==========================================
    tickets = []
    
    # Individua l'inizio della sezione biglietti
    idx_biglietti = text.find("BIGLIETTI RICHIESTI")
    if idx_biglietti != -1:
        text_biglietti = text[idx_biglietti:]
        
        # Le tre tipologie di biglietto
        ticket_pattern = r"(24H ONLY ARENA - B2B CALL CENTER|COLOSSEO 24H - B2B CALL CENTER|FULL EXPERIENCE B2B CALL CENTER)"
        
        # Troviamo tutte le occorrenze delle intestazioni dei biglietti
        matches = list(re.finditer(ticket_pattern, text_biglietti))
        
        for i, match in enumerate(matches):
            ticket_type_str = match.group(1)
            
            # Mappatura del tipo biglietto
            if ticket_type_str == "24H ONLY ARENA - B2B CALL CENTER":
                airtable_type = "Only Arena"
            elif ticket_type_str == "COLOSSEO 24H - B2B CALL CENTER":
                airtable_type = "Standard"
            elif ticket_type_str == "FULL EXPERIENCE B2B CALL CENTER":
                airtable_type = "Arena"
            else:
                airtable_type = None
                
            # Determiniamo il blocco di testo relativo a questo specifico biglietto
            start_pos = match.end()
            # La fine di questo blocco è l'inizio del prossimo biglietto, oppure la fine del testo
            end_pos = matches[i+1].start() if i+1 < len(matches) else len(text_biglietti)
            block_text = text_biglietti[start_pos:end_pos]
            
            # Estrazione Quantità (CON SOMMA)
            # Intercetta i numeri interi tra i due punti ":" e la "x", supporta sia "CC:" che "CC (Under 18):"
            quantities = re.findall(r":\s*(\d+)\s*x", block_text, re.IGNORECASE)
            total_quantity = sum(int(q) for q in quantities)
            
            # Estrazione Data e Ora
            # Formattiamo in YYYY-MM-DD richiesto dai campi Date di Airtable
            # Per l'orario, catturiamo solo HH:MM ignorando i secondi (:\d{2})
            match_datetime = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2}):\d{2}", block_text)
            if match_datetime:
                visit_date = f"{match_datetime.group(3)}-{match_datetime.group(2)}-{match_datetime.group(1)}"
                visit_time = match_datetime.group(4)
            else:
                visit_date = None
                visit_time = None
            
            # Rilevamento presenza biglietti minori
            has_minor = bool(re.search(r"Under 18", block_text, re.IGNORECASE))
            
            # Aggiungi il biglietto se abbiamo trovato quantomeno una quantità o una data
            if total_quantity > 0 or visit_date:
                tickets.append({
                    "Standard/Arena": airtable_type,
                    "Ticket Quantity": total_quantity,
                    "Visit Date": visit_date,
                    "Orario Prenotazione": visit_time,
                    "Note": "Minor Tix" if has_minor else None
                })
                
    return data, tickets


# ==========================================
# INTERFACCIA E LOGICA STREAMLIT
# ==========================================

# Funzione per leggere le credenziali da Airtable.md
def load_credentials():
    creds = {"API_KEY": "", "BASE_ID": "", "TABLE_ID": ""}
    if os.path.exists("Airtable.md"):
        with open("Airtable.md", "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    if key.strip() in creds:
                        creds[key.strip()] = val.strip()
    return creds

saved_creds = load_credentials()

# Se stiamo girando su Streamlit Cloud, prova a prendere le chiavi dai Secrets, altrimenti usa quelle locali
api_key = st.secrets.get("API_KEY", saved_creds.get("API_KEY", "")) if hasattr(st, "secrets") else saved_creds.get("API_KEY", "")
base_id = st.secrets.get("BASE_ID", saved_creds.get("BASE_ID", "")) if hasattr(st, "secrets") else saved_creds.get("BASE_ID", "")
table_id = st.secrets.get("TABLE_ID", saved_creds.get("TABLE_ID", "")) if hasattr(st, "secrets") else saved_creds.get("TABLE_ID", "")

uploaded_files = st.file_uploader("Carica uno o più file PDF", type=["pdf"], accept_multiple_files=True)

if st.button("Avvia Elaborazione", type="primary"):
    if not api_key or not base_id or not table_id:
        st.warning("Per favore, inserisci tutti i parametri di connessione nel file Airtable.md.")
    elif not uploaded_files:
        st.warning("Carica almeno un file PDF per iniziare.")
    else:
        # Inizializza l'API di Airtable
        try:
            api = Api(api_key)
            table = api.table(base_id, table_id)
        except Exception as e:
            st.error(f"Errore durante l'inizializzazione di Airtable: {e}")
            st.stop()
            
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_files = len(uploaded_files)
        total_records_created = 0
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"Elaborazione in corso: {file.name} ({i+1}/{total_files})...")
            
            try:
                general_data, tickets = extract_data_from_pdf(file)
                
                if not tickets:
                    st.info(f"Nessun biglietto trovato nel file {file.name}.")
                    continue
                    
                # Controllo duplicati tramite il codice PCO
                pco_code = general_data.get("PCO")
                if pco_code:
                    existing_records = table.all(formula=f"{{PCO}} = '{pco_code}'")
                    if existing_records:
                        st.warning(f"File ignorato: '{file.name}' - La prenotazione {pco_code} è già presente su Airtable.")
                        progress_bar.progress((i + 1) / total_files)
                        continue

                # Per ogni tipologia di biglietto (Blocco 2), creiamo una riga iniettando i dati generali (Blocco 1)
                for j, ticket in enumerate(tickets):
                    record_data = {
                        "PCO": general_data.get("PCO"),
                        "Payment Deadline": general_data.get("Payment Deadline"),
                        # Assegna il Totale Prenotazione SOLO alla prima riga creata per questo PDF
                        "Totale Prenotazione": general_data.get("Totale Prenotazione") if j == 0 else None,
                        "Company Profile": general_data.get("Company Profile"),
                        "Standard/Arena": ticket.get("Standard/Arena"),
                        "Ticket Quantity": ticket.get("Ticket Quantity"),
                        "Visit Date": ticket.get("Visit Date"),
                        "Orario Prenotazione": ticket.get("Orario Prenotazione"),
                        "Note": ticket.get("Note")
                    }
                    
                    # Rimuoviamo le chiavi con valore None, perché l'API di Airtable preferisce campi assenti
                    # anziché null/None a seconda della configurazione della tabella
                    record_data_clean = {k: v for k, v in record_data.items() if v is not None}
                    
                    # Inserimento su Airtable con typecast=True per forzare il match testuale nel Linked Record
                    table.create(record_data_clean, typecast=True)
                    total_records_created += 1
                    
            except Exception as e:
                st.error(f"Si è verificato un errore elaborando '{file.name}': {str(e)}")
                
            # Aggiorna la barra di progresso
            progress_bar.progress((i + 1) / total_files)
            
        status_text.text("Elaborazione completata con successo!")
        st.success(f"Operazione terminata! Sono state create **{total_records_created}** nuove righe su Airtable.")
