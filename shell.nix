{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = [ pkgs.python314 pkgs.uv ];

  UV_PYTHON = "${pkgs.python314}/bin/python3";
  UV_PYTHON_DOWNLOADS = "never";
  # manylinux wheels pulled in by Home Assistant need these at runtime
  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ];

  shellHook = ''
    uv sync --quiet
    source .venv/bin/activate
  '';
}
