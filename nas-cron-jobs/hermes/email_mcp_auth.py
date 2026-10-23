"""Compatibility import for the Personal Review email transport."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(os.environ.get("REVIEW_APP_ROOT", "/vol2/1000/Docker/personal-review"))))
from review.sources.email_transport import email_payload, email_session
