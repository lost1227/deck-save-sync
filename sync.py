from paramiko.client import SSHClient, AutoAddPolicy
from paramiko.sftp_client import SFTPClient

from pathlib import Path
from datetime import datetime
import subprocess
import shutil
import os

import argparse

GAME_TITLE_ID = '01007EF00011E000'
BACKUP_DIR = Path.cwd() / 'backups'
LOCAL_DIR = Path(r"C:\Users\jordan\AppData\Roaming\yuzu\nand\user\save\0000000000000000\AD96ACCE265449B059D3511A624BBE75")
REMOTE_DIR = Path("/run/media/mmcblk0p1/Emulation/storage/yuzu/nand/user/save/0000000000000000/96B282AE2D8C616DFE7CE59BE4B8F856")
REMOTE_HOST = "192.168.1.168:8022"
USERNAME = "deck"
KEYFILE = Path.home() / ".ssh/id_rsa"

EXE_7ZIP_PATH = Path(r"C:\Program Files\7-Zip\7z.exe")

KNOWN_HOSTS = Path.home() / ".ssh/known_hosts"

parser = argparse.ArgumentParser()
parser.add_argument('--id', default=GAME_TITLE_ID)

args = parser.parse_args()

if not BACKUP_DIR.is_dir():
    BACKUP_DIR.mkdir()

backup_dir = BACKUP_DIR / args.id
if not backup_dir.is_dir():
    backup_dir.mkdir()

local_dir = LOCAL_DIR / args.id
remote_dir = REMOTE_DIR / args.id

assert backup_dir.is_dir()
assert KEYFILE.is_file()

if ":" in REMOTE_HOST:
    host, port = REMOTE_HOST.split(":")
    port = int(port)
else:
    host = REMOTE_HOST
    port = 22

if local_dir.is_dir():
    local_mtime = 0
    for path in local_dir.glob("**/*"):
        if not path.is_file():
            continue
        mtime = path.stat().st_mtime
        local_mtime = max(local_mtime, mtime)
    local_mtime = datetime.fromtimestamp(local_mtime)

    print("Backing up local files...")
    zipname = args.id + '_' + local_mtime.strftime('%Y%m%d_%H%M%S')
    local_backup = backup_dir / (zipname + ".zip")
    if local_backup.exists():
        local_backup.unlink()
    os.chdir(backup_dir)
    shutil.make_archive(zipname, 'zip', root_dir=local_dir.parent, base_dir=local_dir.name)
else:
    local_mtime = datetime.fromtimestamp(0)

with SSHClient() as ssh:
    ssh.load_host_keys(KNOWN_HOSTS)
    ssh.set_missing_host_key_policy(AutoAddPolicy)

    ssh.connect(host, port=port, username=USERNAME, key_filename=str(KEYFILE))

    _, stdout, _ = ssh.exec_command(f"test -d {remote_dir.as_posix()} ; echo $?")
    remote_dir_exists = stdout.read().decode('utf-8').strip() == '0'

    if remote_dir_exists:
        _, stdout, stderr = ssh.exec_command(f"find {remote_dir.as_posix()} -printf \"%T@\\n\" | sort -nr | head -n 1")
        remote_mtime_str = stdout.read().decode('utf-8').strip()
        assert remote_mtime_str

        remote_mtime = datetime.fromtimestamp(float(remote_mtime_str))

        print("Backing up remote files...")
        zipname = args.id + '_' + remote_mtime.strftime('%Y%m%d_%H%M%S') + '.zip'
        _, stdout, stderr = ssh.exec_command(f"cd {remote_dir.parent.as_posix()} && zip -r - {remote_dir.name}")
        remote_backup = backup_dir / zipname
        with remote_backup.open("wb") as outf:
            outf.write(stdout.read())
    else:
        remote_mtime = datetime.fromtimestamp(0)

    print("local: ", local_mtime)
    print("remote:", remote_mtime)

    if abs((remote_mtime - local_mtime).total_seconds()) < 5:
        print("Saves are already synchronized.")
        exit()

    is_download = local_mtime < remote_mtime

    if is_download:
        print("Will overwrite local save.")
    else:
        print("Will overwrite remote save.")

    while True:
        response = input('Continue? (y/n)> ').strip().lower()
        if response == 'n':
            exit()
        elif response == 'y':
            break
        else:
            print('Invalid response.')

    if is_download:
        shutil.rmtree(local_dir)
        subprocess.run([EXE_7ZIP_PATH, 'x', str(remote_backup), '-o'+str(local_dir.parent)])
    else:
        _, stdout, _ = ssh.exec_command("mktemp /tmp/sync.XXXXXX.zip")
        tempfile = stdout.read().decode('utf-8').strip()
        stdin, _, stderr = ssh.exec_command(f"cat > {tempfile}")
        with local_backup.open('rb') as inf:
            stdin.write(inf.read())
        print(tempfile)
        _, stdout, _ = ssh.exec_command(f"rm -r {remote_dir.as_posix()}")
        print(stdout.read().decode("utf-8").strip())
        _, stdout, _ = ssh.exec_command(f"unzip {tempfile} -d {remote_dir.parent.as_posix()} && rm {tempfile}")
        print(stdout.read().decode("utf-8").strip())

