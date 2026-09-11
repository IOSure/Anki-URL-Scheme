import ctypes
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from anki.utils import is_lin, is_mac, is_win

if is_win:
    import winreg


def register_protocol_handler_windows() -> None:
    try:
        anki_handle = winreg.CreateKeyEx(winreg.HKEY_CLASSES_ROOT, "anki")
        winreg.SetValueEx(anki_handle, "URL Protocol", 0, winreg.REG_SZ, "")
        winreg.SetValueEx(anki_handle, "", 0, winreg.REG_SZ, "Anki URL Protocol")

        # we reuse anki.ankiaddon command value
        try:
            ankiaddon_key = winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                r"anki.ankiaddon\shell\open\command",
                0,
                winreg.KEY_READ,
            )
            command_value = winreg.QueryValue(ankiaddon_key, "")
            ankiaddon_key.Close()
        except:
            command_value = None

        command_handle = winreg.CreateKeyEx(anki_handle, r"shell\open\command")
        if command_value:
            winreg.SetValueEx(command_handle, "", 0, winreg.REG_SZ, command_value)
        else:
            print("Failed to get command value")
    finally:
        for handle in [command_handle, anki_handle]:
            try:
                handle.Close()
            except:
                pass


def register_protocol_handler_linux() -> None:
    try:
        # 1. Create desktop entry file
        apps_dir = os.path.expanduser("~/.local/share/applications")
        os.makedirs(apps_dir, exist_ok=True)

        desktop_content = """[Desktop Entry]
Version=1.0
Name=Anki URI Handler
GenericName=Anki URI Handler
Comment=Handle anki:// links
Exec=anki %u
Terminal=false
Type=Application
Categories=Education;
MimeType=x-scheme-handler/anki;"""

        desktop_path = os.path.join(apps_dir, "anki-protocol-handler.desktop")
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(desktop_content)

        # Make desktop file executable
        os.chmod(desktop_path, 0o755)

        # 2. Create and update MIME type
        mime_dir = os.path.expanduser("~/.local/share/mime")
        os.makedirs(os.path.join(mime_dir, "packages"), exist_ok=True)

        mime_content = """<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
    <mime-type type="x-scheme-handler/anki">
        <comment>Anki URL Handler</comment>
        <glob pattern="anki://*"/>
    </mime-type>
</mime-info>"""

        mime_path = os.path.join(mime_dir, "packages", "anki-protocol.xml")
        with open(mime_path, "w", encoding="utf-8") as f:
            f.write(mime_content)

        # 3. Update system databases
        subprocess.run(["update-mime-database", mime_dir], check=True)
        subprocess.run(
            [
                "xdg-mime",
                "default",
                "anki-protocol-handler.desktop",
                "x-scheme-handler/anki",
            ],
            check=True,
        )

        # 4. Update desktop database
        subprocess.run(["update-desktop-database", apps_dir], check=True)

    except Exception as e:
        print(f"Failed to register Linux protocol handler: {e}")


_MACOS_HELPER_BUNDLE_ID = "com.abdnh.anki-links.url-handler"


def _macos_anki_bundle_identifier() -> str:
    env_bundle_id = os.environ.get("__CFBundleIdentifier")
    if env_bundle_id:
        return env_bundle_id

    candidates = [
        Path("/Applications/Anki.app/Contents/Info.plist"),
        Path.home() / "Applications/Anki.app/Contents/Info.plist",
    ]
    for path in candidates:
        try:
            with path.open("rb") as file:
                bundle_id = plistlib.load(file).get("CFBundleIdentifier")
        except (OSError, plistlib.InvalidFileException):
            continue
        if bundle_id:
            return bundle_id

    # The current Anki launcher. Older releases used net.ankiweb.dtop.
    return "net.ankiweb.launcher"


def _set_macos_protocol_handler_legacy(bundle_id: Optional[str]) -> None:
    core_services = ctypes.CDLL(
        "/System/Library/Frameworks/CoreServices.framework/CoreServices"
    )
    core_foundation = ctypes.CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )

    create_cf_string = core_foundation.CFStringCreateWithCString
    create_cf_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    create_cf_string.restype = ctypes.c_void_p

    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    release.restype = None

    set_handler = core_services.LSSetDefaultHandlerForURLScheme
    set_handler.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    set_handler.restype = ctypes.c_int32

    utf8_encoding = 0x08000100
    scheme = create_cf_string(None, b"anki", utf8_encoding)
    handler = create_cf_string(
        None, (bundle_id or "").encode("utf-8"), utf8_encoding
    )
    if not scheme or not handler:
        if scheme:
            release(scheme)
        if handler:
            release(handler)
        raise OSError("Failed to create macOS protocol handler strings")

    try:
        result = set_handler(scheme, handler)
    finally:
        release(handler)
        release(scheme)

    if result != 0:
        raise OSError(f"LSSetDefaultHandlerForURLScheme failed with status {result}")


