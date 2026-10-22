import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Should Loopdesk build team accounts next?"
AGENTS = ("pmf", "retention", "competitor", "finance", "gtm", "product", "chief")
NAMES = {"chief": "Chief", "pmf": "PMF", "retention": "Retention", "competitor": "Competitor", "finance": "Finance", "gtm": "GTM", "product": "Product"}
ICONS = {"chief": ":compass:", "pmf": ":bar_chart:", "retention": ":heart:", "competitor": ":mag:", "finance": ":moneybag:", "gtm": ":rocket:", "product": ":hammer_and_wrench:"}


@dataclass(frozen=True)
class Settings:
    project: str
    location: str = "global"
    sandbox_location: str = "us-east4"
    model: str = "gemini-3.8-flash"

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if not project:
            raise ValueError("Set GOOGLE_CLOUD_PROJECT in .env.")
        return cls(project, os.getenv("GOOGLE_CLOUD_LOCATION", "global"), os.getenv("SANDBOX_LOCATION", "us-east4"), os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
