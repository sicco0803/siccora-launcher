"""Authenticode-Signatur einer Datei direkt ueber Windows pruefen (WinVerifyTrust).

Kein PowerShell: das kann von Virenscannern oder Firmenrichtlinien blockiert sein -
eine Pruefung, die dann still ausfaellt, waere keine Pruefung.
"""
import ctypes
import uuid
from ctypes import wintypes

_WINTRUST_ACTION_GENERIC_VERIFY_V2 = uuid.UUID("00AAC56B-CD44-11d0-8CC2-00C04FC295EE")
_WTD_UI_NONE, _WTD_REVOKE_NONE, _WTD_CHOICE_FILE = 2, 0, 1
_WTD_STATEACTION_VERIFY, _WTD_STATEACTION_CLOSE = 1, 2
_WTD_CACHE_ONLY_URL_RETRIEVAL = 0x1000  # Sperrlisten nicht aus dem Netz laden (kein Haenger offline)
_CERT_NAME_SIMPLE_DISPLAY_TYPE, _CERT_NAME_ATTR_TYPE, _CERT_NAME_ISSUER_FLAG = 4, 3, 1
_OID_ORGANIZATION = b"2.5.4.10"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, u):
        g = cls()
        ctypes.memmove(ctypes.byref(g), u.bytes_le, 16)
        return g


class _FILE_INFO(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR), ("hFile", wintypes.HANDLE),
                ("pgKnownSubject", ctypes.c_void_p)]


class _WINTRUST_DATA(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
                ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
                ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
                ("pFile", ctypes.POINTER(_FILE_INFO)), ("dwStateAction", wintypes.DWORD),
                ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
                ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
                ("pSignatureSettings", ctypes.c_void_p)]


class _PROVIDER_CERT(ctypes.Structure):  # CRYPT_PROVIDER_CERT (nur der Anfang wird gebraucht)
    _fields_ = [("cbStruct", wintypes.DWORD), ("pCert", ctypes.c_void_p)]


class _PROVIDER_SGNR(ctypes.Structure):  # CRYPT_PROVIDER_SGNR (nur der Anfang wird gebraucht)
    _fields_ = [("cbStruct", wintypes.DWORD), ("sftVerifyAsOf", wintypes.FILETIME), ("csCertChain", wintypes.DWORD),
                ("pasCertChain", ctypes.POINTER(_PROVIDER_CERT))]


def _api():
    wt = ctypes.WinDLL("wintrust")
    c32 = ctypes.WinDLL("crypt32")
    wt.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(_WINTRUST_DATA)]
    wt.WinVerifyTrust.restype = ctypes.c_long
    wt.WTHelperProvDataFromStateData.argtypes = [wintypes.HANDLE]
    wt.WTHelperProvDataFromStateData.restype = ctypes.c_void_p
    wt.WTHelperGetProvSignerFromChain.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    wt.WTHelperGetProvSignerFromChain.restype = ctypes.POINTER(_PROVIDER_SGNR)
    c32.CertGetNameStringW.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.LPWSTR, wintypes.DWORD]
    c32.CertGetNameStringW.restype = wintypes.DWORD
    return wt, c32


def _name(c32, cert, kind, flags, para=None):
    buf = ctypes.create_unicode_buffer(512)
    c32.CertGetNameStringW(cert, kind, flags, para, buf, len(buf))
    return buf.value


def signer(path):
    """"Name|Aussteller-Organisation" bei gueltiger Signatur, sonst None."""
    wt, c32 = _api()
    info = _FILE_INFO(cbStruct=ctypes.sizeof(_FILE_INFO), pcwszFilePath=path)
    data = _WINTRUST_DATA(cbStruct=ctypes.sizeof(_WINTRUST_DATA), dwUIChoice=_WTD_UI_NONE,
                          fdwRevocationChecks=_WTD_REVOKE_NONE, dwUnionChoice=_WTD_CHOICE_FILE,
                          pFile=ctypes.pointer(info), dwStateAction=_WTD_STATEACTION_VERIFY,
                          dwProvFlags=_WTD_CACHE_ONLY_URL_RETRIEVAL)
    action = _GUID.of(_WINTRUST_ACTION_GENERIC_VERIFY_V2)
    try:
        if wt.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data)) != 0:
            return None
        prov = wt.WTHelperProvDataFromStateData(data.hWVTStateData)
        sgnr = wt.WTHelperGetProvSignerFromChain(prov, 0, False, 0) if prov else None
        if not sgnr or sgnr.contents.csCertChain < 1:
            return None
        cert = sgnr.contents.pasCertChain[0].pCert
        subject = _name(c32, cert, _CERT_NAME_SIMPLE_DISPLAY_TYPE, 0)
        issuer_org = _name(c32, cert, _CERT_NAME_ATTR_TYPE, _CERT_NAME_ISSUER_FLAG, ctypes.c_char_p(_OID_ORGANIZATION))
        return f"{subject}|{issuer_org}" if subject else None
    finally:
        data.dwStateAction = _WTD_STATEACTION_CLOSE
        wt.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))