def _set_macos_protocol_handler(app_path: Path) -> None:
    script = (
        'ObjC.import("AppKit");'
        f"const appURL = $.NSURL.fileURLWithPath({json.dumps(str(app_path))});"
        "const error = $();"
        "$.NSWorkspace.sharedWorkspace"
        ".setDefaultApplicationAtURLToOpenURLsWithSchemeCompletionHandler("
        'appURL, "anki", (err) => { error.assign(err); });'
        "delay(2);"
        "if (!error.isNil()) {"
        " throw new Error(error.localizedDescription.js);"
        "}"
    )
    try:
        subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        _set_macos_protocol_handler_legacy(_MACOS_HELPER_BUNDLE_ID)


def _macos_helper_app_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "user_files"
        / "Anki URL Handler.app"
    )


def _create_macos_helper_app(path: Path, anki_bundle_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9.-]+", anki_bundle_id):
        raise ValueError(f"Invalid Anki bundle identifier: {anki_bundle_id}")

    path.parent.mkdir(parents=True, exist_ok=True)
    script_path = path.parent / "Anki URL Handler.applescript"
    open_location_handler = "\u00ab" + "event GURLGURL" + "\u00bb"
    script = (
        f"on {open_location_handler} theURL\n"
        '  do shell script "/usr/bin/open -n -b " & quoted form of '
        f'"{anki_bundle_id}" & " --args " & quoted form of theURL\n'
        f"end {open_location_handler}\n"
    )
    script_path.write_text(script, encoding="utf-8")

    if path.exists():
        shutil.rmtree(path)
    subprocess.run(
        ["osacompile", "-o", str(path), str(script_path)],
        check=True,
    )

    info_path = path / "Contents" / "Info.plist"
    with info_path.open("rb") as file:
        info = plistlib.load(file)
    info.update(
        {
            "CFBundleDisplayName": "Anki URL Handler",
            "CFBundleIdentifier": _MACOS_HELPER_BUNDLE_ID,
            "CFBundleName": "Anki URL Handler",
            "CFBundleShortVersionString": "1.0",
            "CFBundleURLTypes": [
                {
                    "CFBundleURLName": "Anki Links",
                    "CFBundleURLSchemes": ["anki"],
                }
            ],
            "LSUIElement": True,
        }
    )
    with info_path.open("wb") as file:
        plistlib.dump(info, file)

    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(path)],
        check=True,
    )
    lsregister = (
        "/System/Library/Frameworks/CoreServices.framework"
        "/Versions/A/Frameworks/LaunchServices.framework"
        "/Versions/A/Support/lsregister"
    )
    subprocess.run([lsregister, "-f", str(path)], check=True)


def register_protocol_handler_macos() -> None:
    helper_path = _macos_helper_app_path()
    _create_macos_helper_app(helper_path, _macos_anki_bundle_identifier())
    _set_macos_protocol_handler(helper_path)


def unregister_protocol_handler_macos() -> None:
    _set_macos_protocol_handler_legacy(None)


def unregister_protocol_handler_windows() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, r"anki\shell\open\command")
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, r"anki\shell\open")
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, r"anki\shell")
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, "anki")
    except OSError as e:
        print(f"Failed to unregister Windows protocol handler: {e}")


def unregister_protocol_handler_linux() -> None:
    try:
        # Remove desktop file
        apps_dir = os.path.expanduser("~/.local/share/applications")
        desktop_path = os.path.join(apps_dir, "anki-protocol-handler.desktop")
        if os.path.exists(desktop_path):
            os.remove(desktop_path)

        # Remove MIME database entry
        mime_dir = os.path.expanduser("~/.local/share/mime")
        mime_path = os.path.join(mime_dir, "packages", "anki-protocol.xml")
        if os.path.exists(mime_path):
            os.remove(mime_path)
            # Update MIME database
            subprocess.run(["update-mime-database", mime_dir], check=True)
            # Remove protocol association
            subprocess.run(["xdg-mime", "unset", "x-scheme-handler/anki"], check=True)
    except Exception as e:
        print(f"Failed to unregister Linux protocol handler: {e}")


def check_admin_windows() -> bool:
    import ctypes

    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def register_protocol_handler() -> None:
    """Register the protocol handler for the current platform"""

    if is_win:
        if not check_admin_windows():
            raise OSError(
                "Failed to register protocol handler. Make sure to run Anki as admin to perform this operation"
            )
        register_protocol_handler_windows()
    elif is_mac:
        register_protocol_handler_macos()
    elif is_lin:
        register_protocol_handler_linux()
    else:
        raise NotImplementedError(f"Platform {sys.platform} not supported")


def unregister_protocol_handler() -> None:
    if is_win:
        if not check_admin_windows():
            raise OSError(
                "Failed to unregister protocol handler. Make sure to run Anki as admin to perform this operation"
            )
        unregister_protocol_handler_windows()
    elif is_mac:
        unregister_protocol_handler_macos()
    elif is_lin:
        unregister_protocol_handler_linux()
    else:
        raise NotImplementedError(f"Platform {sys.platform} not supported (2)")
