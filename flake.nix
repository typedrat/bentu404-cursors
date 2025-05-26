{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs @ {flake-parts, ...}:
    flake-parts.lib.mkFlake {inherit inputs;} {
      systems = ["x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin"];

      perSystem = {
        self',
        pkgs,
        lib,
        ...
      }: let
        workspace = inputs.uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ./.;};

        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        hacks = pkgs.callPackage inputs.pyproject-nix.build.hacks {};

        pyprojectOverrides = final: prev: {
          chardet = hacks.nixpkgsPrebuilt {
            from = pkgs.python313Packages.chardet;
            prev = prev.chardet;
          };

          wand = hacks.nixpkgsPrebuilt {
            from = pkgs.python313Packages.wand;
            prev = prev.wand;
          };

          wininfparser = prev.wininfparser.overrideAttrs (old: {
            nativeBuildInputs =
              old.nativeBuildInputs
              ++ [
                (final.resolveBuildSystem {
                  setuptools = [];
                })
              ];
          });
        };

        python = pkgs.python313;

        # Construct package set
        pythonSet =
          (pkgs.callPackage inputs.pyproject-nix.build.packages {
            inherit python;
          }).overrideScope (
            lib.composeManyExtensions [
              inputs.pyproject-build-systems.overlays.default
              overlay
              pyprojectOverrides
            ]
          );
      in {
        packages = let
          makeCursorPackage = name: zip:
            pkgs.stdenvNoCC.mkDerivation (finalAttrs: {
              pname = "bentu404-cursors-${name}";
              version = "0.1.0";
              src = zip;
              sourceRoot = ".";

              nativeBuildInputs = [
                pkgs.unzip
                pkgs.librsvg
                pkgs.xorg.xcursorgen
              ];

              unpackPhase = ''
                runHook preUnpack
                unzip $src -d $(basename $src)
                runHook postUnpack
              '';

              buildPhase = ''
                runHook preBuild
                ${self'.packages.default}/bin/convertcursors $(basename $src)
                ${self'.packages.accurse}/bin/accurse $(find output -iname 'metadata.toml') || true
                runHook postBuild
              '';

              installPhase = ''
                runHook preInstall
                mkdir -p $out/share/icons

                for dir in output/AC-*; do
                  if [ -d "$dir" ]; then
                    newname=$(basename "$dir" | sed 's/^AC-//')
                    cp -R "$dir" "$out/share/icons/$newname"
                  fi
                done

                runHook postInstall
              '';
            });

          cursorJson = lib.importJSON ./cursors/download_tracking.json;
          overridesPath = ./overrides.json;
          overrides =
            if builtins.pathExists overridesPath
            then lib.importJSON overridesPath
            else {};

          cursorPackages = lib.listToAttrs (
            lib.map
            (entry: let
              # Use the name field from the JSON, which is already sanitized
              rawName = entry.name;
              finalName = lib.attrByPath [rawName] rawName overrides;

              file = pkgs.requireFile rec {
                name = "${finalName}.zip";
                sha256 = entry.hash;
                url = entry.url;

                message = ''
                  Unfortunately, we cannot download file '${name}' automatically.
                  Please go to ${url} and download the file '${entry.filename}' yourself,
                  then rename it to '${name}', and add it to the Nix store using either
                    nix-store --add-fixed sha256 ${name}
                  or
                    nix-prefetch-url --type sha256 file:///path/to/${name}
                '';
              };
            in {
              name = finalName;
              value = makeCursorPackage finalName file;
            })
            cursorJson
          );
        in
          {
            default = pythonSet.mkVirtualEnv "bentu404-cursors-env" workspace.deps.default;
            accurse = pkgs.python3Packages.buildPythonApplication rec {
              pname = "accurse";
              version = "0.1.0";
              pyproject = true;

              src = pkgs.fetchPypi {
                inherit pname version;
                hash = "sha256-ozkNbTrfdCfSk4EY1b4gJSKHlhcSlv2Kb1zTkDq6M0s=";
              };

              build-system = [
                pkgs.python3Packages.hatchling
              ];

              dependencies = [
                pkgs.python3Packages.lxml
              ];
            };
          }
          // cursorPackages;

        devShells.default = let
          editableOverlay = workspace.mkEditablePyprojectOverlay {
            root = "$REPO_ROOT";
          };

          editablePythonSet = pythonSet.overrideScope (
            lib.composeManyExtensions [
              editableOverlay

              (final: prev: {
                bentu404-cursors = prev.bentu404-cursors.overrideAttrs (old: {
                  src = lib.fileset.toSource {
                    root = old.src;
                    fileset = lib.fileset.unions [
                      (old.src + "/pyproject.toml")
                      (old.src + "/src/bentu404_cursors/__init__.py")
                    ];
                  };

                  nativeBuildInputs =
                    old.nativeBuildInputs
                    ++ final.resolveBuildSystem {
                      editables = [];
                    };
                });
              })
            ]
          );

          virtualenv = editablePythonSet.mkVirtualEnv "bentu404-cursors-dev-env" workspace.deps.all;
        in
          pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
              pkgs.ruff
              pkgs.librsvg
              pkgs.xorg.xcursorgen
              pkgs.chromedriver
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = "${virtualenv}/bin/python";
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
      };
    };
}
