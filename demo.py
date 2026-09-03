"""
demo.py -- runs the full four-layer pipeline against the illustrative
dashboard_app/ fixtures (see build_sample_data.py) and prints the resulting
CEO memo. This is the fastest way to see the whole system work end to end:

    pip install -r requirements.txt
    python build_sample_data.py
    python demo.py

No real business data required -- everything read here is fabricated,
plausible-looking sample data checked into this repo.
"""
import os
import sys"""
demo.py -- runs the full four-layer pipeline against the illustrative
dashboard_app/ fixtures (see build_sample_data.py) and prints the resulting
CEO memo. This is the fastest way to see the whole system work end to end:

    pip install -r requirements.txt
    python build_sample_data.py
    python demo.py

No real business data required -- everything read here is fabricated,
plausible-looking sample data checked into this repo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senior_managers.cfo_executive_audit import run_cfo_audit
from senior_managers.coo_operations_audit import run_coo_audit
from senior_managers.controller_audit import run_controller_audit
from capstone.ceo_weekly_memo import run_ceo_memo

if __name__ == "__main__":
    print("############################################")
    print("# Layer 3 -- Senior Managers")
    print("############################################\n")
    run_cfo_audit()
    print()
    run_coo_audit()
    print()
    run_controller_audit()

    print("\n############################################")
    print("# Layer 4 -- CEO Capstone Memo")
    print("############################################\n")
    run_ceo_memo()


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senior_managers.cfo_executive_audit import run_cfo_audit
from senior_managers.coo_operations_audit import run_coo_audit
from senior_managers.controller_audit import run_controller_audit
from capstone.ceo_weekly_memo import run_ceo_memo

if __name__ == "__main__":
    print("############################################")
    print("# Layer 3 -- Senior Managers")
    print("############################################\n")
    run_cfo_audit()
    print()
    run_coo_audit()
    print()
    run_controller_audit()

    print("\n############################################")
    print("# Layer 4 -- CEO Capstone Memo")
    print("############################################\n")
    run_ceo_memo()

