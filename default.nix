{ config, lib, pkgs, ... }:

with lib;

let
  # Python-Skript für den Verteiler
  verteiler = pkgs.writers.writePython3Bin "verteiler" {
    libraries = with pkgs.python3Packages; [
      imaplib2
      smtplib
      email
      configparser
    ];
  } (builtins.readFile ./verteiler.py);

  # YAML-Format für die Generierung der Configs
  configFormat = pkgs.formats.yaml {};

  # Funktion zum Generieren der Config-Dateien pro Verteiler
  configFiles = mapAttrsToList (name: cfg:
    configFormat.generate "${name}.yml" cfg
  ) config.services.sms2mail.config;
in
{
  options = {
    services.sms2mail = {
      enable = mkOption {
        type = types.bool;
        default = false;
        description = "Enable the sms2mail service.";
      };

      config = mkOption {
        type = types.attrsOf configFormat.type;
        default = {};
        description = ''
          Map of mail forwarders, where each key is the forwarder name, 
          and the value is the configuration for that forwarder.
          Example:
          {
            "forwarder1" = {
              IMAP = {
                SERVER = "imap.example.com";
                USER = "user@example.com";
                PASSWORD_PATH = "/path/to/password";
                MAILBOX = "inbox";
              };
              SMTP = {
                SERVER = "smtp.example.com";
                PORT = 587;
                USER = "user@example.com";
                PASSWORD_PATH = "/path/to/password";
                MAIL_FROM = "user@example.com";
              };
              FORWARDING = {
                RECIPIENTS = [ "recipient1@example.com" "recipient2@example.com" ];
              };
              ALLOWED_SENDERS = {
                SENDERS = [ "allowed1@example.com" "allowed2@example.com" ];
              };
              GENERAL = {
                NAME = "Example Forwarder";
              };
            };
          }
        '';
      };
    };
  };

  config = mkIf config.services.sms2mail.enable {
    # Stelle sicher, dass das Skript verfügbar ist
    environment.systemPackages = [ verteiler ];

    # Systemd-Dienst für das Skript
    systemd.services.sms2mail = {
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      description = "sms2mail Daemon";
      serviceConfig = {
        ExecStart = ''
          ${verteiler}/bin/verteiler ${toString config.services.sms2mail.configDir}
        '';
        Restart = "always";
        RestartSec = "5s";
      };
    };

    # Generiere die Config-Dateien
    systemd.tmpfiles.rules = map (file: {
      type = "f";
      path = "/etc/sms2mail/${file}";
      mode = "0644";
      content = config.services.sms2mail.config.${file};
    }) (builtins.attrNames config.services.sms2mail.config);

    # Optional: Config-Ordner setzen
    environment.variables.SMS2MAIL_CONFIG_DIR = "/etc/sms2mail";
  };
}
