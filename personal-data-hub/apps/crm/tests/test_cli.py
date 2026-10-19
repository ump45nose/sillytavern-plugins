from personal_crm.app.cli import main


def test_migrate_integrity_backup(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'crm.db'))
    monkeypatch.setenv('CRM_ASSET_ROOT',str(tmp_path/'assets'))
    assert main(['migrate'])==0
    assert main(['migrate-legacy'])==0
    assert main(['integrity'])==0
    assert main(['backup',str(tmp_path/'backup.db')])==0
    assert (tmp_path/'backup.db').is_file()
