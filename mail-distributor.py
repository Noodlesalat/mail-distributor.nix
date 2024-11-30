#!/usr/bin/env python

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.utils import formataddr, formatdate, make_msgid
from email.header import decode_header
from email import encoders
import time
import os
import logging
import configparser

# Logging konfigurieren
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class IMAPConnection:
    def __init__(self, server, user, password, mailbox='inbox', max_retries=5, retry_delay=10):
        self.server = server
        self.user = user
        self.password = password
        self.mailbox = mailbox
        self.connection = None
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def connect(self):
        """Verbindet sich mit dem IMAP-Server und stellt sicher, dass die Verbindung aktiv ist."""
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.connection:
                    self.connection.logout()
                logging.info(f"Verbinden mit IMAP-Server: {self.server} (Versuch {attempt}/{self.max_retries})")
                self.connection = imaplib.IMAP4_SSL(self.server)
                self.connection.login(self.user, self.password)
                self.connection.select(self.mailbox)
                logging.info("IMAP-Verbindung erfolgreich hergestellt.")
                return
            except Exception as e:
                logging.warning(f"Verbindungsfehler: {e}. Warte {self.retry_delay} Sekunden...")
                time.sleep(self.retry_delay)
        
        logging.error("Maximale Anzahl an Verbindungsversuchen erreicht. Verbindung fehlgeschlagen.")
        self.connection = None

    def ensure_connection(self):
        """Prüft die Verbindung und stellt sie bei Bedarf wieder her."""
        if self.connection:
            try:
                self.connection.noop()
                return  # Verbindung ist aktiv
            except Exception as e:
                logging.warning(f"Verbindung verloren: {e}. Versuche erneut zu verbinden...")
        
        # Verbindung erneut herstellen
        self.connect()

    def fetch_unseen_emails(self):
        """Holt ungelesene E-Mails ab."""
        self.ensure_connection()
        if not self.connection:
            logging.error("Keine Verbindung verfügbar. Überspringe Abruf.")
            return []
        try:
            status, messages = self.connection.search(None, '(UNSEEN)')
            if status != "OK":
                logging.error(f"IMAP-Fehler bei der Suche: {status}")
                return []
            return messages[0].split()
        except Exception as e:
            logging.error(f"Fehler beim Abrufen ungelesener E-Mails: {e}")
            return []

    def fetch_email(self, mail_id):
        """Holt eine E-Mail anhand der Mail-ID."""
        self.ensure_connection()
        if not self.connection:
            return None
        try:
            status, msg_data = self.connection.fetch(mail_id, '(RFC822)')
            if status == "OK":
                return msg_data[0][1]
            logging.error(f"IMAP-Fehler beim Abrufen der E-Mail: {status}")
        except Exception as e:
            logging.error(f"Fehler beim Abrufen der E-Mail mit ID {mail_id}: {e}")
        return None

    def mark_as_deleted(self, mail_id):
        """Markiert eine E-Mail als gelöscht."""
        self.ensure_connection()
        if not self.connection:
            return
        try:
            self.connection.store(mail_id, '+FLAGS', '\\Deleted')
        except Exception as e:
            logging.error(f"Fehler beim Löschen der E-Mail {mail_id}: {e}")

    def expunge(self):
        """Entfernt endgültig gelöschte E-Mails."""
        self.ensure_connection()
        if not self.connection:
            return
        try:
            self.connection.expunge()
        except Exception as e:
            logging.error(f"Fehler beim endgültigen Löschen: {e}")


