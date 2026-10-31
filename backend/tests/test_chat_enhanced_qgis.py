from __future__ import annotations

from app.services.desktop_workflows import infer_desktop_launch_actions


def test_infer_desktop_launch_actions_opens_qgis_for_project_file_without_explicit_qgis_word():
    actions = infer_desktop_launch_actions(
        'Öffne die Datei C:\\GIS\\Projekt\\meine_karte.qgz und analysiere sie.',
        '',
        profile='generic',
    )

    assert actions, 'Expected at least one desktop action'
    first = actions[0]
    assert first['action'] == 'launch_app'
    assert first['command'] == 'qgis'
    assert first['file'] == 'C:\\GIS\\Projekt\\meine_karte.qgz'


def test_infer_desktop_launch_actions_uses_qgis_profile_for_geodata_paths():
    actions = infer_desktop_launch_actions(
        'Lade /data/fotos.shp und bereite eine Karte vor.',
        '',
        profile='qgis',
    )

    assert actions, 'Expected at least one desktop action'
    first = actions[0]
    assert first['action'] == 'launch_app'
    assert first['command'] == 'qgis'
    assert first['file'] == '/data/fotos.shp'
