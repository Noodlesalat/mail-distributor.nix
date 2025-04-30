import imaplib
import smtplib
import email
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from email.header import decode_header
import time
import os
import logging
import yaml
import argparse


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

    def mark_as_read(self, mail_id):
        """Markiert eine E-Mail als gelesen."""
        self.ensure_connection()
        if not self.connection:
            return
        try:
            self.connection.store(mail_id, '+FLAGS', '\\Seen')
        except Exception as e:
            logging.error(f"Fehler beim Markieren der E-Mail {mail_id} als gelesen: {e}")

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
        imap_config = self.config['imap']
        smtp_config = self.config['smtp']
        forwarding_config = self.config['forwarding']

        self.imap = IMAPConnection(
            server=imap_config['server'],
            user=imap_config['user'],
            password=self.read_password(imap_config['password_path']),
            mailbox=imap_config.get('mailbox', 'inbox')
        )
        self.smtp_user = smtp_config['user']
        self.smtp_password = self.read_password(smtp_config['password_path'])
        self.mail_from = smtp_config['mail_from']
        self.smtp_server = smtp_config['server']
        self.smtp_port = int(smtp_config['port'])
        self.forward_to = forwarding_config['recipients']
        self.allowed_senders = forwarding_config['allowed_senders']
        self.forwarder_name = self.config['general']['name']

    def load_config(self, config_file):
        """Lädt die Konfigurationsdatei."""
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)

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
        """Leitet die komplette E-Mail inkl. HTML und Anhängen weiter."""
        from_email = parsed_email['From']
        decoded_from_email = self.decode_from_header(from_email)
        subject = f"[{self.forwarder_name}] {parsed_email['Subject']}"
        decoded_subject = self.decode_from_header(subject)
        original_name, original_address = email.utils.parseaddr(from_email)
        message_id = make_msgid(domain=self.mail_from.split('@')[1])
        send_name = f"{original_name} via Verteiler"

        logging.info(f"Bereite Weiterleitung vor für Absender: {decoded_from_email}, Betreff: {decoded_subject}")

        # Original kopieren
        forwarded = email.message_from_bytes(parsed_email.as_bytes())

        # Header ersetzen
        forwarded.replace_header("Subject", subject)
        forwarded.replace_header("From", formataddr((send_name, self.mail_from)))
        forwarded.replace_header("To", recipient)
        forwarded.add_header("Reply-To", from_email)
        forwarded.replace_header("Date", formatdate(localtime=True))
        forwarded.replace_header("Message-ID", message_id)

        return forwarded


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
        logging.debug("Starte Verarbeitung neuer E-Mails.")
        mail_ids = self.imap.fetch_unseen_emails()
        if not mail_ids:
            logging.debug("Keine ungelesenen E-Mails gefunden.")
            return

        for mail_id in mail_ids:
            raw_email = self.imap.fetch_email(mail_id)
            if not raw_email:
                logging.warning(f"Fehler beim Abrufen der E-Mail mit ID {mail_id}. Überspringe.")
                continue

            parsed_email = email.message_from_bytes(raw_email)
            from_email = parsed_email['From']

            if not self.is_allowed_sender(from_email):
                decoded_sender = self.decode_from_header(from_email)
                logging.info(f"E-Mail von {decoded_sender} ignoriert. Absender nicht erlaubt – wird gelöscht.")
                self.imap.mark_as_deleted(mail_id)
                continue

            for recipient in self.forward_to:
                msg = self.create_forward_email(parsed_email, recipient)
                self.send_email(msg, recipient)

            self.imap.mark_as_read(mail_id)

        self.imap.expunge()
        logging.info("Verarbeitung der E-Mails abgeschlossen.")


def main(config_dir, sleep_duration):
    """Hauptprogramm für den Mail-Verteiler."""
    config_files = [os.path.join(config_dir, f) for f in os.listdir(config_dir) if f.endswith('.yaml')]
    forwarders = [MailForwarder(config_file) for config_file in config_files]

    while True:
        for forwarder in forwarders:
            forwarder.process_emails()
        time.sleep(sleep_duration)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mail Forwarding Script")
    parser.add_argument("config_dir", help="Pfad zum Konfigurationsordner")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default="INFO", help="Log-Level festlegen")
    parser.add_argument("--sleep-duration", type=int, default=10, help="Pause zwischen den Verarbeitungszyklen (in Sekunden)")
    args = parser.parse_args()

    # Logging konfigurieren
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s - %(levelname)s - %(message)s")

    logging.info(f"Starte Mail Forwarding mit Log-Level: {args.log_level}")
    logging.info(f"Verwende Konfigurationsordner: {args.config_dir}")
    logging.info(f"Pause zwischen Verarbeitungszyklen: {args.sleep_duration} Sekunden")

    try:
        main(args.config_dir, args.sleep_duration)
    except Exception as e:
        logging.error(f"Ein schwerwiegender Fehler ist aufgetreten: {e}")
        raise
