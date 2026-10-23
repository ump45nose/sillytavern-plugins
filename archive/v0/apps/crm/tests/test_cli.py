from personal_crm.app.cli import main


def test_migrate_integrity_backup(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'crm.db'))
    monkeypatch.setenv('CRM_ASSET_ROOT',str(tmp_path/'assets'))
    assert main(['migrate'])==0
    assert main(['migrate-legacy'])==0
    assert main(['integrity'])==0
    assert main(['backup',str(tmp_path/'backup.db')])==0
    assert (tmp_path/'backup.db').is_file()


def test_integrated_config_wins_over_legacy_sqlite_env(tmp_path,monkeypatch):
    import json
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'wrong.db'))
    config=tmp_path/'hub.json'
    config.write_text(json.dumps({'database_url':'sqlite:///'+str(tmp_path/'actual.db'),'asset_root':str(tmp_path/'assets')}))
    monkeypatch.setenv('HUB_CONFIG',str(config))
    assert main(['migrate'])==0
    assert (tmp_path/'actual.db').is_file()
    assert not (tmp_path/'wrong.db').exists()
