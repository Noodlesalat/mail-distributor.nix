{ config, lib, pkgs, ... }:

with lib;

let
  # Python-Skript für den mail-distributor
  mail-distributor = pkgs.writers.writePython3Bin "mail-distributor" {
    libraries = with pkgs.python3Packages; [
      imaplib2
      configparser
    ];
  } (builtins.readFile ./mail-distributor.py);

  # YAML-Format für die Generierung der Configs
  configFormat = pkgs.formats.yaml {};

  # Funktion zum Generieren der Config-Dateien pro mail-distributor
  configFiles = mapAttrsToList (name: cfg:
    configFormat.generate "${name}.yml" cfg
  ) config.services.mail-distributor.config;
in
{
  options = {
    services.mail-distributor = {
      enable = mkOption {
        type = types.bool;
        default = false;
        description = "Enable the mail-distributor service.";
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

  config = mkIf config.services.mail-distributor.enable {
    # Stelle sicher, dass das Skript verfügbar ist
    environment.systemPackages = [ mail-distributor ];

    # Systemd-Dienst für das Skript
    systemd.services.mail-distributor = {
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      description = "mail-distributor Daemon";
      serviceConfig = {
        ExecStart = ''
          ${mail-distributor}/bin/mail-distributor ${toString config.services.mail-distributor.configDir}
        '';
        Restart = "always";
        RestartSec = "5s";
      };
    };

    # Generiere die Config-Dateien
    systemd.tmpfiles.rules = map (file: {
      type = "f";
      path = "/etc/mail-distributor/${file}";
      mode = "0644";
      content = config.services.mail-distributor.config.${file};
    }) (builtins.attrNames config.services.mail-distributor.config);

    # Optional: Config-Ordner setzen
    environment.variables.mail-distributor_CONFIG_DIR = "/etc/mail-distributor";
  };
}
