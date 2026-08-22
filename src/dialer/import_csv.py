"""python -m src.dialer.import_csv <path.csv>

CSV columns: phone (required), name (optional), dnc_flag (optional true/1/yes).
"""

import sys

from src.config import settings
from src.db.repo import import_leads_csv, make_engine, make_session_factory


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m src.dialer.import_csv <path.csv>")
        raise SystemExit(1)

    engine = make_engine(settings.db_path)
    session = make_session_factory(engine)()
    leads = import_leads_csv(session, sys.argv[1])
    session.close()
    print(f"Imported {len(leads)} leads into {settings.db_path}")


if __name__ == "__main__":
    main()
