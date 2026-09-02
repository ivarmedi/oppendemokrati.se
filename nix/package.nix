{
  lib,
  python312,
  writeShellScriptBin,
  symlinkJoin,
  runCommand,
  src,
}:
let
  python = python312.withPackages (
    ps: with ps; [
      django
      httpx
      gunicorn
      whitenoise
    ]
  );
  app = runCommand "oppen-demokrati-src" { } ''
    mkdir -p $out
    cp -r ${src}/manage.py ${src}/config ${src}/riksdag $out/
  '';
in
symlinkJoin {
  name = "oppen-demokrati";
  paths = [
    (writeShellScriptBin "od-web" ''
      export DJANGO_SETTINGS_MODULE=config.settings
      exec ${python}/bin/gunicorn --pythonpath ${app} "$@" config.wsgi:application
    '')
    (writeShellScriptBin "od-manage" ''
      export DJANGO_SETTINGS_MODULE=config.settings
      exec ${python}/bin/python ${app}/manage.py "$@"
    '')
  ];
  passthru = {
    inherit python app;
  };
  meta = {
    description = "Öppen Demokrati — riksdagsledamöter och voteringar";
    mainProgram = "od-web";
  };
}
