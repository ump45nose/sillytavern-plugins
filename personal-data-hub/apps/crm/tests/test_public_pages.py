"""Personal Review OAuth 公开说明页回归测试。"""

from fastapi.testclient import TestClient

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.archive import Archive


def test_personal_review_public_pages(tmp_path) -> None:
    """首页必须链接隐私政策，且三个公开页面均可匿名读取。"""

    repository = Archive(f"sqlite:///{tmp_path / 'crm.db'}", tmp_path / "assets")
    client = TestClient(create_app(Settings(mcp_development_no_auth=True), repository))

    homepage = client.get("/personal-review")
    privacy = client.get("/personal-review/privacy")
    terms = client.get("/personal-review/terms")

    assert homepage.status_code == 200
    assert "/personal-review/privacy" in homepage.text
    assert privacy.status_code == 200
    assert "Google API Services User Data Policy" in privacy.text
    assert terms.status_code == 200
