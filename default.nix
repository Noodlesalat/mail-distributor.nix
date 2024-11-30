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
  ) config.services.verteiler.config;
in
{
  options = {
    services.verteiler = {
      enable = mkOption {
        type = types.bool;
        default = false;
        description = "Enable the verteiler service.";
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

  config = mkIf config.services.verteiler.enable {
    # Stelle sicher, dass das Skript verfügbar ist
    environment.systemPackages = [ verteiler ];

    # Systemd-Dienst für das Skript
    systemd.services.verteiler = {
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      description = "verteiler Daemon";
      serviceConfig = {
        ExecStart = ''
          ${verteiler}/bin/verteiler ${toString config.services.verteiler.configDir}
        '';
        Restart = "always";
        RestartSec = "5s";
      };
    };

    # Generiere die Config-Dateien
    systemd.tmpfiles.rules = map (file: {
      type = "f";
      path = "/etc/verteiler/${file}";
      mode = "0644";
      content = config.services.verteiler.config.${file};
    }) (builtins.attrNames config.services.verteiler.config);

    # Optional: Config-Ordner setzen
    environment.variables.verteiler_CONFIG_DIR = "/etc/verteiler";
  };
}
