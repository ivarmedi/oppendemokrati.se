{
  description = "Öppen Demokrati";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      forAllSystems =
        f:
        nixpkgs.lib.genAttrs systems (
          system:
          f {
            inherit system;
            pkgs = nixpkgs.legacyPackages.${system};
          }
        );
    in
    {
      packages = forAllSystems (
        { pkgs, ... }:
        rec {
          oppen-demokrati = pkgs.callPackage ./nix/package.nix { src = self; };
          default = oppen-demokrati;
        }
      );

      apps = forAllSystems (
        { pkgs, system }:
        let
          pkg = self.packages.${system}.default;
        in
        {
          default = {
            type = "app";
            program = "${pkg}/bin/od-web";
          };
          web = {
            type = "app";
            program = "${pkg}/bin/od-web";
          };
          manage = {
            type = "app";
            program = "${pkg}/bin/od-manage";
          };
          sync = {
            type = "app";
            program = "${
              pkgs.writeShellApplication {
                name = "od-sync";
                text = ''
                  exec ${pkg}/bin/od-manage sync_riksdagen "$@"
                '';
              }
            }/bin/od-sync";
          };
        }
      );

      devShells = forAllSystems (
        { pkgs, system }:
        {
          default = pkgs.mkShell {
            packages = [
              self.packages.${system}.default.python
            ];
            env.DJANGO_SETTINGS_MODULE = "config.settings";
          };
        }
      );

      nixosModules.default = import ./nix/module.nix self;
      nixosModules.oppen-demokrati = self.nixosModules.default;

      formatter = forAllSystems ({ pkgs, ... }: pkgs.nixfmt-rfc-style);
    };
}
