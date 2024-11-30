{
  inputs = {
    nixpkgs.url = "github:Nixos/nixpkgs/nixos-24.05";
  };

  outputs = { ... }: rec {
    nixosModules = rec {
      verteiler = import ./default.nix;
      default = verteiler;
    };
    nixosModule = nixosModules.default;
  };
}