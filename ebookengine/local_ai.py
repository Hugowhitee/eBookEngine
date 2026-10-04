"""Optional managed llama.cpp CPU backend. Documents never leave the machine.

No inference/remote actions occur unless the user explicitly requests them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from zipfile import ZipFile

from .core import DocumentError

MODEL_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_URL = ("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
             "a615a81362316d7b9f5a7a9c4313adfdf9b54588/"+MODEL_FILE)
MODEL_SHA256 = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
MODEL_EXPECTED_BYTES = 1_200_000_000


def application_data() -> Path:
    path = Path(os.getenv("LOCALAPPDATA") or Path.home()/".local"/"share")/"eBookEngine"
    path.mkdir(parents=True,exist_ok=True)
    return path


def model_path():return application_data()/"models"/MODEL_FILE

def engine_path():return application_data()/"engines"/"llama"/('llama-cli.exe' if os.name=='nt' else 'llama-cli')


def ready():
    m=model_path();e=engine_path()
    return (m.is_file() and e.is_file() and m.stat().st_size>900_000_000 and e.stat().st_size>100_000)


def _download(url, target, max_bytes, progress, cancelled):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    partial=target.with_suffix(target.suffix+'.part')
    existing=partial.stat().st_size if partial.exists() else 0
    req=urllib.request.Request(url,headers={"User-Agent":"eBookEngine/0.1","Range":f"bytes={existing}-"} if existing else {"User-Agent":"eBookEngine/0.1"})
    with urllib.request.urlopen(req,timeout=25) as source:
        resume=existing>0 and source.status==206
        if existing and not resume:existing=0
        total=int(source.headers.get('Content-Length','0'))+existing
        if total>max_bytes:raise DocumentError('Onverwacht grote download')
        if shutil.disk_usage(target.parent).free < max(total-existing,250*1024*1024):
            raise DocumentError('Onvoldoende schijfruimte voor de installatie')
        with partial.open('ab' if resume else 'wb') as f:
            current=existing
            while True:
                if cancelled and cancelled():raise DocumentError('Download onderbroken; hervatten kan later')
                block=source.read(1024*1024)
                if not block:break
                f.write(block);current+=len(block)
                if current>max_bytes:raise DocumentError('Download groter dan toegestaan')
                if progress:progress(current,total,'Downloaden')
    os.replace(partial,target)
    return target


def install_model(progress=None,cancelled=None):
    target=model_path()
    if target.is_file() and hashlib.file_digest(target.open('rb'),'sha256').hexdigest()==MODEL_SHA256:
        return target
    if progress:progress(0,0,'Model downloaden (ca. 1,12 GB)')
    _download(MODEL_URL,target,1_500_000_000,progress,cancelled)
    with target.open('rb') as f:
        if f.read(4)!=b'GGUF':
            target.unlink(missing_ok=True)
            raise DocumentError('Gedownload bestand is geen GGUF-model')
        f.seek(0)
        if hashlib.file_digest(f,'sha256').hexdigest()!=MODEL_SHA256:
            target.unlink(missing_ok=True)
            raise DocumentError('Modelchecksum onjuist; installatie geannuleerd')
    return target


def install_engine(progress=None,cancelled=None):
    """Install official upstream Windows CPU runtime, isolated in appdata.

    Stable release discovery via verified TLS GitHub API, no scripts or shell.
    """
    if os.name!='nt':
        raise DocumentError('Deze automatische llama-installatie is bedoeld voor Windows x64')
    url='https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'
    req=urllib.request.Request(url,headers={"User-Agent":"eBookEngine/0.1","Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(req,timeout=20) as response:
        release=json.load(response)
    assets=release.get('assets',[])
    matches=[a for a in assets if re.search(r'win-cpu-x64\.zip$',a['name'],re.I) and 'avx512' not in a['name'].lower()]
    if len(matches)!=1:
        raise DocumentError('Geen eenduidige officiële Windows CPU-versie gevonden')
    asset=matches[0]
    digest=asset.get('digest','')
    if not digest.startswith('sha256:'):
        raise DocumentError('Officiële runtime heeft geen verifieerbare checksum')
    target=application_data()/"downloads"/"llama-win.zip"
    _download(asset['browser_download_url'],target,450*1024*1024,progress,cancelled)
    with target.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=digest[7:]:
            target.unlink(missing_ok=True)
            raise DocumentError('Runtimechecksum komt niet overeen')
    destination=engine_path().parent
    destination.mkdir(parents=True,exist_ok=True)
    with ZipFile(target) as archive:
        members=[m for m in archive.infolist() if not m.is_dir()]
        if len(members)>250 or sum(m.file_size for m in members)>1_000_000_000:
            raise DocumentError('Onverwachte runtime-archiefstructuur')
        for m in members:
            # flatten only files needed by llama-cli; avoid arbitrary extraction
            basename=Path(m.filename).name
            if m.file_size>300_000_000:raise DocumentError('Onverwachte runtimegrootte')
            if basename.lower().endswith(('.dll','.exe')):
                (destination/basename).write_bytes(archive.read(m))
    target.unlink(missing_ok=True)
    if not engine_path().is_file():
        raise DocumentError('Gedownloade runtime mist llama-cli.exe')
    return engine_path()


def suggest_description(source_text: str, *,cancelled=None):
    """AI output is an untrusted *proposal*, never applied automatically."""
    if not ready():
        raise DocumentError('Installeer eerst het lokale AI-model en de runtime via Extra')
    prompt=("<|im_start|>system\nYou are preparing a factual bibliographic description. "
            "Use ONLY the evidence in the given excerpts. No invented details. "
            "Return a concise plain-text 2-3 sentence description, no introduction.\n<|im_end|>"
            "<|im_start|>user\n"+source_text[:5500]+"\n<|im_end|><|im_start|>assistant\n")
    cmd=[str(engine_path()),'-m',str(model_path()),'-p',prompt,'-n','250',
         '-c','4096','--temp','0.1','--no-display-prompt','--simple-io']
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,encoding='utf8',errors='replace',creationflags=flags)
    try:
        import time
        started=time.monotonic()
        while True:
            try:
                stdout,stderr=proc.communicate(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                if (cancelled and cancelled()) or time.monotonic()-started>240:
                    proc.kill();proc.communicate()
                    raise DocumentError('AI-verzoek geannuleerd of verlopen')
    finally:
        if proc.poll() is None:proc.kill()
    if proc.returncode:
        raise DocumentError('Lokale AI is mislukt: '+(stderr[-350:] or 'onbekende fout'))
    answer=stdout.strip().split('<|im_end|>')[0].strip()
    if not (20<=len(answer)<=1200) or answer.count('\n')>8:
        raise DocumentError('AI-voorstel is ongeldig; niets aangepast')
    return answer
