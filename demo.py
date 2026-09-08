"""python demo.py

The single, no-API-key-needed, end-to-end walkthrough: CSV import -> dialer
-> conversation -> dashboard -> the "Java, Mumbai, under 60 days" query.
See src/dialer/demo.py for the implementation.
"""

# langgraph emits a PendingDeprecationWarning as it imports, and langchain_core
# re-enables that whole category itself while *it* imports -- so a filter set
# before either of them loses the ordering race. Importing langchain_core
# first, then filtering, then importing the app, is what actually wins.
# This script is meant to be read by a human: a stderr warning above the first
# banner reads as something having gone wrong. Every other entrypoint, and the
# test suite, still surface it.
import warnings

import langchain_core._api.deprecation  # noqa: F401 -- imported for its import-time side effect

warnings.simplefilter("ignore", PendingDeprecationWarning)

from src.dialer.demo import main  # noqa: E402 -- must follow the filter above

if __name__ == "__main__":
    main()
