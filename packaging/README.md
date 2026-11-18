# Packaging Video Blender

## Mac (this machine)

```bash
bash packaging/build_mac.sh
```

Output:
- `dist/Video Blender.app`
- `dist/Video-Blender-1.0.0-mac-arm64.dmg`

## Windows

Build on a Windows machine or via GitHub Actions:

```powershell
./packaging/build_windows.ps1
```

Output:
- `dist/Video-Blender-1.0.0-windows-x64.zip` (contains `Video Blender.exe`)

## CI

Push a tag `v1.0.0` (or run the workflow manually) to build Mac + Windows artifacts.
