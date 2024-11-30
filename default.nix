{ config, lib, pkgs, ... }:

with lib;

let
  # Python-Skript für den mail-distributor
  mail-distributor = pkgs.writers.writePython3Bin "mail-distributor" {
    libraries = with pkgs.python3Packages; [
      imaplib2
      pyyaml
    ];
    flakeIgnore = [ "E501" "F811" "F841" "W293" "E302" "F821" ];
  } (builtins.readFile ./mail-distributor.py);

  # YAML-Format für die Generierung der Configs
  configFormat = pkgs.formats.yaml {};

  # Verzeichnis im Nix-Store für alle generierten Konfigurationsdateien
  configDir = pkgs.runCommand "mail-distributor-configs" { buildInputs = [ pkgs.makeWrapper ]; } ''
    mkdir -p $out
    ${concatMapStringsSep "\n" (name: ''
      ln -s "${configFormat.generate "${name}.yml" (config.services.mail-distributor.config.${name})}" $out/${name}.yml
    '') (attrNames config.services.mail-distributor.config)}
  '';

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
          ${mail-distributor}/bin/mail-distributor ${configDir}
        '';
        Restart = "always";
        RestartSec = "5s";
      };
    };
  };
}
