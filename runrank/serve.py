"""Start the RunnasUP API + built frontend on 127.0.0.1 only.

  python -m runrank.serve            personal database data/runrank.sqlite (or $RUNRANK_DB)
  python -m runrank.serve --demo     separate synthetic demo database data/demo/runrank-demo.sqlite
"""
import argparse
import os
import pathlib

import uvicorn

from . import api, store

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO_DB = ROOT / "data" / "demo" / "runrank-demo.sqlite"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="use the separate synthetic demo database")
    ap.add_argument("--reset-demo", action="store_true", help="delete the demo database first (demo only)")
    ap.add_argument("--port", type=int, default=8600)
    args = ap.parse_args()
    if args.demo:
        if args.reset_demo and DEMO_DB.exists():
            DEMO_DB.unlink()              # only ever the synthetic demo file
        db, kind = str(DEMO_DB), "demo"
    else:
        if args.reset_demo:
            ap.error("--reset-demo only applies with --demo")
        db = os.environ.get("RUNRANK_DB") or store.DEFAULT_DB
        kind = "personal" if db == store.DEFAULT_DB else "custom"
    store.connect(db).close()             # create / migrate before serving
    app = api.create_app(db, demo_mode=args.demo, database=kind)
    print("RunnasUP on http://127.0.0.1:%d  (database: %s, %s)" % (args.port, kind, db), flush=True)
    # access_log off: query strings (e.g. activity-title searches) stay out of the terminal
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