class MailForwarder:
    def __init__(self, config_file):
        self.config = self.load_config(config_file)
        self.imap = IMAPConnection(
            server=self.config['IMAP']['SERVER'],
            user=self.config['IMAP']['USER'],
            password=self.read_password(self.config['IMAP']['PASSWORD_PATH']),
            mailbox=self.config['IMAP'].get('MAILBOX', 'inbox')
        )
        self.smtp_user = self.config['SMTP']['USER']
        self.smtp_password = self.read_password(self.config['SMTP']['PASSWORD_PATH'])
        self.mail_from = self.config['SMTP']['MAIL_FROM']
        self.smtp_server = self.config['SMTP']['SERVER']
        self.smtp_port = int(self.config['SMTP']['PORT'])
        self.forward_to = [recipient.strip() for recipient in self.config['FORWARDING']['RECIPIENTS'].split(',')]
        self.allowed_senders = self.config['ALLOWED_SENDERS']['SENDERS'].split(',')
        self.forwarder_name = self.config['GENERAL']['NAME']

    def load_config(self, config_file):
        """Lädt die Konfigurationsdatei."""
        config = configparser.ConfigParser()
        config.read(config_file)
        return config

    def read_password(self, password_path):
        """Liest ein Passwort aus einer Datei."""
        try:
            with open(password_path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            logging.error(f"Fehler beim Lesen des Passworts: {e}")
            raise

    def is_allowed_sender(self, from_email):
        """Prüft, ob ein Absender erlaubt ist."""
        if '<' in from_email and '>' in from_email:
            from_email = from_email.split('<')[1].split('>')[0].strip()
        return from_email.lower() in [s.lower() for s in self.allowed_senders]

    def decode_from_header(self, from_header):
        """Dekodiert einen From-Header."""
        return ''.join(
            part.decode(encoding or 'utf-8') if isinstance(part, bytes) else part
            for part, encoding in decode_header(from_header)
        )
    
    def decode_subject(self, subject_header):
        """Dekodiert den Betreff aus einem E-Mail-Header."""
        if not subject_header:
            return ""
        return ''.join(
            part.decode(encoding or 'utf-8') if isinstance(part, bytes) else part
            for part, encoding in decode_header(subject_header)
        )

    def create_forward_email(self, parsed_email, recipient):
        """Erstellt eine weitergeleitete E-Mail."""
        from_email = parsed_email['From']
        decoded_from_email = self.decode_from_header(from_email)
        subject = parsed_email['Subject']
        decoded_subject = self.decode_from_header(subject)
        original_name, original_address = email.utils.parseaddr(from_email)
        message_id = make_msgid(domain=self.mail_from.split('@')[1])

        logging.info(f"Bereite Weiterleitung vor für Absender: {decoded_from_email}, Betreff: {decoded_subject}")

        msg = MIMEMultipart('mixed')
        msg['From'] = formataddr((original_name, self.mail_from))
        msg['To'] = recipient
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = message_id
        msg['Reply-To'] = from_email

        # Füge alle Parts zur weitergeleiteten Nachricht hinzu
        alternative_part = MIMEMultipart('alternative')
        for part in email_parts:
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'

            if content_type == "text/plain" and "attachment" not in content_disposition:
                alternative_part.attach(MIMEText(payload.decode(charset), 'plain'))
            elif content_type == "text/html" and "attachment" not in content_disposition:
                alternative_part.attach(MIMEText(payload.decode(charset), 'html'))
            elif "attachment" in content_disposition:
                filename = part.get_filename()
                maintype, subtype = content_type.split('/')
                attachment_part = MIMEBase(maintype, subtype)
                attachment_part.set_payload(payload)
                encoders.encode_base64(attachment_part)
                attachment_part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                msg.attach(attachment_part)

        if len(alternative_part.get_payload()) > 0:
            msg.attach(alternative_part)

        return msg

    def create_forward_email(self, parsed_email, recipient):
        """Erstellt eine weitergeleitete E-Mail, indem Body und Content-Type 1:1 übernommen werden."""
        email_parts = list(parsed_email.walk())
        from_email = parsed_email['From']
        decoded_from_email = self.decode_from_header(from_email)
        subject = f"[{self.forwarder_name}] {parsed_email['Subject']}"
        decoded_subject = self.decode_from_header(subject)
        original_name, original_address = email.utils.parseaddr(from_email)
        message_id = make_msgid(domain=self.mail_from.split('@')[1])
        send_name = f"{original_name} via Verteiler"

        logging.info(f"Bereite Weiterleitung vor für Absender: {decoded_from_email}, Betreff: {decoded_subject}")

        # E-Mail-Header setzen
        email_headers = {
            'From': formataddr((send_name, self.mail_from)),
            'To': recipient,
            'Subject': subject,
            'Date': formatdate(localtime=True),
            'Message-ID': message_id,
            'Reply-To': from_email
        }

        # Original-Body und Header direkt übernehmen
        raw_body = parsed_email.get_payload(decode=False)  # Kein Decoding, wir übernehmen 1:1
        content_type = parsed_email.get_content_type()
        content_transfer_encoding = parsed_email.get("Content-Transfer-Encoding")

        # E-Mail erstellen
        msg = MIMEBase(*content_type.split('/'))
        msg.set_payload(raw_body)

        # Header für den Body setzen
        if content_transfer_encoding:
            msg.add_header("Content-Transfer-Encoding", content_transfer_encoding)

        # E-Mail-Header anhängen
        for header, value in email_headers.items():
            msg[header] = value

        return msg

    def send_email(self, msg, recipient):
        """Sendet die erstellte E-Mail."""
        try:
            logging.info(f"Versende E-Mail an {recipient} über {self.smtp_server}:{self.smtp_port}.")
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.mail_from, recipient, msg.as_string())
            logging.info(f"E-Mail erfolgreich an {recipient} gesendet.")
        except Exception as e:
            logging.error(f"Fehler beim Senden der E-Mail an {recipient}: {e}")

    def process_emails(self):
        """Prozessiert ungelesene E-Mails."""
        logging.info("Starte Verarbeitung neuer E-Mails.")
        mail_ids = self.imap.fetch_unseen_emails()
        if not mail_ids:
            logging.info("Keine ungelesenen E-Mails gefunden.")
            return

        for mail_id in mail_ids:
            raw_email = self.imap.fetch_email(mail_id)
            if not raw_email:
                logging.warning(f"Fehler beim Abrufen der E-Mail mit ID {mail_id}. Überspringe.")
                continue
            
            parsed_email = email.message_from_bytes(raw_email)
            from_email = parsed_email['From']

            if not self.is_allowed_sender(from_email):
                logging.info(f"E-Mail von {self.decode_from_header(from_email)} ignoriert. Absender nicht erlaubt.")
                continue

            for recipient in self.forward_to:
                msg = self.create_forward_email(parsed_email, recipient)
                self.send_email(msg, recipient)
            self.imap.mark_as_deleted(mail_id)

        self.imap.expunge()
        logging.info("Verarbeitung der E-Mails abgeschlossen.")


def main(config_dir):
    """Hauptprogramm für den Mail-Verteiler."""
    config_files = [os.path.join(config_dir, f) for f in os.listdir(config_dir) if f.endswith('.ini')]
    forwarders = [MailForwarder(config_file) for config_file in config_files]

    while True:
        for forwarder in forwarders:
            forwarder.process_emails()
        time.sleep(60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Nutzung: python mail_forwarder.py <config_verzeichnis>")
        sys.exit(1)
    config_directory = sys.argv[1]
    main(config_directory)
