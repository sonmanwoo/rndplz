from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path


class StateStore:
    """One atomic state file; process lock also protects CLI/server overlap."""
    def __init__(self, directory):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/"state.json"
        self.lock=threading.RLock()

    def read(self):
        if not self.path.exists():
            return {"version":1,"sessions":[],"proposals":[],"idempotency":{}}
        data=json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version")!=1 or not all(isinstance(data.get(k),list) for k in ("sessions","proposals")):
            raise ValueError("저장소 형식을 확인할 수 없습니다. 원본을 보존했습니다.")
        return data

    def transaction(self, fn):
        with self.lock:
            lockfile=self.directory/"state.lock"
            deadline=time.monotonic()+3
            while True:
                try:
                    fd=os.open(lockfile,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
                    os.close(fd)
                    break
                except FileExistsError:
                    if time.monotonic()>deadline:
                        raise ValueError("다른 저장 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.")
                    time.sleep(.03)
            temporary=self.directory/"state.next.json"
            try:
                state=copy.deepcopy(self.read())
                result=fn(state)
                with temporary.open("w",encoding="utf-8") as f:
                    json.dump(state,f,ensure_ascii=False,indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary,self.path)
                return result
            finally:
                lockfile.unlink(missing_ok=True)
