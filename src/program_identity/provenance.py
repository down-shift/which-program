"""Filesystem source provenance instrumentation; cooperative, not tamper-proof."""
import hashlib, json, os, sys, importlib.abc, importlib.machinery, importlib.util
from pathlib import Path
import time

def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

class _Loader:
    def __init__(self, loader, fullname): self.loader, self.fullname = loader, fullname
    def create_module(self, spec):
        fn=getattr(self.loader,"create_module",None)
        return fn(spec) if fn else None
    def exec_module(self, module):
        started=time.perf_counter()
        dest=os.environ.get("PI_PROVENANCE_FILE")
        relevant=set(os.environ.get("PI_RELEVANT_MODULES", "").split(","))
        if self.fullname not in relevant: return self.loader.exec_module(module)
        row={"run_id":os.environ.get("PI_RUN_ID"),"command_id":os.environ.get("PI_COMMAND_ID"),"pid":os.getpid(),"ppid":os.getppid(),"interpreter":sys.executable,"cwd":os.getcwd(),"module":self.fullname,"origin":getattr(module.__spec__,"origin",None),"instrumentation":"ok"}
        try:
            origin=Path(module.__spec__.origin).resolve()
            if not isinstance(self.loader, importlib.machinery.SourceFileLoader) or origin.suffix != ".py": raise ValueError("unsupported loader")
            loaded=origin.read_bytes(); row["source_path"]=str(origin); row["loaded_sha256"]=_sha(loaded)
            target=Path(os.environ["PI_TARGET_ROOT"]).resolve()/origin.relative_to(Path(os.environ["PI_IMPORT_ROOT"]).resolve())
            row["target_path"]=str(target); row["target_sha256"]=_sha(target.read_bytes()) if target.is_file() else None
            row["path_match"]=origin==target
            row["content_match"]=row["target_sha256"] == row["loaded_sha256"] if row["target_sha256"] else None
            pyc=importlib.util.cache_from_source(str(origin))
            row["bytecode_cache_present"]=Path(pyc).exists()
            # SourceFileLoader may execute a cached pyc. The harness removes caches and runs -B;
            # if a cache remains, identity is conservatively unknown.
            if row["bytecode_cache_present"]: row["instrumentation"]="unknown"
        except Exception as e: row.update(instrumentation="unknown", error=f"{type(e).__name__}: {e}")
        row["observer_capture_seconds"]=time.perf_counter()-started
        try:
            self.loader.exec_module(module)
        except BaseException as e:
            row["load_error"]=f"{type(e).__name__}: {e}"; raise
        if dest:
            with open(dest,"a") as f: f.write(json.dumps(row,sort_keys=True)+"\n")

class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec and spec.loader and fullname in set(os.environ.get("PI_RELEVANT_MODULES","").split(",")):
            spec.loader=_Loader(spec.loader,fullname)
        return spec

def install():
    if os.environ.get("PI_PROVENANCE_FILE"):
        sys.meta_path.insert(0,_Finder())

install()
