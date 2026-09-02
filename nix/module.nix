self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.oppen-demokrati;
  env = {
    OD_DEBUG = "0";
    OD_STATE_DIR = cfg.stateDir;
    OD_SECRET_KEY_FILE = cfg.secretKeyFile;
    OD_ALLOWED_HOSTS = lib.concatStringsSep "," (
      lib.unique (
        cfg.allowedHosts
        ++ [ "127.0.0.1" ]
        ++ lib.optional (cfg.hostname != "") cfg.hostname
      )
    );
    OD_CSRF_TRUSTED_ORIGINS = lib.concatStringsSep "," (
      cfg.csrfTrustedOrigins
      ++ lib.optional (cfg.hostname != "") "https://${cfg.hostname}"
    );
  };
in
{
  options.services.oppen-demokrati = {
    enable = lib.mkEnableOption "Öppen Demokrati (Django + SQLite)";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { src = self; };
      defaultText = lib.literalExpression "packages.oppen-demokrati";
      description = "Package providing od-web and od-manage.";
    };

    hostname = lib.mkOption {
      type = lib.types.str;
      default = "";
      example = "od.example.com";
      description = "Public hostname, added to ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS.";
    };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Address gunicorn binds to.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "Local gunicorn port.";
    };

    workers = lib.mkOption {
      type = lib.types.ints.positive;
      default = 2;
      description = "Gunicorn workers.";
    };

    stateDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/oppen-demokrati";
      description = "SQLite database, page cache, downloaded zips, collected static files.";
    };

    secretKeyFile = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/oppen-demokrati/secret";
      description = "Django SECRET_KEY file. Created on first start if missing.";
    };

    allowedHosts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Extra Django ALLOWED_HOSTS entries.";
    };

    csrfTrustedOrigins = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Extra CSRF_TRUSTED_ORIGINS.";
    };

    sync = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Daily systemd timer for `od-manage sync_riksdagen`.";
      };

      onCalendar = lib.mkOption {
        type = lib.types.str;
        default = "04:15";
        description = "systemd OnCalendar for the vote/MP sync.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.oppen-demokrati = {
      isSystemUser = true;
      group = "oppen-demokrati";
      home = cfg.stateDir;
    };
    users.groups.oppen-demokrati = { };

    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0750 oppen-demokrati oppen-demokrati -"
      "d ${cfg.stateDir}/cache 0750 oppen-demokrati oppen-demokrati -"
      "d ${cfg.stateDir}/data 0750 oppen-demokrati oppen-demokrati -"
      "d ${cfg.stateDir}/staticfiles 0750 oppen-demokrati oppen-demokrati -"
    ];

    systemd.services.oppen-demokrati = {
      description = "Öppen Demokrati";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      environment = env;
      preStart = ''
        if [ ! -s "${cfg.secretKeyFile}" ]; then
          ${pkgs.openssl}/bin/openssl rand -base64 48 > "${cfg.secretKeyFile}"
          chmod 0600 "${cfg.secretKeyFile}"
        fi
        ${cfg.package}/bin/od-manage migrate --noinput
        ${cfg.package}/bin/od-manage collectstatic --noinput
      '';
      serviceConfig = {
        User = "oppen-demokrati";
        Group = "oppen-demokrati";
        WorkingDirectory = cfg.stateDir;
        ExecStart = "${cfg.package}/bin/od-web --bind ${cfg.listenAddress}:${toString cfg.port} --workers ${toString cfg.workers} --max-requests 1000 --max-requests-jitter 50";
        Restart = "on-failure";
        RestartSec = "5s";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ReadWritePaths = [ cfg.stateDir ];
      };
    };

    systemd.services.oppen-demokrati-sync = lib.mkIf cfg.sync.enable {
      description = "Sync Öppen Demokrati from Riksdagens öppna data";
      after = [
        "network-online.target"
        "oppen-demokrati.service"
      ];
      wants = [ "network-online.target" ];
      environment = env;
      serviceConfig = {
        Type = "oneshot";
        User = "oppen-demokrati";
        Group = "oppen-demokrati";
        WorkingDirectory = cfg.stateDir;
        ExecStart = "${cfg.package}/bin/od-manage sync_riksdagen";
        Nice = 10;
        ReadWritePaths = [ cfg.stateDir ];
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
      };
    };

    systemd.timers.oppen-demokrati-sync = lib.mkIf cfg.sync.enable {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.sync.onCalendar;
        Persistent = true;
        RandomizedDelaySec = "20min";
      };
    };

    environment.systemPackages = [
      (pkgs.writeShellApplication {
        name = "od-manage";
        text = ''
          cd ${lib.escapeShellArg cfg.stateDir}
          ${lib.concatStrings (
            lib.mapAttrsToList (k: v: ''
              export ${k}=${lib.escapeShellArg v}
            '') env
          )}
          exec ${cfg.package}/bin/od-manage "$@"
        '';
      })
    ];
  };
}
